from pathlib import Path

import httpx
import pytest
import respx

from craft_dl.models import AssetInfo
from craft_dl.progress import Bars, DetailColumn, human_bytes
from craft_dl.releases import download_asset


def test_human_bytes() -> None:
    assert human_bytes(512) == "512 B"
    assert human_bytes(1536) == "1.50 KiB"
    assert human_bytes(5 * 1024 * 1024) == "5.00 MiB"


def test_file_rows_come_and_go_and_track_bytes() -> None:
    bars = Bars(enabled=False)
    before = len(bars.progress.tasks)
    handle = bars.file("some-long-asset-name-that-needs-shortening-1.0.0.msi", 1000)
    assert len(bars.progress.tasks) == before + 1
    row = bars.progress.tasks[-1]
    assert row.description.startswith("  …") and row.fields["bytes"] and row.total == 1000
    handle.advance(400)
    assert bars.progress.tasks[-1].completed == 400
    assert bars.active_files == 1
    handle.close()
    assert len(bars.progress.tasks) == before
    assert bars.active_files == 0


def test_speed_is_a_sliding_window_over_all_files() -> None:
    bars = Bars(enabled=False)
    bars.start_repo("x", 3)
    bars.record_bytes(1000, now=100.0)
    bars.record_bytes(3000, now=102.0)
    assert bars.speed(now=102.0) == pytest.approx(2000.0)
    assert bars.speed(now=120.0) == 0.0, "old samples drop out of the window"
    bars.record_bytes(2048, now=200.0)
    assert "KiB/s" in bars.progress.tasks[bars.current].fields["detail"]


def test_detail_column_renders_git_text_and_file_bytes() -> None:
    bars = Bars(enabled=False)
    bars.start_repo("repo", 2)
    bars.step_progress(0.5, "Receiving objects 5/10 · 3.92 MiB/s")
    column = DetailColumn()
    assert column.render(bars.progress.tasks[bars.current]).plain == "Receiving objects 5/10 · 3.92 MiB/s"
    handle = bars.file("a.bin", 2048)
    handle.advance(1024)
    assert column.render(bars.progress.tasks[-1]).plain.startswith("1.00 KiB/2.00 KiB")


@respx.mock
async def test_download_asset_reports_chunks_and_closes_on_failure(tmp_path: Path) -> None:
    respx.get("https://example.test/ok").mock(return_value=httpx.Response(200, content=b"abcdef"))
    respx.get("https://example.test/bad").mock(return_value=httpx.Response(500))
    bars = Bars(enabled=False)
    async with httpx.AsyncClient() as http:
        assert await download_asset(http, AssetInfo("ok.bin", 6, "https://example.test/ok"), tmp_path, bars.file)
        assert sum(count for _, count in bars.samples) == 6
        assert bars.active_files == 0
        with pytest.raises(httpx.HTTPStatusError):
            await download_asset(http, AssetInfo("bad.bin", 6, "https://example.test/bad"), tmp_path, bars.file)
        # end with
    # end with
    assert bars.active_files == 0
