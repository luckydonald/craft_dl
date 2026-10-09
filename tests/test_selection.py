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
