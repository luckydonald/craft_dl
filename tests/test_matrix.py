"""Every documented flag, run against the names of all assets released so far."""

import itertools

import pytest

from craft_dl.assets import PLATFORM_ALIASES, is_checksum, platform_of, tokens, variant_matches
from craft_dl.chain import Selector, parse_chain
from craft_dl.filtering import CliMode, asset_matches, matching_selectors, release_matches, select_assets
from tests.snapshot import SNAPSHOT, all_assets, releases_of

REPOS = sorted(SNAPSHOT)
PLATFORMS = sorted(PLATFORM_ALIASES)
VARIANTS = [
    "msi", "exe", "setup", "portable", "dmg", "deb", "rpm", "appimage", "flatpak", "tar-gz", "zip", "zsync", "x64", "x86", "x86_64",
    "amd64", "intel", "aarch64", "arm64", "m1", "m2", "apple-silicon", "apple-chip", "i386", "universal", "x64-setup", "x64-portable",
]
COMPOUND_PLATFORMS = ["win-portable", "win-x64", "win-setup", "win-x64-setup", "mac-universal", "linux-aarch64", "apple-m1", "windows-msi"]
# `artcraft` only ever shipped Windows and macOS installers (its universal builds do satisfy the Apple-silicon names),
# so these flags legitimately match nothing there.
# Every other (repo, flag) pair must match, so a regression to "matches nothing" is caught.
ARTCRAFT_NOTHING = {
    "linux", "freebsd", "bsd", "portable", "deb", "rpm", "appimage", "flatpak", "zip", "zsync", "x86", "i386", "x64-portable",
    "win-portable", "linux-aarch64",
}
EXPECTED_NOTHING: set[tuple[str, str]] = {("artcraft", flag) for flag in ARTCRAFT_NOTHING} | {
    (repo, flag) for repo in REPOS for flag in ("setup", "x64-setup", "exe", "win-setup", "win-x64-setup") if repo != "artcraft"
}
ARM = ["aarch64", "arm64", "armv8", "m1", "m2", "silicon", "apple-silicon", "apple-chip"]
INTEL = ["x64", "x86_64", "x86-64", "amd64", "intel"]
X86 = ["x86", "i386", "i686", "ia32"]
NOT_CLASSIFIED = {name for _, _, name in all_assets() if platform_of(name) is None}


def selected(repo: str, selector: Selector, cli_mode: CliMode = CliMode.both) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for release in releases_of(repo):
        matched = matching_selectors([selector], release.tag, None)
        for asset in select_assets(matched, release.assets, cli_mode):
            result.add((release.tag, asset.name))
        # end for
    # end for
    return result
# end def


def without_checksums(items: set[tuple[str, str]]) -> set[tuple[str, str]]:
    return {(tag, name) for tag, name in items if not is_checksum(name)}
# end def


def group_of(repo: str, flag: str, kind: str) -> Selector:
    if kind == "platform":
        return parse_chain([f"--app={repo}", f"--platform={flag}"])[0]
    # end if
    return Selector((repo,), (), (), (flag,))
# end def


def test_snapshot_is_not_empty() -> None:
    assert len(REPOS) >= 10
    assert len(all_assets()) > 500


def test_every_asset_is_classifiable() -> None:
    unknown = {name for name in NOT_CLASSIFIED if not is_checksum(name) and "-web-" not in name}
    assert unknown == set()


@pytest.mark.parametrize("repo", REPOS)
@pytest.mark.parametrize("flag", PLATFORMS)
def test_every_platform_flag_matches_something(repo: str, flag: str) -> None:
    found = without_checksums(selected(repo, group_of(repo, flag, "platform")))
    if (repo, flag) in EXPECTED_NOTHING:
        assert not found
    else:
        assert found, f"--platform={flag} matches nothing in {repo}"
    # end if


@pytest.mark.parametrize("repo", REPOS)
@pytest.mark.parametrize("flag", VARIANTS)
def test_every_variant_flag_matches_something(repo: str, flag: str) -> None:
    found = without_checksums(selected(repo, group_of(repo, flag, "variant")))
    if (repo, flag) in EXPECTED_NOTHING:
        assert not found
    else:
        assert found, f"--variant={flag} matches nothing in {repo}"
    # end if


@pytest.mark.parametrize("repo", REPOS)
@pytest.mark.parametrize("flag", COMPOUND_PLATFORMS)
def test_every_compound_platform_matches_something(repo: str, flag: str) -> None:
    selectors = parse_chain([f"--app={repo}", f"--platform={flag}"])
    found: set[tuple[str, str]] = set()
    for release in releases_of(repo):
        found |= {(release.tag, a.name) for a in select_assets(selectors, release.assets, CliMode.both) if not is_checksum(a.name)}
    # end for
    if (repo, flag) in EXPECTED_NOTHING:
        assert not found
    else:
        assert found, f"--platform={flag} matches nothing in {repo}"
    # end if


@pytest.mark.parametrize("repo", REPOS)
@pytest.mark.parametrize(("platform", "variant"), list(itertools.product(sorted(set(PLATFORM_ALIASES.values())), VARIANTS)))
def test_platform_variant_cross_matrix(repo: str, platform: str, variant: str) -> None:
    selector = Selector((repo,), (), (platform,), (variant,))
    expected = {
        (tag, name) for owner, tag, name in all_assets()
        if owner == repo and platform_of(name) == platform and variant_matches(variant, name) and not is_checksum(name)
    }
    assert without_checksums(selected(repo, selector)) == expected
    for _, name in expected:
        assert set(tokens(variant)) <= set(tokens(name)) or "universal" in tokens(name)
    # end for


@pytest.mark.parametrize("repo", REPOS)
@pytest.mark.parametrize("group", [ARM, INTEL, X86])
def test_architecture_aliases_select_identical_sets(repo: str, group: list[str]) -> None:
    results = [selected(repo, Selector((repo,), (), (), (alias,))) for alias in group]
    assert all(result == results[0] for result in results)


@pytest.mark.parametrize("repo", REPOS)
def test_x86_and_x64_never_mix(repo: str) -> None:
    x86 = without_checksums(selected(repo, Selector((repo,), (), (), ("x86",))))
    x64 = without_checksums(selected(repo, Selector((repo,), (), (), ("x64",))))
    assert not any("x86_64" in name or "x64" in name.lower() for _, name in x86)
    assert not any("windows-x86." in name or "windows-x86-" in name for _, name in x64)


@pytest.mark.parametrize("repo", REPOS)
def test_universal_implies_both_mac_architectures(repo: str) -> None:
    universal = without_checksums(selected(repo, Selector((repo,), (), ("mac",), ("universal",))))
    assert universal
    for arch in ("arm64", "x64", "m1", "intel"):
        assert universal <= without_checksums(selected(repo, Selector((repo,), (), ("mac",), (arch,))))
    # end for
    everything = without_checksums(selected(repo, Selector((repo,), (), (), ("universal",))))
    assert all(platform_of(name) == "mac" for _, name in everything)


@pytest.mark.parametrize("repo", REPOS)
def test_windows_arm_selects_only_windows_arm_builds(repo: str) -> None:
    found = without_checksums(selected(repo, Selector((repo,), (), ("windows",), ("aarch64",))))
    assert all("arm64" in name.lower() or "aarch64" in name.lower() for _, name in found)
    assert all(platform_of(name) == "windows" for _, name in found)


@pytest.mark.parametrize("repo", REPOS)
@pytest.mark.parametrize("group", [["win", "windows"], ["mac", "macos", "apple", "osx", "darwin"], ["bsd", "freebsd"]])
def test_platform_aliases_select_identical_sets(repo: str, group: list[str]) -> None:
    results = [selected(repo, parse_chain([f"--app={repo}", f"--platform={alias}"])[0]) for alias in group]
    assert all(result == results[0] for result in results)


@pytest.mark.parametrize("repo", REPOS)
def test_platform_suffix_equals_explicit_variant(repo: str) -> None:
    sugar = selected(repo, parse_chain([f"--app={repo}", "--platform=win-x64"])[0])
    explicit = selected(repo, parse_chain([f"--app={repo}", "--platform=win", "--variant=x64"])[0])
    assert sugar == explicit


@pytest.mark.parametrize("repo", REPOS)
def test_checksums_are_always_kept_and_cli_modes_partition(repo: str) -> None:
    selector = Selector((repo,), (), ("linux",), ("deb",))
    both = selected(repo, selector, CliMode.both)
    app = selected(repo, selector, CliMode.app)
    cli = selected(repo, selector, CliMode.cli_only)
    assert both == app | cli
    for release in releases_of(repo):
        names = {a.name for a in release.assets}
        for checksum in (n for n in names if is_checksum(n)):
            assert (release.tag, checksum) in both
        # end for
    # end for
    assert not any("-cli-" in name for _, name in app)
    assert all("-cli-" in name or is_checksum(name) for _, name in cli)


@pytest.mark.parametrize("repo", REPOS)
def test_platform_partition_loses_nothing(repo: str) -> None:
    everything = {(tag, name) for r, tag, name in all_assets() if r == repo}
    parts: set[tuple[str, str]] = set()
    for platform in sorted(set(PLATFORM_ALIASES.values())):
        parts |= selected(repo, Selector((repo,), (), (platform,), ()))
    # end for
    unclassified = {(tag, name) for tag, name in everything if platform_of(name) is None and not is_checksum(name)}
    checksums = {(tag, name) for tag, name in everything if is_checksum(name)}
    assert parts | unclassified | checksums == everything


@pytest.mark.parametrize(("repo", "tag"), [(repo, tag) for repo in REPOS for tag in SNAPSHOT[repo]])
def test_release_matching(repo: str, tag: str) -> None:
    version = tag.rsplit("v", 1)[-1] if "v" in tag else tag
    assert release_matches(Selector((repo,), (tag,), (), ()), tag, None)
    assert release_matches(Selector((repo,), (version,), (), ()), tag, None)
    assert release_matches(Selector((repo,), (f"v{version}",), (), ()), tag, None)
    assert release_matches(Selector((repo,), ("latest",), (), ()), tag, tag)
    assert not release_matches(Selector((repo,), ("latest",), (), ()), tag, None)
    assert not release_matches(Selector((repo,), ("v99.99.99",), (), ()), tag, tag)


def test_split_releases_share_a_version() -> None:
    tags = SNAPSHOT["artcraft"]
    matched = [tag for tag in tags if release_matches(Selector(("artcraft",), ("v0.5.0",), (), ()), tag, None)]
    assert matched == ["artcraft-v0.5.0", "artcraft-windows-v0.5.0"]


def test_asset_matches_without_filters_accepts_everything() -> None:
    assert all(asset_matches(Selector(), name) for _, _, name in all_assets())
