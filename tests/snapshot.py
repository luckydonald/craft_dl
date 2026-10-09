"""Asset names of every release published in the `storytold` `*craft` repos.

`tests/data/release_assets.json` was generated with
`gh api repos/storytold/<repo>/releases --paginate --jq '.[] | {tag: .tag_name, assets: [.assets[].name]}'` for each repo.
Regenerate it when a new naming scheme appears; `tests/test_matrix.py` then tells which names the filters cannot classify.
"""

import json
from pathlib import Path

from craft_dl.models import AssetInfo, ReleaseInfo

SNAPSHOT: dict[str, dict[str, list[str]]] = json.loads((Path(__file__).parent / "data" / "release_assets.json").read_text())


def releases_of(repo: str) -> list[ReleaseInfo]:
    return [
        ReleaseInfo(tag=tag, name=tag, body="", assets=[AssetInfo(name, 1, f"https://example.test/{tag}/{name}") for name in names])
        for tag, names in SNAPSHOT[repo].items()
    ]
# end def


def all_assets() -> list[tuple[str, str, str]]:
    """`(repo, tag, asset name)` of every released asset."""
    return [(repo, tag, name) for repo, tags in SNAPSHOT.items() for tag, names in tags.items() for name in names]
# end def
