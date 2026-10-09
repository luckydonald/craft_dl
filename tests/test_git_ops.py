import asyncio
import logging
from pathlib import Path

import pytest

from craft_dl import git_ops, git_progress
from craft_dl.progress import Bars


def test_parse_progress_lines() -> None:
    receiving = git_progress.parse_progress("Receiving objects:  45% (390/866), 1.20 MiB | 3.92 MiB/s")
    assert receiving == git_progress.GitProgress("Receiving objects", 45, 390, 866, "3.92 MiB/s", False, 3, 5)
    assert receiving is not None and receiving.fraction == pytest.approx((3 + 0.45) / 5)
    assert receiving.detail == "390/866 · 3.92 MiB/s"
    done = git_progress.parse_progress("Receiving objects: 100% (866/866), 4.45 MiB | 3.92 MiB/s, done.")
    assert done is not None and done.finished and done.fraction == pytest.approx(4 / 5)
    counting = git_progress.parse_progress("remote: Counting objects: 100% (71/71), done.")
    assert counting is not None and counting.index == 1 and counting.rate is None and counting.fraction == pytest.approx(2 / 5)
    enumerating = git_progress.parse_progress("remote: Enumerating objects: 866, done.")
    assert enumerating == git_progress.GitProgress("Enumerating objects", None, 866, None, None, True, 0, 5)
    assert enumerating.fraction == pytest.approx(1 / 5)
    running = git_progress.parse_progress("remote: Enumerating objects: 400")
    assert running is not None and not running.finished and running.phase_fraction == 0.0 and running.detail == "400"
    assert git_progress.parse_progress("From https://github.com/storytold/x") is None
    assert git_progress.parse_progress("Resolving deltas: 100% (2/2), done.").fraction == 1.0  # type: ignore[union-attr]


def test_phases_depend_on_the_command() -> None:
    files = "Updating files:  45% (9/20)"
    assert git_progress.parse_progress(files) is None, "a fetch never updates files"
    clone = git_progress.parse_progress(files, git_progress.CLONE_PHASES)
    assert clone is not None and (clone.index, clone.count) == (5, 6)
    checkout = git_progress.parse_progress("Checking out files:  50% (1/2)", git_progress.CHECKOUT_PHASES)
    assert checkout is not None and checkout.phase == "Updating files" and checkout.fraction == pytest.approx(0.5)


async def test_read_stderr_feeds_bar_and_logs_only_finished_lines(caplog: pytest.LogCaptureFixture) -> None:
    stream = asyncio.StreamReader()
    stream.feed_data(
        b"From github\nremote: Enumerating objects: 9, done.\nReceiving objects:  10% (1/10)\rReceiving objects:  60% (6/10)\r"
        b"Receiving objects: 100% (10/10), done.\nReceiving objects:  50% (5/10)\n",
    )
    stream.feed_eof()
    seen: list[git_progress.GitProgress] = []
    with caplog.at_level(logging.INFO, logger="craft_dl.git_ops"):
        text = await git_ops.read_stderr(stream, "git fetch", seen.append)
    # end with
    indexes = [progress.index for progress in seen]
    assert indexes == sorted(indexes)
    assert [(p.phase, p.done) for p in seen] == [
        ("Enumerating objects", 9), ("Receiving objects", 1), ("Receiving objects", 6), ("Receiving objects", 10), ("Receiving objects", 5),
    ]
    assert [r.getMessage() for r in caplog.records][:2] == ["git fetch: From github", "git fetch: remote: Enumerating objects: 9, done."]
    assert "Receiving objects:  10%" in text


async def test_commands_are_logged(remote: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="craft_dl.git_ops"):
        await git_ops.clone(str(remote), tmp_path / "c", lambda progress: None)
    # end with
    assert any(r.getMessage().startswith("$ git clone --progress") for r in caplog.records)


def test_step_progress_is_partial_then_whole() -> None:
    bars = Bars(enabled=False)
    bars.start_repo("x", 2)
    bars.step_progress(0.5, "Creating backup refs 5/10")
    assert bars.progress.tasks[bars.current].completed == 0.5
    assert bars.progress.tasks[bars.current].fields["detail"] == "Creating backup refs 5/10"
    bars.work_done()
    assert bars.progress.tasks[bars.current].fields["detail"] == ""
    bars.step_progress(0.25)
    assert bars.progress.tasks[bars.current].completed == 1.25
    bars.step_progress(5)
    assert bars.progress.tasks[bars.current].completed < 2


def test_git_rows_show_steps_and_current_phase() -> None:
    bars = Bars(enabled=False)
    bars.start_repo("x", 2)
    rows = len(bars.progress.tasks)
    bars.git_progress(git_progress.parse_progress("remote: Enumerating objects: 400") or pytest.fail())
    steps, phase = bars.progress.tasks[rows], bars.progress.tasks[rows + 1]
    assert steps.description == "  git step 1/5" and steps.completed == 0
    assert phase.description.strip() == "Enumerating objects" and phase.completed == 0 and phase.fields["detail"] == "400"
    bars.git_progress(git_progress.parse_progress("remote: Enumerating objects: 400, done.") or pytest.fail())
    assert bars.progress.tasks[rows + 1].completed == bars.progress.tasks[rows + 1].total == 400
    assert bars.progress.tasks[rows].completed == 1
    bars.git_progress(git_progress.parse_progress("Receiving objects:  50% (5/10), 1 MiB | 2 MiB/s") or pytest.fail())
    assert bars.progress.tasks[rows].completed == 3.5
    assert (bars.progress.tasks[rows + 1].completed, bars.progress.tasks[rows + 1].total) == (5, 10)
    bars.work_done()
    assert len(bars.progress.tasks) == rows and bars.git_tasks is None
