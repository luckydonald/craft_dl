import asyncio
import logging
from pathlib import Path

import pytest

from craft_dl import git_ops
from craft_dl.progress import Bars


def test_parse_progress_lines() -> None:
    receiving = git_ops.parse_progress("Receiving objects:  45% (390/866), 1.20 MiB | 3.92 MiB/s")
    assert receiving == git_ops.GitProgress("Receiving objects", 45, 390, 866, "3.92 MiB/s")
    assert receiving is not None and receiving.fraction == pytest.approx(0.37)
    assert receiving.detail == "Receiving objects 390/866 · 3.92 MiB/s"
    done = git_ops.parse_progress("Receiving objects: 100% (866/866), 4.45 MiB | 3.92 MiB/s, done.")
    assert done is not None and done.fraction == pytest.approx(0.7)
    counting = git_ops.parse_progress("remote: Counting objects: 100% (71/71), done.")
    assert counting is not None and counting.fraction == pytest.approx(0.05) and counting.rate is None
    files = git_ops.parse_progress("Updating files:  45% (9/20)")
    assert files is not None and files.detail == "Updating files 9/20" and files.fraction == pytest.approx(0.945)
    enumerating = git_ops.parse_progress("remote: Enumerating objects: 866, done.")
    assert enumerating == git_ops.GitProgress("Enumerating objects", None, 866, None, None)
    assert enumerating.detail == "Enumerating objects 866" and enumerating.fraction == 0.0
    assert git_ops.parse_progress("From https://github.com/storytold/x") is None
    assert git_ops.parse_progress("Resolving deltas: 100% (2/2), done.").fraction == pytest.approx(0.9)  # type: ignore[union-attr]


async def test_read_stderr_feeds_bar_and_logs_only_finished_lines(caplog: pytest.LogCaptureFixture) -> None:
    stream = asyncio.StreamReader()
    stream.feed_data(b"From github\nReceiving objects:  10% (1/10)\rReceiving objects:  60% (6/10)\rReceiving objects: 100% (10/10), done.\n")
    stream.feed_eof()
    seen: list[tuple[float, str]] = []
    with caplog.at_level(logging.INFO, logger="craft_dl.git_ops"):
        text = await git_ops.read_stderr(stream, "git fetch", lambda fraction, detail: seen.append((fraction, detail)))
    # end with
    fractions = [fraction for fraction, _ in seen]
    assert fractions == sorted(fractions) and fractions[-1] == pytest.approx(0.7)
    assert seen[-1][1] == "Receiving objects 10/10"
    assert [r.getMessage() for r in caplog.records] == ["git fetch: From github", "git fetch: Receiving objects: 100% (10/10), done."]
    assert "Receiving objects:  10%" in text


async def test_commands_are_logged(remote: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="craft_dl.git_ops"):
        await git_ops.clone(str(remote), tmp_path / "c", lambda fraction, detail: None)
    # end with
    assert any(r.getMessage().startswith("$ git clone --progress") for r in caplog.records)


def test_step_progress_is_partial_then_whole() -> None:
    bars = Bars(enabled=False)
    bars.start_repo("x", 2)
    bars.step_progress(0.5, "Receiving objects 5/10")
    assert bars.progress.tasks[bars.current].completed == 0.5
    assert bars.progress.tasks[bars.current].fields["detail"] == "Receiving objects 5/10"
    bars.work_done()
    assert bars.progress.tasks[bars.current].fields["detail"] == ""
    bars.step_progress(0.25)
    assert bars.progress.tasks[bars.current].completed == 1.25
    bars.step_progress(5)
    assert bars.progress.tasks[bars.current].completed < 2
