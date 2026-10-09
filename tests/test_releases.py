import os
from pathlib import Path

import httpx
import pytest
import respx

from craft_dl.models import AssetInfo, ReleaseInfo
from craft_dl.releases import download_asset, ensure_releases_dir, link_latest, release_dir, write_readme


def test_ensure_releases_dir(tmp_path: Path) -> None:
    root = ensure_releases_dir(tmp_path / "nested" / "repo")
    assert (root / ".gitignore").read_text() == "*\n"
    ensure_releases_dir(tmp_path / "nested" / "repo")  # no failure if it exists
# end def


def test_release_dir_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        release_dir(tmp_path, "../evil")
    # end with
# end def


def test_readme(tmp_path: Path) -> None:
    write_readme(tmp_path / "v1", ReleaseInfo(tag="v1", name="PhotoCraft v1", body="notes"))
    assert (tmp_path / "v1" / "README.md").read_text() == "# PhotoCraft v1\n\nnotes\n"
# end def


@respx.mock
async def test_download_skip_and_cleanup(tmp_path: Path) -> None:
    asset = AssetInfo(name="a.zip", size=3, url="https://example.test/a")
    respx.get(asset.url).mock(return_value=httpx.Response(200, content=b"abc"))
    async with httpx.AsyncClient() as http:
        assert await download_asset(http, asset, tmp_path) is True
        assert (tmp_path / "a.zip").read_bytes() == b"abc"
        assert await download_asset(http, asset, tmp_path) is False  # same size, skipped

        bad = AssetInfo(name="b.zip", size=3, url="https://example.test/b")
        respx.get(bad.url).mock(return_value=httpx.Response(500))
        with pytest.raises(httpx.HTTPStatusError):
            await download_asset(http, bad, tmp_path)
        # end with
    # end with
    assert not (tmp_path / "b.zip").exists()
    assert not (tmp_path / "b.zip.part").exists()
# end def


def test_link_latest_creates_and_moves_a_relative_symlink(tmp_path: Path) -> None:
    root = ensure_releases_dir(tmp_path)
    (root / "v1").mkdir()
    (root / "v2").mkdir()
    assert link_latest(root, "v1")
    assert os.readlink(root / "latest") == "v1"
    assert link_latest(root, "v1")
    assert link_latest(root, "v2")
    assert os.readlink(root / "latest") == "v2"
    assert (root / "latest").resolve() == (root / "v2").resolve()
    assert not (root / ".latest.tmp").exists()


def test_link_latest_skips_missing_folder_and_real_directory(tmp_path: Path) -> None:
    root = ensure_releases_dir(tmp_path)
    assert not link_latest(root, "v9")
    assert not (root / "latest").exists() and not (root / "latest").is_symlink()
    (root / "v1").mkdir()
    (root / "latest").mkdir()
    assert not link_latest(root, "v1")
    assert not (root / "latest").is_symlink()
