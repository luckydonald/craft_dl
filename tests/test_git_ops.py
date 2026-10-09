import asyncio
import logging
from pathlib import Path

import pytest

from craft_dl import git_ops
from craft_dl.progress import Bars


def test_fraction_of_git_progress_lines() -> None:
    assert git_ops.fraction_of("Receiving objects:  50% (5/10)") == pytest.approx(0.45)
    assert git_ops.fraction_of("remote: Counting objects: 100% (3/3), done.") == pytest.approx(0.05)
    assert git_ops.fraction_of("Resolving deltas: 100% (2/2), done.") == 1.0
    assert git_ops.fraction_of("From https://github.com/storytold/x") is None


async def test_read_stderr_feeds_bar_and_logs_only_finished_lines(caplog: pytest.LogCaptureFixture) -> None:
    stream = asyncio.StreamReader()
    stream.feed_data(b"From github\nReceiving objects:  10% (1/10)\rReceiving objects:  60% (6/10)\rReceiving objects: 100% (10/10), done.\n")
    stream.feed_eof()
    seen: list[float] = []
    with caplog.at_level(logging.INFO, logger="craft_dl.git_ops"):
        text = await git_ops.read_stderr(stream, "git fetch", seen.append)
    # end with
    assert seen == sorted(seen) and seen[-1] == pytest.approx(0.8)
    assert [r.getMessage() for r in caplog.records] == ["git fetch: From github", "git fetch: Receiving objects: 100% (10/10), done."]
    assert "Receiving objects:  10%" in text


async def test_commands_are_logged(remote: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="craft_dl.git_ops"):
        await git_ops.clone(str(remote), tmp_path / "c", lambda fraction: None)
    # end with
    assert any(r.getMessage().startswith("$ git clone --progress") for r in caplog.records)


def test_step_progress_is_partial_then_whole() -> None:
    bars = Bars(enabled=False)
    bars.start_repo("x", 2)
    bars.step_progress(0.5)
    assert bars.progress.tasks[bars.current].completed == 0.5
    bars.work_done()
    bars.step_progress(0.25)
    assert bars.progress.tasks[bars.current].completed == 1.25
    bars.step_progress(5)
    assert bars.progress.tasks[bars.current].completed < 2
