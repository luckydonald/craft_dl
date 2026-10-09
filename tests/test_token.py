import pytest

from craft_dl import token


async def test_flag_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    assert await token.resolve_token("flag", {"GITHUB_TOKEN": "env"}) == "flag"
# end def


async def test_gh_before_env(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake() -> str | None:
        return "gh"
    # end def
    monkeypatch.setattr(token, "gh_cli_token", fake)
    assert await token.resolve_token(None, {"GITHUB_TOKEN": "env"}) == "gh"
# end def


async def test_env_when_no_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake() -> str | None:
        return None
    # end def
    monkeypatch.setattr(token, "gh_cli_token", fake)
    assert await token.resolve_token(None, {"GITHUB_TOKEN": "env"}) == "env"
    assert await token.resolve_token(None, {}) is None
# end def
