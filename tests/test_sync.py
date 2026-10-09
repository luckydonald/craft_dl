from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import respx

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
    from craft_dl import git_ops

    await git_ops.clone(str(remote), tmp_path / "fakecraft")
    errors = ErrorCollector()
    ctx = Context(repo_dir=tmp_path, dl={Dl.repo, Dl.release}, errors=errors, bars=Bars(enabled=False))
    await run(["*"], ctx, failing_names)
    assert [f.step for f in errors.failures] == ["list repositories"]
    assert Dl.release not in ctx.dl
    assert (tmp_path / "fakecraft" / ".git").exists()
# end def
