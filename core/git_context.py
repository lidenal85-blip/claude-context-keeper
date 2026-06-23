"""Git-интеграция с snapshots в отдельную ref."""

import subprocess
from datetime import datetime
from pathlib import Path


class GitContext:
    def __init__(self, project_path: Path):
        self.path = Path(project_path)

    def is_git_repo(self):
        try:
            subprocess.run(["git", "rev-parse", "--git-dir"],
                         cwd=self.path, capture_output=True, check=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def _run(self, *args, **kwargs):
        result = subprocess.run(list(args), cwd=self.path,
                               capture_output=True, text=True, **kwargs)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, list(args), result.stdout, result.stderr
            )
        return result.stdout.strip()

    def get_current_commit(self):
        try:
            return self._run("git", "rev-parse", "HEAD")
        except subprocess.CalledProcessError:
            return "no-git"

    def get_diff_stat(self):
        try:
            return self._run("git", "diff", "--stat", "HEAD")
        except subprocess.CalledProcessError:
            return ""

    def get_uncommitted_files(self):
        try:
            output = self._run("git", "status", "--porcelain")
            if not output:
                return []
            return [line[3:] for line in output.split('\n') if line]
        except subprocess.CalledProcessError:
            return []

    def create_snapshot(self, message):
        if not self.is_git_repo():
            return "no-git"
        try:
            self._run("git", "add", "-A")
            tree = self._run("git", "write-tree")
            parent = self._run("git", "rev-parse", "HEAD")
            commit_hash = self._run(
                "git", "commit-tree", tree, "-p", parent,
                "-m", f"[claude-snapshot] {message}"
            )
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._run("git", "update-ref", f"refs/claude-snapshots/{ts}",
                     commit_hash)
            self._run("git", "reset", "--soft", parent)
            return commit_hash
        except subprocess.CalledProcessError:
            return "error"

    def list_snapshots(self, limit=10):
        try:
            output = self._run(
                "git", "for-each-ref", "--sort=-creatordate",
                f"--count={limit}", "--format=%(refname:short) %(subject)",
                "refs/claude-snapshots/"
            )
            return output.split('\n') if output else []
        except subprocess.CalledProcessError:
            return []
