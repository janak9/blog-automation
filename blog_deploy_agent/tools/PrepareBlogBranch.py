import os
import subprocess

from agency_swarm.tools import BaseTool
from pydantic import Field

DEFAULT_REPO = "/Users/janakvaghela/projects/legresca/v-try-on"


def _run(args, cwd):
    proc = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, timeout=180
    )
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


class PrepareBlogBranch(BaseTool):
    """
    Prepares the v-try-on repository for a new blog deployment.

    This tool:
    1. Verifies the path is a clean git repository (fails if there are uncommitted changes).
    2. Checks out `main` and pulls the latest changes from origin.
    3. Creates and checks out a fresh feature branch for the new blog post.

    Run this FIRST, before inserting any blog content. It leaves you on the new
    branch, ready for InsertBlogPost.
    """

    branch_name: str = Field(
        ...,
        description="Feature branch to create, e.g. 'blog/ai-virtual-try-on-guide'. Use the blog slug prefixed with 'blog/'.",
    )
    repo_path: str = Field(
        default=DEFAULT_REPO,
        description="Absolute path to the v-try-on repository. Defaults to the standard location.",
    )
    base_branch: str = Field(
        default="",
        description="Branch to base the new branch on. Defaults to the DEPLOY_BASE_BRANCH env var, "
        "or 'main' if unset. Set to 'dev' to base off (and later target) dev.",
    )

    def run(self):
        repo = self.repo_path
        base_branch = self.base_branch or os.getenv("DEPLOY_BASE_BRANCH", "main")
        if not os.path.isdir(os.path.join(repo, ".git")):
            return f"Error: {repo} is not a git repository."

        # Refuse to run on a dirty tree so we never mix unrelated changes into the PR.
        code, out, err = _run(["git", "status", "--porcelain"], repo)
        if code != 0:
            return f"Error checking git status: {err or out}"
        if out.strip():
            return (
                "Error: repository has uncommitted changes. Resolve them before deploying:\n"
                f"{out}"
            )

        steps = []
        for args in (
            ["git", "checkout", base_branch],
            ["git", "pull", "origin", base_branch, "--ff-only"],
        ):
            code, out, err = _run(args, repo)
            steps.append(f"$ {' '.join(args)}\n{(out or err).strip()}")
            if code != 0:
                return "Error during pull:\n\n" + "\n\n".join(steps)

        # Create the branch (delete a stale local one with the same name first).
        _run(["git", "branch", "-D", self.branch_name], repo)
        code, out, err = _run(["git", "checkout", "-b", self.branch_name], repo)
        steps.append(f"$ git checkout -b {self.branch_name}\n{(out or err).strip()}")
        if code != 0:
            return "Error creating branch:\n\n" + "\n\n".join(steps)

        return (
            f"Repository ready. On fresh branch '{self.branch_name}' based on latest "
            f"origin/{base_branch}.\n\n" + "\n\n".join(steps)
        )


if __name__ == "__main__":
    print(PrepareBlogBranch(branch_name="blog/test-branch").run())
