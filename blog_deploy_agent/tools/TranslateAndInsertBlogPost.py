"""Translate a blog post into Hindi + Gujarati (in parallel) and wire it into the repo.

This is the fast path for deployment. It runs the two translations CONCURRENTLY (one
LLM call per language, in separate threads) and inserts the English post + both
translations into all four files itself — so the large translated JSON never has to be
regenerated token-by-token by the agent. Reuses InsertBlogPost's file-insertion helpers.
"""

import concurrent.futures
import json
import os

from agency_swarm.tools import BaseTool
from pydantic import Field

from shared_tools.openai_client_utils import get_openai_client

from .InsertBlogPost import (
    BLOG_DATA_REL,
    DEFAULT_REPO,
    MESSAGES,
    _insert_json_post,
    _insert_ts_post,
)

_LANGS = {"hi": "Hindi", "gu": "Gujarati"}

_SYS_PROMPT = (
    "You are a professional translator for a fashion e-commerce / AI blog (brand: Vtryon). "
    "You translate blog post JSON precisely and naturally."
)


def _translate_prompt(lang_name: str, payload: dict) -> str:
    return (
        f"Translate the following blog post into {lang_name}.\n\n"
        "RULES:\n"
        "- Translate ONLY human-readable text: title, description, category, authorRole, and inside "
        "each content block the fields text/alt/caption/label and every string in list `items`, and "
        "inside each faq the question and answer.\n"
        "- Keep ALL structural fields identical and untranslated: type, level, src, url.\n"
        "- Keep `authorName` exactly as given (do not translate brand/author names like 'Vtryon "
        "Editorial', 'WhatsApp', company names).\n"
        "- Preserve Markdown emphasis such as **bold**.\n"
        "- The translated `content` array MUST have the same number and order of blocks as the "
        "source, and `faqs` the same number of items.\n"
        "- Return ONLY a single JSON object with keys: title, description, category, authorName, "
        "authorRole, content (array), faqs (array). No prose, no code fences.\n\n"
        f"SOURCE JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )


class TranslateAndInsertBlogPost(BaseTool):
    """
    Fast deploy step: translate an approved blog into Hindi + Gujarati IN PARALLEL and insert the
    English post plus both translations into all four files (lib/blog-data.ts, messages/en.json,
    messages/hi.json, messages/gu.json), with JSON validation.

    Call this ONCE with the approved English post. You do NOT need to write the translations
    yourself or call InsertBlogPost separately — this tool does both, concurrently.

    Provide the English content/faq so the tool can translate them; metadata (title/description/
    category/authorName/authorRole) comes from en_meta.
    """

    slug: str = Field(..., description="The blog post slug (must match the slug in blog_post_ts).")
    blog_post_ts: str = Field(
        ...,
        description="The complete English blog object literal (TypeScript) for BLOG_POSTS, starting "
        "with '{' and ending with '}'. May use ${BASE_IMAGE_URL} template literals.",
    )
    en_meta: dict = Field(
        ...,
        description="English metadata: {title, description, category, authorName, authorRole}.",
    )
    content: list = Field(
        ...,
        description="The English `content` array (ContentBlock objects) to translate.",
    )
    faq: list = Field(
        default_factory=list,
        description="The English `faq` array ({question, answer}) to translate (becomes `faqs`).",
    )
    repo_path: str = Field(default=DEFAULT_REPO, description="Absolute path to the v-try-on repo.")

    def _translate(self, lang_code: str) -> tuple[str, dict]:
        client = get_openai_client(tool=self)
        model = os.getenv("TRANSLATE_MODEL") or os.getenv("DEFAULT_MODEL", "gpt-5.4")
        payload = {
            "title": self.en_meta.get("title", ""),
            "description": self.en_meta.get("description", ""),
            "category": self.en_meta.get("category", ""),
            "authorName": self.en_meta.get("authorName", ""),
            "authorRole": self.en_meta.get("authorRole", ""),
            "content": self.content,
            "faqs": self.faq or [],
        }
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYS_PROMPT},
                {"role": "user", "content": _translate_prompt(_LANGS[lang_code], payload)},
            ],
            response_format={"type": "json_object"},
        )
        entry = json.loads(resp.choices[0].message.content)
        # Never let the brand/author name drift.
        entry["authorName"] = self.en_meta.get("authorName", entry.get("authorName", ""))
        return lang_code, entry

    def run(self):
        repo = self.repo_path
        # 1) Translate hi + gu concurrently.
        entries: dict[str, dict] = {}
        errors: list[str] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = {pool.submit(self._translate, code): code for code in _LANGS}
            for fut in concurrent.futures.as_completed(futures):
                code = futures[fut]
                try:
                    lang, entry = fut.result()
                    entries[lang] = entry
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{_LANGS[code]} translation failed: {type(exc).__name__}: {exc}")

        if errors:
            return "Translation error — nothing was written:\n" + "\n".join(f"  - {e}" for e in errors)

        # Sanity: block/faq counts should match the English source.
        warnings = []
        for code, entry in entries.items():
            if len(entry.get("content", [])) != len(self.content):
                warnings.append(
                    f"{_LANGS[code]}: content block count {len(entry.get('content', []))} != "
                    f"English {len(self.content)}"
                )
            if len(entry.get("faqs", [])) != len(self.faq or []):
                warnings.append(
                    f"{_LANGS[code]}: faq count {len(entry.get('faqs', []))} != English {len(self.faq or [])}"
                )

        # 2) Insert everything (English + both translations) into the four files.
        results = []
        ts_path = os.path.join(repo, BLOG_DATA_REL)
        if not os.path.isfile(ts_path):
            return f"Error: {ts_path} not found."
        results.append(_insert_ts_post(ts_path, self.slug, self.blog_post_ts))
        results.append(_insert_json_post(os.path.join(repo, MESSAGES["en"]), self.slug, self.en_meta))
        results.append(_insert_json_post(os.path.join(repo, MESSAGES["hi"]), self.slug, entries["hi"]))
        results.append(_insert_json_post(os.path.join(repo, MESSAGES["gu"]), self.slug, entries["gu"]))

        ok = all(r.startswith(("OK", "SKIP")) for r in results)
        header = "Translated (hi+gu in parallel) and inserted into all files." if ok else \
            "Completed with errors — review below."
        out = header + "\n" + "\n".join(f"  - {r}" for r in results)
        if warnings:
            out += "\n  ⚠ count mismatch (review the translation):\n" + "\n".join(f"    · {w}" for w in warnings)
        return out


if __name__ == "__main__":
    print(TranslateAndInsertBlogPost.__doc__)
