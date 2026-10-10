import logging
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import httpx

from craft_dl.store import LATEST_LINK, RELEASES_DIR, safe_relative

logger = logging.getLogger(__name__)

SCHEMES = {"webdav": "http", "webdavs": "https"}
TIMEOUT = httpx.Timeout(60.0, connect=15.0)
PROPFIND_BODY = '<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:"><d:prop><d:getcontentlength/></d:prop></d:propfind>'
LATEST_FILE = f"{LATEST_LINK}.txt"


class WebdavError(Exception):
    """The WebDAV location could not be parsed, or the server answered unexpectedly."""
# end class


@dataclass(frozen=True)
class WebdavLocation:
    """`webdavs://user:escaped%20password@domain.example.com/some/path`, credentials already unescaped."""

    base_url: str
    user: str | None = None
    password: str | None = None

    def client(self) -> httpx.AsyncClient:
        """A dedicated client: the credentials must never be sent anywhere else (e.g. to GitHub)."""
        auth = httpx.BasicAuth(self.user, self.password or "") if self.user is not None else None
        return httpx.AsyncClient(auth=auth, timeout=TIMEOUT, follow_redirects=False)
    # end def
# end class


def has_protocol(path: Path | str) -> bool:
    """`Path("webdavs://host/x")` collapses to `webdavs:/host/x`, so both spellings count."""
    scheme, colon, rest = str(path).lower().partition(":")
    return bool(colon) and scheme in SCHEMES and rest.startswith("/")
# end def


def parse(path: Path | str) -> WebdavLocation:
    if not has_protocol(path):
        raise WebdavError("not a webdav:// or webdavs:// path")
    # end if
    scheme, _, rest = str(path).partition(":")
    parts = urlsplit(f"{scheme.lower()}://{rest.lstrip('/')}")
    try:
        host = parts.hostname
        port = parts.port
    except ValueError as error:
        raise WebdavError(f"invalid host or port: {error}") from error
    # end try
    if not host:
        raise WebdavError("expected webdavs://[<user>[:<password>]@]<host>[:<port>]/<dir>")
    # end if
    host = f"[{host}]" if ":" in host else host
    netloc = host if port is None else f"{host}:{port}"
    base_url = f"{SCHEMES[parts.scheme]}://{netloc}{parts.path.rstrip('/')}"
    user = unquote(parts.username) if parts.username is not None else None
    password = unquote(parts.password) if parts.password is not None else None
    return WebdavLocation(base_url, user, password)
# end def


class WebdavStore:
    """Reads and writes a WebDAV collection directly. Credentials live in the client, never in a URL or a message.

    Missing folders, including those of the base URL's path, are created as needed.
    """

    def __init__(self, base_url: str, client: httpx.AsyncClient, known_dirs: set[str] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client
        self.known_dirs: set[str] = known_dirs if known_dirs is not None else set()
    # end def

    @property
    def location(self) -> str:
        return self.base_url
    # end def

    def sub(self, name: str) -> "WebdavStore":
        return WebdavStore(self.url(name), self.client, self.known_dirs)
    # end def

    def url(self, path: str = "") -> str:
        segments = [quote(segment) for segment in safe_relative(path).split("/")] if path else []
        return "/".join([self.base_url, *segments])
    # end def

    async def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        return await self.client.request(method, self.url(path), **kwargs)
    # end def

    async def stat(self, path: str = "") -> tuple[bool, int | None]:
        """`(exists, size)`, where the size is `None` for collections."""
        response = await self.request("PROPFIND", path, headers={"Depth": "0", "Content-Type": "application/xml"}, content=PROPFIND_BODY)
        if response.is_redirect and response.headers.get("Location", "").endswith("/"):  # a collection asked for without its slash
            response = await self.client.request(
                "PROPFIND", self.url(path) + "/", headers={"Depth": "0", "Content-Type": "application/xml"}, content=PROPFIND_BODY,
            )
        # end if
        if response.status_code == 404:
            return False, None
        # end if
        if response.status_code in (405, 501):  # no PROPFIND, a plain HEAD tells enough
            response = await self.request("HEAD", path)
            if response.status_code == 404:
                return False, None
            # end if
            response.raise_for_status()
            length = response.headers.get("Content-Length")
            return True, int(length) if length is not None and length.isdigit() else None
        # end if
        response.raise_for_status()
        try:
            element = ET.fromstring(response.content).find(".//{DAV:}getcontentlength")
        except ET.ParseError as error:
            raise WebdavError(f"unreadable PROPFIND answer for {self.url(path)}: {error}") from error
        # end try
        text = element.text.strip() if element is not None and element.text else ""
        return True, int(text) if text.isdigit() else None
    # end def

    async def exists_size(self, path: str) -> int | None:
        exists, size = await self.stat(path)
        return size if exists else None
    # end def

    async def mkdirs(self, path: str) -> None:
        """`MKCOL` is not recursive: one request per segment, top-down, starting at the host root.

        The segments of the base URL are best effort (405 = exists, 403 = some servers refuse existing top-level collections),
        below them every failure but 405 is an error.
        """
        base_count = len(self.path_segments(self.base_url))
        origin = self.base_url[: len(self.base_url) - len(urlsplit(self.base_url).path)]
        segments = self.path_segments(self.url(safe_relative(path)))
        for index in range(len(segments)):
            url = f"{origin}/{'/'.join(segments[: index + 1])}"
            if url in self.known_dirs:
                continue
            # end if
            response = await self.client.request("MKCOL", url + "/")  # collections want the slash, else some servers answer 301
            if response.status_code != 405 and not (index < base_count and response.status_code == 403):
                response.raise_for_status()
            # end if
            self.known_dirs.add(url)
        # end for
    # end def

    @staticmethod
    def path_segments(url: str) -> list[str]:
        return [segment for segment in urlsplit(url).path.split("/") if segment]
    # end def

    async def write_text(self, path: str, text: str) -> None:
        (await self.request("PUT", path, content=text.encode(), headers={"Content-Type": "text/plain; charset=utf-8"})).raise_for_status()
    # end def

    async def write_stream(self, path: str, chunks: AsyncIterator[bytes], size: int) -> None:
        """`PUT` to `<path>.part`, then `MOVE` over the final name, so a half-uploaded file is never visible there."""
        partial = path + ".part"
        done = False
        try:
            (await self.request("PUT", partial, content=chunks, headers={"Content-Length": str(size)})).raise_for_status()
            (await self.request("MOVE", partial, headers={"Destination": self.url(path), "Overwrite": "T"})).raise_for_status()
            done = True
        finally:
            if not done:
                with suppress(httpx.HTTPError):
                    await self.request("DELETE", partial)
                # end with
            # end if
        # end try
    # end def

    async def read(self, path: str, start: int = 0, end: int | None = None) -> bytes:
        """A ranged `GET` (`end` exclusive); a server without range support sends everything, which is sliced here."""
        if end is not None and end <= start:
            return b""
        # end if
        response = await self.request("GET", path, headers={"Range": f"bytes={start}-{'' if end is None else end - 1}"})
        if response.status_code == 416:  # starts behind the end of the file
            return b""
        # end if
        response.raise_for_status()
        return response.content if response.status_code == 206 else response.content[start:end]
    # end def

    async def set_latest(self, tag: str) -> bool:
        """WebDAV has no symlinks, so `_releases_/latest.txt` holds the tag instead."""
        if not (await self.stat(f"{RELEASES_DIR}/{safe_relative(tag)}"))[0]:
            return False
        # end if
        await self.write_text(f"{RELEASES_DIR}/{LATEST_FILE}", tag + "\n")
        logger.info("%s/%s/%s -> %s", self.base_url, RELEASES_DIR, LATEST_FILE, tag)
        return True
    # end def
# end class
