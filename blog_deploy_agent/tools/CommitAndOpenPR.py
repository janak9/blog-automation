import json
import os
import re
import subprocess
import urllib.request

from agency_swarm.tools import BaseTool
from pydantic import Field

DEFAULT_REPO = "/Users/janakvaghela/projects/legresca/v-try-on"


def _run(args, cwd):
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=180)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def _parse_remote(remote_url: str):
    """Extract (token, owner, repo) from an https github remote URL.

    Supports 'https://user:token@github.com/owner/repo(.git)'. Token may be absent.
    """
    m = re.match(
        r"https://(?:([^@/]+)@)?github\.com/([^/]+)/([^/.]+)(?:\.git)?/?$", remote_url.strip()
    )
    if not m:
        return None, None, None
    creds, owner, repo = m.group(1), m.group(2), m.group(3)
    token = None
    if creds and ":" in creds:
        token = creds.split(":", 1)[1]
    elif creds:
        token = creds
    return token, owner, repo


class CommitAndOpenPR(BaseTool):
    """
    Commits the staged blog changes, pushes the feature branch to origin, and opens a
    pull request against the base branch (main) using the GitHub API.

    Preconditions: PrepareBlogBranch and InsertBlogPost have already run, so the repo is
    on the feature branch with the blog wired into blog-data.ts and the message files
    (and any generated images copied into public/blog).

    The PR — not a direct push to main — is the deploy trigger: a human reviewer merges it.
    Returns the PR URL on success.
    """

    branch_name: str = Field(..., description="The feature branch to push (already checked out).")
    commit_message: str = Field(..., description="Commit message, e.g. 'feat(blog): add <slug> post with hi/gu i18n'.")
    pr_title: str = Field(..., description="Pull request title.")
    pr_body: str = Field(
        ...,
        description="Pull request description (markdown). Summarize the post, languages added, and files changed.",
    )
    repo_path: str = Field(default=DEFAULT_REPO, description="Absolute path to the v-try-on repository.")
    base_branch: str = Field(
        default="",
        description="PR base branch (the branch the PR merges INTO). Defaults to the "
        "DEPLOY_BASE_BRANCH env var, or 'main' if unset. Set to 'dev' to open the PR against dev. "
        "Must match the base_branch you used in PrepareBlogBranch.",
    )

    def run(self):
        repo = self.repo_path
        base_branch = self.base_branch or os.getenv("DEPLOY_BASE_BRANCH", "main")
        log = []

        code, out, err = _run(["git", "status", "--porcelain"], repo)
        if code == 0 and not out.strip():
            return "Error: no changes to commit. Did InsertBlogPost run successfully?"

        for args in (
            ["git", "add", "-A"],
            ["git", "commit", "-m", self.commit_message],
            ["git", "push", "-u", "origin", self.branch_name, "--force-with-lease"],
        ):
            code, out, err = _run(args, repo)
            log.append(f"$ {' '.join(args[:3])} ...\n{(out or err).strip()[:500]}")
            if code != 0:
                return "Error during git commit/push:\n\n" + "\n\n".join(log)

        # Resolve remote → token/owner/repo for the API call.
        code, remote_url, err = _run(["git", "remote", "get-url", "origin"], repo)
        if code != 0:
            return "Pushed branch, but could not read origin URL to open a PR:\n" + err
        token, owner, name = _parse_remote(remote_url)
        token = token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        if not (token and owner and name):
            return (
                "Branch pushed successfully, but no GitHub token was available to open the PR "
                f"automatically. Open it manually:\n"
                f"  base: {base_branch}  <-  compare: {self.branch_name}"
            )

        payload = json.dumps(
            {
                "title": self.pr_title,
                "head": self.branch_name,
                "base": base_branch,
                "body": self.pr_body,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.github.com/repos/{owner}/{name}/pulls",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "seo-swarm-blog-deploy",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return (
                f"Success. Branch pushed and PR opened:\n{data.get('html_url')}\n\n"
                + "\n\n".join(log)
            )
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            if e.code == 422 and "already exists" in body:
                return (
                    f"Branch pushed. A PR for '{self.branch_name}' already exists; "
                    "the new commit was added to it."
                )
            return (
                f"Branch pushed, but opening the PR failed (HTTP {e.code}): {body[:300]}\n"
                f"Open it manually: base {base_branch} <- {self.branch_name}"
            )
        except Exception as e:
            return f"Branch pushed, but opening the PR failed: {e}"


if __name__ == "__main__":
    print(_parse_remote("https://user:ghp_xxx@github.com/Legresca/v-try-on"))
