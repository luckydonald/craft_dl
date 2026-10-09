import re
from collections.abc import Sequence
from enum import StrEnum

from craft_dl.assets import any_variant, is_checksum, is_cli, platform_of
from craft_dl.chain import Selector
from craft_dl.models import AssetInfo

LATEST = "latest"
VERSION = re.compile(r"(?:^|[^0-9a-z])v?(\d+(?:\.\d+)+[0-9a-z.+-]*)$")


class CliMode(StrEnum):
    """What to do with assets that contain `-cli-` in their name."""

    both = "both"
    app = "app"
    cli_only = "cli-only"
# end class


CLI_SPELLINGS: dict[str, CliMode] = {
    **dict.fromkeys(("both", "*", "all", "true", "yes", "ja", "j", "y", "1"), CliMode.both),
    **dict.fromkeys(("app", "false", "no", "nein", "n", "0"), CliMode.app),
    **dict.fromkeys(("cli-only", "only", "cli", "nur", "o", "-1"), CliMode.cli_only),
}


def parse_cli_mode(value: str) -> CliMode:
    try:
        return CLI_SPELLINGS[value.strip().lower()]
    except KeyError:
        raise ValueError(f"invalid --dl-cli value {value!r}, expected one of: {', '.join(CLI_SPELLINGS)}") from None
    # end try
# end def


def version_of(tag: str) -> str | None:
    """`artcraft-windows-v0.5.0` -> `0.5.0`, `v0.1.1-rc.4` -> `0.1.1-rc.4`."""
    found = VERSION.search(tag.lower())
    return found.group(1) if found else None
# end def


def release_value_matches(value: str, tag: str, latest_tag: str | None) -> bool:
    value = value.lower()
    if value == LATEST:
        return latest_tag is not None and tag == latest_tag
    # end if
    if value == tag.lower():
        return True
    # end if
    version = version_of(tag)
    wanted = version_of(value)
    return version is not None and wanted is not None and version == wanted
# end def


def wants_latest(selectors: Sequence[Selector]) -> bool:
    return any(LATEST in selector.releases for selector in selectors)
# end def


def release_matches(selector: Selector, tag: str, latest_tag: str | None) -> bool:
    return not selector.releases or any(release_value_matches(value, tag, latest_tag) for value in selector.releases)
# end def


def matching_selectors(selectors: Sequence[Selector], tag: str, latest_tag: str | None) -> list[Selector]:
    return [selector for selector in selectors if release_matches(selector, tag, latest_tag)]
# end def


def missing_releases(selectors: Sequence[Selector], tags: Sequence[str], latest_tag: str | None) -> list[str]:
    """Requested `--release` values that match no existing release."""
    missing: list[str] = []
    for selector in selectors:
        for value in selector.releases:
            if value not in missing and not any(release_value_matches(value, tag, latest_tag) for tag in tags):
                missing.append(value)
            # end if
        # end for
    # end for
    return missing
# end def


def asset_matches(selector: Selector, name: str) -> bool:
    if selector.platforms and platform_of(name) not in selector.platforms:
        return False
    # end if
    return not selector.variants or any_variant(selector.variants, name)
# end def


def select_assets(matched: Sequence[Selector], assets: Sequence[AssetInfo], cli_mode: CliMode) -> list[AssetInfo]:
    """Assets accepted by any matched selector (no selector means no restriction); checksum files are always kept."""
    chosen: list[AssetInfo] = []
    for asset in assets:
        if is_checksum(asset.name):
            chosen.append(asset)
            continue
        # end if
        if cli_mode is CliMode.app and is_cli(asset.name):
            continue
        # end if
        if cli_mode is CliMode.cli_only and not is_cli(asset.name):
            continue
        # end if
        if not matched or any(asset_matches(selector, asset.name) for selector in matched):
            chosen.append(asset)
        # end if
    # end for
    return chosen
# end def


def unmatched_selectors(matched: Sequence[Selector], assets: Sequence[AssetInfo]) -> list[Selector]:
    """Selectors with platform/variant filters that accept none of the release's assets, usually a typo."""
    names = [asset.name for asset in assets if not is_checksum(asset.name)]
    if not names:
        return []
    # end if
    return [
        selector for selector in matched
        if (selector.platforms or selector.variants) and not any(asset_matches(selector, name) for name in names)
    ]
# end def
