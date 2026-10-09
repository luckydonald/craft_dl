# craft_dl
Download [https://github.com/storytold/*craft](https://github.com/orgs/storytold/repositories) applications for archival reasons.


## Usage

```sh
uv run craft_dl                                   # everything: --dl=repo,release --app='*'
uv run craft_dl download --dl=repo,release --app=photo,craft-fonts,cad
uv run craft_dl --app=sound --app=word            # repeated instead of comma-separated
uv run craft_dl --app='**'                        # every storytold/* repository
```

- `--dl`: `repo` (clone/fetch + backup refs) and/or `release` (release notes + assets into `_releases_/<tag>/`). Default: both.
- `--app`: `craft` is implied as suffix (`photo` is `photocraft`), falling back to the bare name. `*` (default) is every repo named `<word>craft`, `**` is all repos.
- `--repo-dir`: default `~/git/storytold/`.
- `--github-token`: overrides `gh auth token` and `$GITHUB_TOKEN` (in that order of preference when not given).

Every step may fail independently; errors are collected and printed at the end together with commands to retry only the failed parts.

## Backup refs

After each fetch, every new or changed branch/tag tip gets local branches, so force pushes stay recoverable:

- `bak/{branch,tag}/<name/with/slashes>/<YYYY-MM-DD>/<HH-MM-SS>/<commit>`
- `bak/commit/<sha1>`

Recover an overwritten branch tip with `git branch restored bak/commit/<sha1>`.
