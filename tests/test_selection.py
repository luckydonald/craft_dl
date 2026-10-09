from craft_dl.cli import parse_dl
from craft_dl.models import Dl
from craft_dl.selection import resolve_apps, split_values

REPOS = ["photocraft", "artcraft", "placeholder-artcraft", "craft-fonts", "photocraft-corpus", "artcraftx", "cadcraft", "spark"]


def test_split_values_comma_and_repeat() -> None:
    assert split_values(["sound,word", "word", " cad "]) == ["sound", "word", "cad"]
# end def


def test_default_matches_only_single_word_craft() -> None:
    resolved, unresolved = resolve_apps(["*"], REPOS)
    assert resolved == ["photocraft", "artcraft", "cadcraft"]
    assert unresolved == []
# end def


def test_double_star_is_everything() -> None:
    assert resolve_apps(["**"], REPOS)[0] == REPOS
# end def


def test_suffix_implied_then_bare_fallback() -> None:
    resolved, unresolved = resolve_apps(["photo", "craft-fonts", "spark", "nope"], REPOS)
    assert resolved == ["photocraft", "craft-fonts", "spark"]
    assert unresolved == ["nope"]
# end def


def test_all_is_the_default_pattern_and_dl_wildcard() -> None:
    assert resolve_apps(["all"], ["photocraft", "craft-fonts"]) == (["photocraft"], [])
    assert parse_dl(["*"]) == set(Dl)
    assert parse_dl(["all"]) == set(Dl)


def test_at_storytold_is_every_repo_and_both_is_dl_default() -> None:
    assert resolve_apps(["@storytold"], ["photocraft", "craft-fonts"]) == (["photocraft", "craft-fonts"], [])
    assert parse_dl(["both"]) == set(Dl)
