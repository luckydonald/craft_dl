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
