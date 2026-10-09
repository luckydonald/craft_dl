import pytest

from craft_dl.chain import Selector, parse_chain
from craft_dl.filtering import CliMode, matching_selectors, missing_releases, parse_cli_mode, select_assets, unmatched_selectors, version_of
from craft_dl.models import AssetInfo
from tests.snapshot import SNAPSHOT, releases_of

EXAMPLE = parse_chain(
    "--app=artcraft --release=v0.41.0,latest --platform=win --variant=msi --platform=mac "
    "--app=photocraft --release=v0.5.0 --variant=dmg,flatpak,aarch64".split(),
)


def chosen(repo: str, tag: str, cli_mode: CliMode = CliMode.both) -> set[str]:
    selectors = [s for s in EXAMPLE if repo in s.apps]
    release = next(r for r in releases_of(repo) if r.tag == tag)
    matched = matching_selectors(selectors, tag, "artcraft-v0.41.0")
    return {a.name for a in select_assets(matched, release.assets, cli_mode)}
# end def


def test_example_artcraft() -> None:
    assert chosen("artcraft", "artcraft-v0.41.0") == {
        "ArtCraft_0.41.0_x64_en-US.msi",
        "ArtCraft_0.41.0_universal.dmg",
        "ArtCraft_universal.app.tar.gz",
    }


def test_example_photocraft() -> None:
    version = "0.5.0"
    assert chosen("photocraft", "v0.5.0") == {
        f"photocraft-{version}-macos-universal.dmg",
        f"photocraft-cli-{version}-macos-universal.zip",
        f"photocraft-{version}-linux-aarch64.AppImage",
        f"photocraft-{version}-linux-aarch64.AppImage.zsync",
        f"photocraft-{version}-linux-aarch64.deb",
        f"photocraft-{version}-linux-aarch64.flatpak",
        f"photocraft-{version}-linux-aarch64.rpm",
        f"photocraft-{version}-linux-aarch64.tar.gz",
        f"photocraft-{version}-linux-x86_64.flatpak",
        f"photocraft-{version}-windows-arm64.msi",
        f"photocraft-{version}-windows-arm64-portable.zip",
        "SHA256SUMS.txt",
    }


def test_unselected_release_is_not_matched() -> None:
    assert matching_selectors(EXAMPLE, "artcraft-v0.37.0", "artcraft-v0.41.0") == []


@pytest.mark.parametrize(("value", "mode"), [
    ("both", CliMode.both), ("YES", CliMode.both), ("ja", CliMode.both), ("1", CliMode.both),
    ("app", CliMode.app), ("no", CliMode.app), ("nein", CliMode.app), ("0", CliMode.app),
    ("cli-only", CliMode.cli_only), ("only", CliMode.cli_only), ("nur", CliMode.cli_only), ("-1", CliMode.cli_only),
])
def test_cli_mode_spellings(value: str, mode: CliMode) -> None:
    assert parse_cli_mode(value) is mode


def test_invalid_cli_mode() -> None:
    with pytest.raises(ValueError, match="maybe"):
        parse_cli_mode("maybe")


def test_cli_mode_filters_after_platform() -> None:
    selector = Selector(("photocraft",), ("v0.5.0",), ("mac",), ())
    release = next(r for r in releases_of("photocraft") if r.tag == "v0.5.0")
    assets = release.assets
    both = {a.name for a in select_assets([selector], assets, CliMode.both)}
    app = {a.name for a in select_assets([selector], assets, CliMode.app)}
    cli = {a.name for a in select_assets([selector], assets, CliMode.cli_only)}
    assert both == {"photocraft-0.5.0-macos-universal.dmg", "photocraft-cli-0.5.0-macos-universal.zip", "SHA256SUMS.txt"}
    assert app == {"photocraft-0.5.0-macos-universal.dmg", "SHA256SUMS.txt"}
    assert cli == {"photocraft-cli-0.5.0-macos-universal.zip", "SHA256SUMS.txt"}


def test_no_selector_means_everything_but_cli_mode_applies() -> None:
    assets = [AssetInfo("a-cli-1.zip", 1, ""), AssetInfo("a-1.zip", 1, "")]
    assert len(select_assets([], assets, CliMode.both)) == 2
    assert [a.name for a in select_assets([], assets, CliMode.app)] == ["a-1.zip"]


def test_overlapping_groups_are_a_union() -> None:
    a = Selector(("x",), (), ("windows",), ())
    b = Selector(("x",), (), (), ("msi",))
    assets = [AssetInfo(n, 1, "") for n in ("p-1-windows-x64.msi", "p-1-windows-x64.zip", "p-1-linux.deb")]
    assert [x.name for x in select_assets([a, b], assets, CliMode.both)] == ["p-1-windows-x64.msi", "p-1-windows-x64.zip"]


def test_version_of() -> None:
    assert version_of("artcraft-windows-v0.5.0") == "0.5.0"
    assert version_of("v0.1.1-rc.4") == "0.1.1-rc.4"
    assert version_of("nightly") is None


def test_missing_releases_and_typos() -> None:
    tags = list(SNAPSHOT["artcraft"])
    selector = Selector(("artcraft",), ("v9.9.9", "0.41.0", "latest"), (), ())
    assert missing_releases([selector], tags, None) == ["v9.9.9", "latest"]
    assert missing_releases([selector], tags, "artcraft-v0.41.0") == ["v9.9.9"]
    typo = Selector(("photocraft",), (), (), ("flatpack",))
    release = next(r for r in releases_of("photocraft") if r.tag == "v0.5.0")
    assert unmatched_selectors([typo], release.assets) == [typo]


@pytest.mark.parametrize("value", ["*", "all", "ALL"])
def test_dl_cli_wildcard(value: str) -> None:
    assert parse_cli_mode(value) is CliMode.both
