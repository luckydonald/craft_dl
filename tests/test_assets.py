import pytest

from craft_dl.assets import is_checksum, is_cli, platform_of, split_platform, tokens, variant_matches


@pytest.mark.parametrize(("name", "platform"), [
    ("ArtCraft_0.41.0_x64_en-US.msi", "windows"),
    ("ArtCraft_0.41.0_x64-setup_windows.exe", "windows"),
    ("ArtCraft_universal.app.tar.gz", "mac"),
    ("ArtCraft_0.5.0_universal_darwin.dmg", "mac"),
    ("photocraft-0.5.0-linux-aarch64.AppImage.zsync", "linux"),
    ("photocraft-0.5.0-freebsd-x86_64.tar.gz", "freebsd"),
    ("photocraft-cli-0.5.0-macos-universal.zip", "mac"),
    ("photocraft-0.5.0-windows-x64.wixpdb", "windows"),
    ("photocraft-web-0.5.0.zip", None),
    ("SHA256SUMS.txt", None),
])
def test_platform_of(name: str, platform: str | None) -> None:
    assert platform_of(name) == platform


def test_x86_is_not_x86_64() -> None:
    assert not variant_matches("x86", "p-0.5.0-linux-x86_64.deb")
    assert variant_matches("x86", "p-0.5.0-windows-x86.msi")
    assert not variant_matches("x64", "p-0.5.0-windows-x86.msi")
    assert variant_matches("x64", "p-0.5.0-linux-x86_64.deb")


@pytest.mark.parametrize("alias", ["aarch64", "arm64", "armv8", "m1", "M2", "apple-silicon", "apple-chip"])
def test_arm_aliases(alias: str) -> None:
    assert variant_matches(alias, "p-0.5.0-linux-aarch64.deb")
    assert variant_matches(alias, "p-0.5.0-windows-arm64.msi")
    assert not variant_matches(alias, "p-0.5.0-linux-x86_64.deb")


@pytest.mark.parametrize("alias", ["x64", "x86_64", "x86-64", "amd64", "intel"])
def test_intel_aliases(alias: str) -> None:
    assert variant_matches(alias, "p-0.5.0-windows-x64.msi")
    assert variant_matches(alias, "p-0.5.0-linux-x86_64.deb")
    assert not variant_matches(alias, "p-0.5.0-linux-aarch64.deb")


def test_universal_implies_both_mac_architectures() -> None:
    name = "p-0.5.0-macos-universal.dmg"
    assert variant_matches("arm64", name)
    assert variant_matches("m1", name)
    assert variant_matches("x64", name)
    assert variant_matches("universal", name)
    assert not variant_matches("x86", name)
    assert not variant_matches("universal", "p-0.5.0-windows-x64.msi")


def test_dash_variant_needs_all_tokens() -> None:
    assert variant_matches("x64-setup", "ArtCraft_0.41.0_x64-setup.exe")
    assert not variant_matches("x64-setup", "ArtCraft_0.41.0_x64_en-US.msi")
    assert variant_matches("tar-gz", "p-0.5.0-linux-x86_64.tar.gz")


def test_tokens_normalize_compounds() -> None:
    assert tokens("p-0.5.0-linux-x86_64.tar.gz") == ["p", "0", "5", "0", "linux", "x64", "targz"]


def test_cli_and_checksum() -> None:
    assert is_cli("photocraft-cli-0.5.0-macos-universal.zip")
    assert not is_cli("photocraft-0.5.0-macos-universal.dmg")
    assert is_checksum("SHA256SUMS.txt")
    assert not is_checksum("photocraft-0.5.0-macos-universal.dmg")


def test_split_platform() -> None:
    assert split_platform("win-x64-setup") == ("windows", "x64-setup")
    assert split_platform("Apple") == ("mac", None)
    with pytest.raises(ValueError, match="amiga"):
        split_platform("amiga")
