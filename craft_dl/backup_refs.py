import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from craft_dl.git_ops import GitError, run_git, update_ref

BACKUP_PREFIX = "refs/heads/bak/"
NAMED_PATTERN = re.compile(r"^bak/(branch|tag)/(.+)/\d{4}-\d{2}-\d{2}/\d{2}-\d{2}-\d{2}/([0-9a-f]{40,64})$")
COMMIT_PATTERN = re.compile(r"^bak/commit/([0-9a-f]{40,64})$")


@dataclass
class BackupResult:
    created: int = 0
    errors: list[str] = field(default_factory=list)
# end class


def named_ref(kind: str, name: str, now: datetime, sha: str) -> str:
    """`bak/{branch,tag}/{name/with/slashes}/{YYYY-MM-DD}/{HH-MM-SS}/{commit}`"""
    return f"bak/{kind}/{name}/{now:%Y-%m-%d}/{now:%H-%M-%S}/{sha}"
# end def


def commit_ref(sha: str) -> str:
    return f"bak/commit/{sha}"
# end def


async def current_refs(path: Path) -> list[tuple[str, str, str]]:
    """`(kind, name, commit sha)` for every remote branch and tag; annotated tags are peeled."""
    fmt = "%(refname)%00%(objectname)%00%(objecttype)%00%(*objectname)%00%(*objecttype)"
    output = await run_git("for-each-ref", f"--format={fmt}", "refs/remotes", "refs/tags", cwd=path)
    refs: list[tuple[str, str, str]] = []
    for line in output.splitlines():
        refname, sha, object_type, peeled_sha, peeled_type = line.split("\0")
        if peeled_sha:
            sha, object_type = peeled_sha, peeled_type
        # end if
        if object_type != "commit":
            continue
        # end if
        if refname.startswith("refs/tags/"):
            refs.append(("tag", refname.removeprefix("refs/tags/"), sha))
        else:
            # refs/remotes/<remote>/<branch>
            name = refname.removeprefix("refs/remotes/").partition("/")[2]
            if name and name != "HEAD":
                refs.append(("branch", name, sha))
            # end if
        # end if
    # end for
    return refs
# end def


async def existing_backups(path: Path) -> tuple[set[tuple[str, str, str]], set[str]]:
    output = await run_git("for-each-ref", "--format=%(refname:short)", BACKUP_PREFIX, cwd=path)
    named: set[tuple[str, str, str]] = set()
    commits: set[str] = set()
    for line in output.splitlines():
        if match := NAMED_PATTERN.match(line):
            named.add((match.group(1), match.group(2), match.group(3)))
        elif match := COMMIT_PATTERN.match(line):
            commits.add(match.group(1))
        # end if
    # end for
    return named, commits
# end def


async def backup_refs(path: Path, now: datetime) -> BackupResult:
    """Create `bak/*` branches for every new or changed branch/tag tip, so force pushes stay recoverable.

    A tip counts as new if there's no backup for that exact `(kind, name, commit)` yet, which makes reruns idempotent.
    """
    result = BackupResult()
    named, commits = await existing_backups(path)
    for kind, name, sha in await current_refs(path):
        if (kind, name, sha) not in named:
            try:
                await update_ref(path, "refs/heads/" + named_ref(kind, name, now, sha), sha)
                result.created += 1
                named.add((kind, name, sha))
            except GitError as error:
                result.errors.append(f"{kind} {name}: {error}")
            # end try
        # end if
        if sha not in commits:
            try:
                await update_ref(path, "refs/heads/" + commit_ref(sha), sha)
                result.created += 1
                commits.add(sha)
            except GitError as error:
                result.errors.append(f"commit {sha}: {error}")
            # end try
        # end if
    # end for
    return result
# end def
