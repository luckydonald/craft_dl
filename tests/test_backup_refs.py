from datetime import UTC, datetime
from pathlib import Path

from craft_dl import git_ops
from craft_dl.backup_refs import BackupResult, backup_refs, named_ref, write_batch
from tests.conftest import git

NOW = datetime(2026, 10, 9, 12, 30, 5, tzinfo=UTC)


def test_named_ref() -> None:
    assert named_ref("branch", "feat/x", NOW, "abc") == "bak/branch/feat/x/2026-10-09/12-30-05/abc"
# end def


async def test_backup_is_idempotent_and_survives_force_push(remote: Path, tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    await git_ops.clone(str(remote), checkout)
    old_tip = git("rev-parse", "main", cwd=remote)

    first = await backup_refs(checkout, NOW)
    assert first.errors == []
    assert first.created == 4  # named refs for main, feat/x and v1, plus one shared bak/commit
    refs = git("for-each-ref", "--format=%(refname:short)", "refs/heads/bak", cwd=checkout).splitlines()
    assert f"bak/commit/{old_tip}" in refs
    assert f"bak/branch/feat/x/2026-10-09/12-30-05/{old_tip}" in refs
    assert f"bak/tag/v1/2026-10-09/12-30-05/{old_tip}" in refs

    again = await backup_refs(checkout, NOW)
    assert again.created == 0

    # force push: rewrite main upstream
    git("commit", "--amend", "--allow-empty", "-m", "rewritten", cwd=remote)
    new_tip = git("rev-parse", "main", cwd=remote)
    assert new_tip != old_tip
    await git_ops.fetch_all(checkout)
    await backup_refs(checkout, NOW)
    assert git("rev-parse", f"bak/commit/{old_tip}", cwd=checkout) == old_tip
    assert git("rev-parse", f"bak/commit/{new_tip}", cwd=checkout) == new_tip
# end def


async def test_batch_failure_falls_back_to_single_refs(tmp_path: Path, remote: Path) -> None:
    checkout = tmp_path / "checkout"
    await git_ops.clone(str(remote), checkout)
    head = (await git_ops.run_git("rev-parse", "HEAD", cwd=checkout)).strip()
    result = BackupResult()
    # the second ref is invalid, which fails the whole transaction
    await write_batch(checkout, [("refs/heads/bak/ok/1", head), ("refs/heads/bak/bad..name", head)], result)
    assert result.created == 1
    assert len(result.errors) == 1
    assert (await git_ops.run_git("rev-parse", "refs/heads/bak/ok/1", cwd=checkout)).strip() == head
