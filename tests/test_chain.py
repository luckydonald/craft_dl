import pytest

from craft_dl.chain import ChainError, Selector, chain_apps, parse_chain, selector_args

EXAMPLE = "--app=art --release=v0.41.0,latest --platform=win --variant=msi --platform=mac --app=photo --release=v0.5.0 --variant=dmg,flatpak,aarch64"


def test_example_chain() -> None:
    assert parse_chain(EXAMPLE.split()) == [
        Selector(("art",), ("v0.41.0", "latest"), ("windows",), ("msi",)),
        Selector(("art",), ("v0.41.0", "latest"), ("mac",), ()),
        Selector(("photo",), ("v0.5.0",), (), ("dmg", "flatpak", "aarch64")),
    ]
    assert chain_apps(parse_chain(EXAMPLE.split())) == ["art", "photo"]


def test_space_separated_form_and_foreign_options() -> None:
    tokens = ["download", "--dl=release", "--app", "art", "--repo-dir", "/x", "--platform", "win"]
    assert parse_chain(tokens) == [Selector(("art",), (), ("windows",), ())]


def test_repeated_levels_extend_until_something_deeper_is_set() -> None:
    assert parse_chain("--app=a --app=b --release=1 --release=2 --variant=x --variant=y".split()) == [
        Selector(("a", "b"), ("1", "2"), (), ("x", "y")),
    ]


def test_release_resets_platform_and_variant_but_keeps_app() -> None:
    assert parse_chain("--app=a --release=1 --platform=win --variant=msi --release=2".split()) == [
        Selector(("a",), ("1",), ("windows",), ("msi",)),
        Selector(("a",), ("2",), (), ()),
    ]


def test_app_resets_everything() -> None:
    assert parse_chain("--app=a --release=1 --platform=win --app=b".split()) == [
        Selector(("a",), ("1",), ("windows",), ()),
        Selector(("b",), (), (), ()),
    ]


def test_platform_list_is_one_group_and_repeat_is_two() -> None:
    assert parse_chain("--app=a --platform=win,mac".split()) == [Selector(("a",), (), ("windows", "mac"), ())]
    assert parse_chain("--app=a --platform=win --platform=mac".split()) == [
        Selector(("a",), (), ("windows",), ()),
        Selector(("a",), (), ("mac",), ()),
    ]


def test_platform_suffix_is_sugar_for_variants() -> None:
    assert parse_chain("--app=a --platform=win-x64-setup".split()) == parse_chain("--app=a --platform=win --variant=x64-setup".split())
    assert parse_chain("--app=a --platform=win-x64,mac-universal".split()) == [
        Selector(("a",), (), ("windows",), ("x64",)),
        Selector(("a",), (), ("mac",), ("universal",)),
    ]


def test_filters_without_app_apply_to_default_apps() -> None:
    assert parse_chain(["--platform=win"]) == [Selector(("*",), (), ("windows",), ())]
    assert parse_chain([]) == []
    assert chain_apps([]) == ["*"]


def test_orphan_filters_before_first_app_are_ambiguous() -> None:
    with pytest.raises(ChainError, match="before the first --app"):
        parse_chain("--platform=win --app=a".split())


def test_errors() -> None:
    with pytest.raises(ChainError, match="amiga"):
        parse_chain(["--platform=amiga"])
    with pytest.raises(ChainError, match="needs a value"):
        parse_chain(["--app"])


def test_selector_args_round_trip() -> None:
    selectors = parse_chain(EXAMPLE.split())[:2]
    args = selector_args("artcraft", selectors)
    assert args == [
        "--app=artcraft", "--release=v0.41.0,latest", "--platform=windows", "--variant=msi",
        "--app=artcraft", "--release=v0.41.0,latest", "--platform=mac",
    ]
    assert parse_chain(args) == [Selector(("artcraft",), s.releases, s.platforms, s.variants) for s in selectors]
