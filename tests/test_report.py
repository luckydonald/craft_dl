from craft_dl.chain import parse_chain
from craft_dl.models import Dl
from craft_dl.report import ErrorCollector


def test_retry_commands_group_by_dl() -> None:
    errors = ErrorCollector()
    errors.add("photocraft", Dl.release, "asset", "boom")
    errors.add("cadcraft", Dl.release, "asset", "boom")
    errors.add("cadcraft", Dl.repo, "fetch", "boom")
    errors.add(None, None, "list repositories", "boom")
    assert errors.retry_commands() == [
        "uv run craft_dl download --dl=repo --app=cadcraft",
        "uv run craft_dl download --dl=release --app=photocraft --app=cadcraft",
        "uv run craft_dl download",
    ]
# end def


def test_no_errors() -> None:
    assert ErrorCollector().render() == "All done, no errors."
# end def


def test_release_retry_keeps_filters_and_puts_unfiltered_repos_last() -> None:
    errors = ErrorCollector()
    errors.add("cadcraft", Dl.release, "asset", "boom")
    errors.add("photocraft", Dl.release, "asset", "boom")
    selectors = {"photocraft": parse_chain("--app=photo --release=v0.5.0 --variant=dmg".split())}
    assert errors.retry_commands(selectors, ["--dl-cli=app"]) == [
        "uv run craft_dl download --dl=release --app=photocraft --release=v0.5.0 --variant=dmg --app=cadcraft --dl-cli=app",
    ]
    assert "--release=v0.5.0" in errors.render(selectors)
# end def
