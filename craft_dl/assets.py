import re
from collections.abc import Iterable

WINDOWS = "windows"
MAC = "mac"
LINUX = "linux"
FREEBSD = "freebsd"

PLATFORM_ALIASES: dict[str, str] = {
    "win": WINDOWS,
    "windows": WINDOWS,
    "apple": MAC,
    "mac": MAC,
    "macos": MAC,
    "osx": MAC,
    "darwin": MAC,
    "linux": LINUX,
    "freebsd": FREEBSD,
    "bsd": FREEBSD,
}

EXTENSION_PLATFORMS: dict[str, str] = {
    "msi": WINDOWS,
    "exe": WINDOWS,
    "wixpdb": WINDOWS,
    "dmg": MAC,
    "pkg": MAC,
    "deb": LINUX,
    "rpm": LINUX,
    "appimage": LINUX,
    "flatpak": LINUX,
    "snap": LINUX,
}

# Multi-word spellings that must be joined before splitting on non-alphanumerics (`x86_64` must never turn into `x86` + `64`).
COMPOUNDS: dict[str, str] = {
    "x86_64": "x64",
    "x86-64": "x64",
    "apple-silicon": "arm64",
    "apple-chip": "arm64",
    "app.tar.gz": "app targz",
    "tar.gz": "targz",
    "tar-gz": "targz",
}

# Same CPU architecture, different names: everything maps to one canonical spelling.
ARCH_ALIASES: dict[str, str] = {
    "arm64": "arm64",
    "aarch64": "arm64",
    "armv8": "arm64",
    "silicon": "arm64",
    "x64": "x64",
    "amd64": "x64",
    "intel": "x64",
    "x86": "x86",
    "i386": "x86",
    "i686": "x86",
    "ia32": "x86",
}

APPLE_CHIP = re.compile(r"^m\d+$")
UNIVERSAL = "universal"
UNIVERSAL_ARCHS = frozenset({"arm64", "x64"})
CHECKSUM_NAMES = ("sha256sums", "sha512sums", "checksums", "md5sums")
CHECKSUM_SUFFIXES = (".sha256", ".sha512", ".sha1", ".md5")


def canonical_token(token: str) -> str:
    if APPLE_CHIP.match(token):
        return "arm64"
    # end if
    return ARCH_ALIASES.get(token, token)
# end def


def tokens(text: str) -> list[str]:
    """Lowercase alphanumeric tokens with architecture aliases and multi-word compounds normalized."""
    text = text.lower()
    for compound, replacement in COMPOUNDS.items():
        text = text.replace(compound, f" {replacement} ")
    # end for
    return [canonical_token(token) for token in re.split(r"[^a-z0-9]+", text) if token]
# end def


def platform_of(name: str) -> str | None:
    """Platform an asset is built for, from its tokens and then its extension; `None` if it is platform independent."""
    parts = tokens(name)
    for part in parts:
        if part in PLATFORM_ALIASES:
            return PLATFORM_ALIASES[part]
        # end if
    # end for
    if "app" in parts and "targz" in parts:
        return MAC
    # end if
    for part in reversed(parts):
        if part in EXTENSION_PLATFORMS:
            return EXTENSION_PLATFORMS[part]
        # end if
    # end for
    return None
# end def


def variant_matches(variant: str, name: str) -> bool:
    """Every dash-joined token of the variant must be in the name; `universal` builds satisfy `arm64` and `x64`."""
    parts = set(tokens(name))
    for wanted in tokens(variant):
        if wanted in parts:
            continue
        # end if
        if wanted in UNIVERSAL_ARCHS and UNIVERSAL in parts:
            continue
        # end if
        return False
    # end for
    return True
# end def


def is_cli(name: str) -> bool:
    return "cli" in tokens(name)
# end def


def is_checksum(name: str) -> bool:
    lowered = name.lower()
    stem = lowered.rsplit(".", 1)[0]
    return stem in CHECKSUM_NAMES or lowered.endswith(CHECKSUM_SUFFIXES)
# end def


def known_platform(value: str) -> str | None:
    return PLATFORM_ALIASES.get(value.strip().lower())
# end def


def split_platform(value: str) -> tuple[str, str | None]:
    """`win-x64-setup` -> (`windows`, `x64-setup`); raises `ValueError` for an unknown platform."""
    head, _, rest = value.strip().lower().partition("-")
    platform = known_platform(head)
    if platform is None:
        raise ValueError(f"unknown platform {value!r}, expected one of: {', '.join(sorted(PLATFORM_ALIASES))}")
    # end if
    return platform, rest or None
# end def


def any_variant(variants: Iterable[str], name: str) -> bool:
    return any(variant_matches(variant, name) for variant in variants)
# end def
