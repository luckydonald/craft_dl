from pathlib import Path

import httpx
import pytest
import respx

from craft_dl.models import AssetInfo
from craft_dl.releases import download_asset
from craft_dl.webdav import WebdavError, WebdavStore, has_protocol, parse

BASE = "https://dav.example.com/some/path"


def multistatus(length: int | None) -> httpx.Response:
    prop = "" if length is None else f"<d:getcontentlength>{length}</d:getcontentlength>"
    body = f'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:"><d:response><d:propstat><d:prop>{prop}</d:prop></d:propstat></d:response></d:multistatus>'
    return httpx.Response(207, content=body)


def test_has_protocol() -> None:
    assert has_protocol(Path("webdavs://host/x"))
    assert has_protocol("WEBDAV://host/x")
    assert has_protocol("webdavs:/host/x")
    assert not has_protocol("smb://host/x")
    assert not has_protocol("/webdavs://x")


def test_parse_unescapes_credentials_and_hides_them_in_the_url() -> None:
    location = parse(Path("webdavs://us%40er:escaped%20pass%3Aword%2F@dav.example.com:8443/some/path/"))
    assert (location.user, location.password) == ("us@er", "escaped pass:word/")
    assert location.base_url == "https://dav.example.com:8443/some/path"
    assert parse("webdav://dav.example.com").base_url == "http://dav.example.com"
    assert parse("webdavs://dav.example.com/x").user is None


@pytest.mark.parametrize("value", ["webdavs://", "webdavs://user:pw@", "/some/dir"])
def test_parse_rejects_invalid(value: str) -> None:
    with pytest.raises(WebdavError):
        parse(value)


@respx.mock
async def test_client_sends_basic_auth_without_credentials_in_the_url() -> None:
    route = respx.route(method="PROPFIND", url=f"{BASE}/f").mock(return_value=multistatus(5))
    location = parse("webdavs://user:p%20w@dav.example.com/some/path")
    async with location.client() as client:
        assert await WebdavStore(location.base_url, client).exists_size("f") == 5
    # end with
    assert route.calls[0].request.headers["Authorization"].startswith("Basic ")
    assert "p%20w" not in str(route.calls[0].request.url)


@respx.mock
async def test_exists_size() -> None:
    respx.route(method="PROPFIND", url=f"{BASE}/a").mock(return_value=multistatus(7))
    respx.route(method="PROPFIND", url=f"{BASE}/dir").mock(return_value=multistatus(None))
    respx.route(method="PROPFIND", url=f"{BASE}/gone").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        store = WebdavStore(BASE, client)
        assert await store.exists_size("a") == 7
        assert await store.exists_size("dir") is None
        assert await store.exists_size("gone") is None
        assert await store.stat("dir") == (True, None)
    # end with


@respx.mock
async def test_exists_size_falls_back_to_head() -> None:
    respx.route(method="PROPFIND").mock(return_value=httpx.Response(405))
    respx.head(f"{BASE}/a").mock(return_value=httpx.Response(200, headers={"Content-Length": "9"}))
    async with httpx.AsyncClient() as client:
        assert await WebdavStore(BASE, client).exists_size("a") == 9
    # end with


@respx.mock
async def test_mkdirs_goes_top_down_tolerates_existing_and_caches() -> None:
    route = respx.route(method="MKCOL").mock(
        side_effect=[httpx.Response(403), httpx.Response(405), httpx.Response(201), httpx.Response(405), httpx.Response(201)],
    )
    async with httpx.AsyncClient() as client:
        store = WebdavStore(BASE, client)
        await store.mkdirs("_releases_/v1")
        await store.mkdirs("_releases_/v1")
        await store.mkdirs("_releases_/v2")
    # end with
    assert [str(call.request.url) for call in route.calls] == [
        "https://dav.example.com/some", BASE, f"{BASE}/_releases_", f"{BASE}/_releases_/v1", f"{BASE}/_releases_/v2",
    ]


@respx.mock
async def test_mkdirs_fails_on_errors_below_the_base() -> None:
    respx.route(method="MKCOL").mock(side_effect=[httpx.Response(405), httpx.Response(405), httpx.Response(403)])
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError):
            await WebdavStore(BASE, client).mkdirs("_releases_")
        # end with
    # end with


@respx.mock
async def test_write_stream_puts_part_then_moves_and_cleans_up_on_failure() -> None:
    put = respx.put(f"{BASE}/d/a.bin.part").mock(return_value=httpx.Response(201))
    move = respx.route(method="MOVE", url=f"{BASE}/d/a.bin.part").mock(return_value=httpx.Response(201))

    async def chunks():
        yield b"ab"
        yield b"cd"

    async with httpx.AsyncClient() as client:
        store = WebdavStore(BASE, client)
        await store.write_stream("d/a.bin", chunks(), 4)
        assert put.calls[0].request.content == b"abcd"
        assert put.calls[0].request.headers["Content-Length"] == "4"
        assert move.calls[0].request.headers["Destination"] == f"{BASE}/d/a.bin"
        assert move.calls[0].request.headers["Overwrite"] == "T"

        put.mock(return_value=httpx.Response(507))
        delete = respx.delete(f"{BASE}/d/a.bin.part").mock(return_value=httpx.Response(204))
        with pytest.raises(httpx.HTTPStatusError):
            await store.write_stream("d/a.bin", chunks(), 4)
        # end with
        assert delete.called
    # end with


@respx.mock
async def test_ranged_read() -> None:
    route = respx.get(f"{BASE}/f").mock(return_value=httpx.Response(206, content=b"cd"))
    async with httpx.AsyncClient() as client:
        store = WebdavStore(BASE, client)
        assert await store.read("f", 2, 4) == b"cd"
        assert route.calls[0].request.headers["Range"] == "bytes=2-3"
        route.mock(return_value=httpx.Response(200, content=b"abcdef"))  # server ignores ranges
        assert await store.read("f", 2, 4) == b"cd"
        assert await store.read("f", 4) == b"ef"
        route.mock(return_value=httpx.Response(416))
        assert await store.read("f", 99) == b""
    # end with


@respx.mock
async def test_set_latest_writes_latest_txt_only_if_the_release_exists() -> None:
    respx.route(method="PROPFIND", url=f"{BASE}/_releases_/v1").mock(return_value=multistatus(None))
    respx.route(method="PROPFIND", url=f"{BASE}/_releases_/v9").mock(return_value=httpx.Response(404))
    put = respx.put(f"{BASE}/_releases_/latest.txt").mock(return_value=httpx.Response(201))
    async with httpx.AsyncClient() as client:
        store = WebdavStore(BASE, client)
        assert await store.set_latest("v1")
        assert put.calls[0].request.content == b"v1\n"
        assert not await store.set_latest("v9")
    # end with
    assert put.call_count == 1


@respx.mock
async def test_download_asset_skips_matching_size_and_uploads_otherwise() -> None:
    asset = AssetInfo(name="a.zip", size=3, url="https://example.test/a")
    respx.get(asset.url).mock(return_value=httpx.Response(200, content=b"abc"))
    stat = respx.route(method="PROPFIND", url=f"{BASE}/r/a.zip").mock(return_value=httpx.Response(404))
    put = respx.put(f"{BASE}/r/a.zip.part").mock(return_value=httpx.Response(201))
    respx.route(method="MOVE", url=f"{BASE}/r/a.zip.part").mock(return_value=httpx.Response(201))
    async with httpx.AsyncClient() as client:
        store = WebdavStore(BASE, client)
        assert await download_asset(client, asset, store, "r") is True
        assert put.calls[0].request.content == b"abc"
        stat.mock(return_value=multistatus(3))
        assert await download_asset(client, asset, store, "r") is False
    # end with
