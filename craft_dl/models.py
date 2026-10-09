from dataclasses import dataclass, field
from enum import StrEnum


class Dl(StrEnum):
    """What `--dl` can select."""

    repo = "repo"
    release = "release"
# end class


@dataclass(frozen=True)
class AssetInfo:
    name: str
    size: int
    url: str
# end class


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    name: str
    body: str
    assets: list[AssetInfo] = field(default_factory=list)
# end class
