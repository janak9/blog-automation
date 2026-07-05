import json
import os
import re
from typing import Dict, List

from agency_swarm.tools import BaseTool
from pydantic import Field

DEFAULT_REPO = "/Users/janakvaghela/projects/legresca/v-try-on"

BLOG_DATA_REL = "lib/blog-data.ts"
MESSAGES = {"en": "messages/en.json", "hi": "messages/hi.json", "gu": "messages/gu.json"}

BLOG_ARRAY_MARKER = "export const BLOG_POSTS: BlogPost[] = ["


def _insert_json_post(path: str, slug: str, entry: dict) -> str:
    """Insert `entry` as the first property of blog.posts in a messages JSON file.

    Uses targeted text insertion (not full re-serialization) so the diff stays
    minimal, then validates that the whole file still parses as JSON.
    """
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if f'"{slug}"' in content:
        return f"SKIP: slug '{slug}' already present in {os.path.basename(path)}."

    blog_idx = content.find('"blog"')
    if blog_idx == -1:
        return f"Error: '\"blog\"' key not found in {path}."
    posts_idx = content.find('"posts"', blog_idx)
    if posts_idx == -1:
        return f"Error: 'blog.posts' key not found in {path}."
    brace_idx = content.find("{", posts_idx)
    if brace_idx == -1:
        return f"Error: could not locate opening brace of blog.posts in {path}."
    insert_pos = brace_idx + 1

    # Detect the indentation used by the first existing property.
    m = re.match(r"\n(\s*)\S", content[insert_pos:])
    indent = m.group(1) if m else "      "

    body_lines = json.dumps(entry, ensure_ascii=False, indent=2).split("\n")
    block_lines = [f'{indent}"{slug}": {body_lines[0]}']
    block_lines += [indent + line for line in body_lines[1:]]
    new_block = "\n" + "\n".join(block_lines) + ","

    new_content = content[:insert_pos] + new_block + content[insert_pos:]

    # Validate before writing — never leave a broken JSON file behind.
    try:
        json.loads(new_content)
    except json.JSONDecodeError as e:
        return f"Error: insertion into {os.path.basename(path)} produced invalid JSON: {e}"

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return f"OK: added '{slug}' to {os.path.basename(path)}."


def _insert_ts_post(path: str, slug: str, ts_object: str) -> str:
    """Insert a blog object as the first element of the BLOG_POSTS array."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if f'slug: "{slug}"' in content or f"slug: '{slug}'" in content:
        return f"SKIP: slug '{slug}' already present in {os.path.basename(path)}."

    idx = content.find(BLOG_ARRAY_MARKER)
    if idx == -1:
        return f"Error: BLOG_POSTS array marker not found in {path}."
    insert_pos = idx + len(BLOG_ARRAY_MARKER)

    obj = ts_object.strip()
    if not obj.startswith("{"):
        return "Error: blog_post_ts must be a TS object literal starting with '{'."
    obj = obj.rstrip().rstrip(",")
    # Re-indent every line by two spaces so it sits cleanly inside the array.
    indented = "\n".join(("  " + line) if line.strip() else line for line in obj.split("\n"))
    new_block = "\n" + indented + ","

    new_content = content[:insert_pos] + new_block + content[insert_pos:]
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return f"OK: added '{slug}' to {os.path.basename(path)} (as first entry)."


class InsertBlogPost(BaseTool):
    """
    Wires a single approved blog post into the v-try-on codebase across all four
    files needed for full i18n support:

      1. lib/blog-data.ts    -> appends the English blog object to BLOG_POSTS (first entry)
      2. messages/en.json    -> blog.posts.<slug> metadata (title/description/category/author)
      3. messages/hi.json    -> blog.posts.<slug> FULL Hindi translation (incl. content + faqs)
      4. messages/gu.json    -> blog.posts.<slug> FULL Gujarati translation (incl. content + faqs)

    JSON files are edited in place with minimal diffs and validated before writing.
    If the slug already exists in any file, that file is skipped (idempotent).

    IMPORTANT — you must produce the Hindi and Gujarati translations yourself and pass
    them as hi_entry / gu_entry. Each must be a complete object with keys:
    title, description, category, authorName, authorRole, content (translated array of
    the same ContentBlock shapes), and faqs (translated array of {question, answer}).
    Keep every `type`, `src`, `url`, `level`, and structural field identical to English;
    translate only human-readable text (text/alt/caption/label/items/question/answer).
    """

    slug: str = Field(..., description="The blog post slug (must match the slug in blog_post_ts).")
    blog_post_ts: str = Field(
        ...,
        description="The complete English blog object literal (TypeScript) to insert into BLOG_POSTS, "
        "starting with '{' and ending with '}'. May use ${BASE_IMAGE_URL} template literals.",
    )
    en_meta: Dict = Field(
        ...,
        description="English metadata object for en.json: {title, description, category, authorName, authorRole}.",
    )
    hi_entry: Dict = Field(
        ...,
        description="Full Hindi translation object for hi.json: title, description, category, authorName, "
        "authorRole, content (array), faqs (array).",
    )
    gu_entry: Dict = Field(
        ...,
        description="Full Gujarati translation object for gu.json (same shape as hi_entry).",
    )
    repo_path: str = Field(
        default=DEFAULT_REPO, description="Absolute path to the v-try-on repository."
    )

    def run(self):
        repo = self.repo_path
        results: List[str] = []

        ts_path = os.path.join(repo, BLOG_DATA_REL)
        if not os.path.isfile(ts_path):
            return f"Error: {ts_path} not found."
        results.append(_insert_ts_post(ts_path, self.slug, self.blog_post_ts))

        for loc, entry in (
            ("en", self.en_meta),
            ("hi", self.hi_entry),
            ("gu", self.gu_entry),
        ):
            path = os.path.join(repo, MESSAGES[loc])
            if not os.path.isfile(path):
                results.append(f"Error: {path} not found.")
                continue
            results.append(_insert_json_post(path, self.slug, entry))

        ok = all(r.startswith("OK") or r.startswith("SKIP") for r in results)
        header = "All files updated." if ok else "Completed with errors — review below."
        return header + "\n" + "\n".join(f"  - {r}" for r in results)


if __name__ == "__main__":
    print(InsertBlogPost.__doc__)
