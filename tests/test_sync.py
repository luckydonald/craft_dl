from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import respx

from craft_dl import git_ops
from craft_dl.chain import parse_chain
from craft_dl.filtering import CliMode
from craft_dl.models import AssetInfo, Dl, ReleaseInfo
from craft_dl.progress import Bars
from craft_dl.report import ErrorCollector
from craft_dl.sync import Context, run


class FakeSource:
    def __init__(self, fail_listing: bool = False) -> None:
        self.fail_listing = fail_listing
        self.release = ReleaseInfo(tag="v1", name="Fake v1", body="n", assets=[AssetInfo("a.bin", 3, "https://example.test/a")])
    # end def

    async def list_releases(self, repo: str) -> AsyncIterator[ReleaseInfo]:
        if self.fail_listing:
            raise RuntimeError("rate limited")
        # end if
        yield self.release
    # end def

    async def latest_release(self, repo: str) -> ReleaseInfo:
        return self.release
    # end def
# end class


async def names() -> list[str]:
    return ["fakecraft"]
# end def


async def failing_names() -> list[str]:
    raise RuntimeError("no network")
# end def


@respx.mock
async def test_releases_without_checkout(tmp_path: Path) -> None:
    respx.get("https://example.test/a").mock(return_value=httpx.Response(200, content=b"abc"))
    errors = ErrorCollector()
    async with httpx.AsyncClient() as http:
        ctx = Context(repo_dir=tmp_path, dl={Dl.release}, errors=errors, bars=Bars(enabled=False), source=FakeSource(), http=http)
        await run(["*"], ctx, names)
    # end with
    assert errors.failures == []
    assert (tmp_path / "fakecraft" / "_releases_" / "v1" / "a.bin").read_bytes() == b"abc"
    assert not (tmp_path / "fakecraft" / ".git").exists()
# end def


@respx.mock
async def test_listing_failure_falls_back_to_latest(tmp_path: Path) -> None:
    respx.get("https://example.test/a").mock(return_value=httpx.Response(200, content=b"abc"))
    errors = ErrorCollector()
    async with httpx.AsyncClient() as http:
        ctx = Context(repo_dir=tmp_path, dl={Dl.release}, errors=errors, bars=Bars(enabled=False), source=FakeSource(True), http=http)
        await run(["*"], ctx, names)
    # end with
    assert [f.step for f in errors.failures] == ["list releases"]
    assert (tmp_path / "fakecraft" / "_releases_" / "v1" / "a.bin").exists()
# end def


async def test_offline_still_fetches_existing_checkouts(remote: Path, tmp_path: Path) -> None:
    await git_ops.clone(str(remote), tmp_path / "fakecraft")
    errors = ErrorCollector()
    ctx = Context(repo_dir=tmp_path, dl={Dl.repo, Dl.release}, errors=errors, bars=Bars(enabled=False))
    await run(["*"], ctx, failing_names)
    assert [f.step for f in errors.failures] == ["list repositories"]
    assert Dl.release not in ctx.dl
    assert (tmp_path / "fakecraft" / ".git").exists()
# end def


class MultiSource:
    def __init__(self) -> None:
        names = ["a-1.0-windows-x64.msi", "a-1.0-linux-x86_64.deb", "a-1.0-macos-universal.dmg", "SHA256SUMS.txt"]
        self.releases = [
            ReleaseInfo(tag=tag, name=tag, body="notes", assets=[AssetInfo(n, 1, f"https://example.test/{tag}/{n}") for n in names])
            for tag in ("v1.0.0", "v2.0.0")
        ]
    # end def

    async def list_releases(self, repo: str) -> AsyncIterator[ReleaseInfo]:
        for release in self.releases:
            yield release
        # end for
    # end def

    async def latest_release(self, repo: str) -> ReleaseInfo:
        return self.releases[-1]
    # end def
# end class


@respx.mock
async def test_only_matching_assets_are_downloaded(tmp_path: Path) -> None:
    route = respx.get(url__startswith="https://example.test/").mock(return_value=httpx.Response(200, content=b"x"))
    errors = ErrorCollector()
    chain = parse_chain("--app=fake --release=latest,v9.9.9 --platform=win".split())
    async with httpx.AsyncClient() as http:
        ctx = Context(repo_dir=tmp_path, dl={Dl.release}, errors=errors, bars=Bars(enabled=False), source=MultiSource(), http=http)
        await run(["fake"], ctx, names, chain)
    # end with
    release_dir = tmp_path / "fakecraft" / "_releases_"
    assert sorted(p.name for p in release_dir.iterdir() if p.is_dir()) == ["v2.0.0"]
    assert sorted(p.name for p in (release_dir / "v2.0.0").iterdir()) == ["README.md", "SHA256SUMS.txt", "a-1.0-windows-x64.msi"]
    assert route.call_count == 2
    assert [(f.step, f.detail) for f in errors.failures] == [("select release", "release 'v9.9.9' not found")]
# end def


@respx.mock
async def test_dl_cli_app_skips_cli_assets(tmp_path: Path) -> None:
    respx.get(url__startswith="https://example.test/").mock(return_value=httpx.Response(200, content=b"x"))
    source = MultiSource()
    source.releases = [ReleaseInfo("v1", "v1", "n", [AssetInfo("a-cli-1-macos.zip", 1, "https://example.test/c"), AssetInfo("a-1-macos.dmg", 1, "https://example.test/d")])]
    async with httpx.AsyncClient() as http:
        ctx = Context(repo_dir=tmp_path, dl={Dl.release}, errors=ErrorCollector(), bars=Bars(enabled=False), source=source, http=http, cli_mode=CliMode.app)
        await run(["*"], ctx, names)
    # end with
    assert sorted(p.name for p in (tmp_path / "fakecraft" / "_releases_" / "v1").iterdir()) == ["README.md", "a-1-macos.dmg"]
# end def
