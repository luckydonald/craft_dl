import logging
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

logger = logging.getLogger(__name__)

OPEN = "/usr/bin/open"  # sh/make-like environments have weird $PATHs, use direct paths
MOUNT = "/sbin/mount"
VOLUMES = Path("/Volumes")
SCHEME = "smb:"
TIMEOUT_SECONDS = 30


class SmbError(Exception):
    """The share could not be parsed, mounted or found."""
# end class


@dataclass(frozen=True)
class SmbPath:
    """`smb://{ServerName}._smb._tcp.local/{Mount}/{dir1/dir2}`"""

    server: str
    share: str
    subpath: str

    @property
    def url(self) -> str:
        return f"smb://{self.server}/{quote(self.share)}"
    # end def

    @property
    def volume(self) -> Path:
        return VOLUMES / self.share
    # end def

    @property
    def local_path(self) -> Path:
        return self.volume / self.subpath if self.subpath else self.volume
    # end def
# end class


def has_protocol(path: Path | str) -> bool:
    """`Path("smb://host/share")` collapses to `smb:/host/share`, so both spellings count."""
    return str(path).lower().startswith(SCHEME + "/")
# end def


def parse(path: Path | str) -> SmbPath:
    if not has_protocol(path):
        raise SmbError(f"not an smb:// path: {path}")
    # end if
    rest = str(path)[len(SCHEME):].lstrip("/")
    server, _, remainder = rest.partition("/")
    share, _, subpath = remainder.partition("/")
    if not server or not share:
        raise SmbError(f"expected smb://<server>/<mount>[/<dir>], got {path}")
    # end if
    return SmbPath(server, share, subpath.strip("/"))
# end def


def mounted_volumes() -> str:
    return subprocess.run([MOUNT], capture_output=True, text=True, check=False).stdout
# end def


def is_mounted(volume: Path) -> bool:
    """Like the Makefile: some line of `mount` says `on /Volumes/<Mount> `."""
    return f"on {volume} " in mounted_volumes()
# end def


def open_share(url: str) -> None:
    try:
        subprocess.run([OPEN, url], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise SmbError(f"could not open {url}: {error}") from error
    # end try
# end def


def wait_until(condition: Callable[[], bool], what: str, timeout: int = TIMEOUT_SECONDS) -> None:
    for _ in range(timeout):
        if condition():
            return
        # end if
        time.sleep(1)
    # end for
    if not condition():
        raise SmbError(f"timed out after {timeout}s waiting for {what}")
    # end if
# end def


def mount(path: Path | str, timeout: int = TIMEOUT_SECONDS) -> Path:
    """Mounts the share if needed (macOS `open smb://…`) and returns the path below `/Volumes/<Mount>`."""
    target = parse(path)
    if is_mounted(target.volume):
        logger.info("%s is already mounted.", target.volume)
    else:
        logger.info("Mounting %s from %s…", target.volume, target.url)
        open_share(target.url)
        wait_until(lambda: is_mounted(target.volume), f"{target.volume} to be mounted", timeout)
    # end if
    wait_until(target.local_path.is_dir, f"{target.local_path} to exist", timeout)
    return target.local_path
# end def
