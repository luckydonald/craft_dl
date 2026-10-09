import subprocess
from pathlib import Path

import pytest


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()
# end def


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A local 'upstream' repo with `main` and a branch with a slash in its name."""
    path = tmp_path / "upstream"
    path.mkdir()
    git("init", "-b", "main", cwd=path)
    (path / "a.txt").write_text("1")
    git("add", "a.txt", cwd=path)
    git("commit", "-m", "one", cwd=path)
    git("branch", "feat/x", cwd=path)
    git("tag", "-a", "v1", "-m", "v1", cwd=path)
    return path
# end def
