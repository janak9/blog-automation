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
    """Extract (user, owner, repo) from an https github remote URL.

    Supports 'https://[user@]github.com/owner/repo(.git)'. Any secret embedded in the URL is
    ignored: tokens must never be stored in git remotes (see _github_token).
    """
    m = re.match(
        r"https://(?:([^@/]+)@)?github\.com/([^/]+)/([^/.]+)(?:\.git)?/?$", remote_url.strip()
    )
    if not m:
        return None, None, None
    creds, owner, repo = m.group(1), m.group(2), m.group(3)
    user = creds.split(":", 1)[0] if creds else None
    return user, owner, repo


def _github_token(user):
    """Token for the GitHub API: GITHUB_TOKEN / GH_TOKEN, else the gh CLI's keychain login.

    When the remote names a user ('https://legresca-admin@github.com/...'), ask gh for that
    account's token so the PR is never opened under the wrong identity.
    """
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        return token
    args = ["gh", "auth", "token", "--hostname", "github.com"] + (["--user", user] if user else [])
    try:
        code, out, _ = _run(args, None)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out if code == 0 and out else None


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

        # Resolve remote → user/owner/repo, then the token for the API call.
        code, remote_url, err = _run(["git", "remote", "get-url", "origin"], repo)
        if code != 0:
            return "Pushed branch, but could not read origin URL to open a PR:\n" + err
        user, owner, name = _parse_remote(remote_url)
        token = _github_token(user)
        if not (token and owner and name):
            return (
                "Branch pushed successfully, but no GitHub token was available to open the PR "
                f"automatically (run `gh auth login`{f' as {user}' if user else ''}). Open it manually:\n"
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
    print(_parse_remote("https://legresca-admin@github.com/Legresca/v-try-on"))
