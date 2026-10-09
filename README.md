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

## Filtering release downloads

Release assets are large, so which ones to fetch can be narrowed down per app. `README.md` (the release notes) and checksum files such as `SHA256SUMS.txt` are always saved for every selected release.

```sh
uv run craft_dl --dl=release --app=art --release=v0.41.0,latest --platform=win --variant=msi --platform=mac \
                --app=photo --release=v0.5.0 --variant=dmg,flatpak,aarch64
```

- The options form a chain with the scope order `app > release > platform > variant`. A new option keeps the levels above it and resets the levels below it.
  The example above has three groups: `art`, releases `v0.41.0`+`latest`, platform `win`, variant `msi`; the same for platform `mac` without a variant; and `photo`, release `v0.5.0`, any platform, variants `dmg`, `flatpak` or `aarch64`.
- Within a group the values of one level are alternatives; the levels narrow down each other (platform *and* variant). An asset is downloaded when any group of its repo accepts it.
- Without any of these options everything is downloaded. A requested release that does not exist, or a platform/variant that matches no asset, is reported.
- `--release`: tag or bare version (`v0.41.0`, `0.41.0`; split releases like `artcraft-windows-v0.5.0` share the version), or `latest`.
- `--platform`: `win`/`windows`, `mac`/`macos`/`apple`/`osx`/`darwin` (includes `*.app.tar.gz`), `linux`, `freebsd`/`bsd`. A suffix is a variant: `win-x64-setup` is `--platform=win --variant=x64-setup`.
- `--variant`: any word of the file name, e.g. `msi`, `exe`, `setup`, `portable`, `dmg`, `deb`, `rpm`, `appimage`, `flatpak`, `tar-gz`, `zip`. Dashes join words that must all be present (`x64-setup`). Without a platform it matches on every platform.
- CPU architectures have aliases: `aarch64` = `arm64` = `armv8` = `m1`, `m2`, … = `apple-silicon` = `apple-chip`; `x64` = `x86_64` = `amd64` = `intel`; `x86` = `i386`. `universal` macOS builds count as both `arm64` and `x64`.
  So `--variant=aarch64` also selects the `windows-arm64` builds; add `--platform=linux` to narrow it down.
- `--dl-cli`: assets with `-cli-` in the name (e.g. `photocraft-cli-0.5.0-macos-universal.zip`). `both` (default; also `true`, `yes`, `ja`, `j`, `y`, `1`), `app` to skip them (`false`, `no`, `nein`, `n`, `0`), `cli-only` to take only them (`only`, `cli`, `nur`, `o`, `-1`).

Filters before the first `--app` apply to the default `*` apps if no `--app` is given at all; otherwise they are ambiguous and rejected. Retry commands keep the filters of each failed repo.

## Backup refs

After each fetch, every new or changed branch/tag tip gets local branches, so force pushes stay recoverable:

- `bak/{branch,tag}/<name/with/slashes>/<YYYY-MM-DD>/<HH-MM-SS>/<commit>`
- `bak/commit/<sha1>`

Recover an overwritten branch tip with `git branch restored bak/commit/<sha1>`.
