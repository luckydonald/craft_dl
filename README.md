# craft_dl
Download [https://github.com/storytold/*craft](https://github.com/orgs/storytold/repositories) applications for archival reasons.


## Usage

```sh
uv run craft_dl                                   # everything for all repos ending with `*craft`, basically same as: --dl=repo,release --app='*'
uv run craft_dl download --dl=repo,release --app=photo,craft-fonts,cad
uv run craft_dl --app=sound --app=word            # repeated instead of comma-separated
uv run craft_dl --app='**'                        # every storytold/* repository, not only those ending with `*craft` 
```
#### General Parameters
- Those tell the tool where & how to download, and which repos to look at, and if you want to download code or releases or both. 
- The default is to download everything for every repo ending with `*craft`.
- Filter the releases further with the [Release Parameters](#release-parameters), as [explained below](#filtering-release-downloads).

##### Parameters:
- **`--dl`**: Source code and/or releases.
  - `repo` (clone/fetch + backup refs)
  - `release` (release notes + assets into `_releases_/<tag>/`).
  - `*`, `all`, `both` (**default**) are equivalent to `repo,release`.
- **`--app`**: Which app to download.
  - Free text entry.
    - The part `craft` is implied as suffix (`photo` downloads `photocraft`).
    - Falling back to the bare name if not found with the added tail.
  - `*` or `all` (**default**) is every repo named `<word>craft`,
  - `**` or `@storytold` is a special value to download all @storytold repos, not only those matching `*craft`.
- **`--repo-dir`**: Where those downloads should be placed into.
  - **default**: `~/git/storytold/`.
- **`--github-token`**: Optional token to use with the GitHub API, to prevent/reduce hitting rate limits.
  - if not set, checks `gh auth token` (if installed), or
  - or the environment variable `$GITHUB_TOKEN`.
  - in that order of preference when.
  - If nothing is providing an API token, the script will still work but may hit rate limits.

## Failure
- Every step may fail independently without preventing other downloads
- errors are collected and printed at the end together 
  - with commands to retry only the failed parts.

## Filtering release downloads

Release assets are large, so which ones to fetch can be narrowed down per app. `README.md` (the release notes) and checksum files such as `SHA256SUMS.txt` are always saved for every selected release.

```sh
uv run craft_dl --dl=release --app=art --release=v0.41.0,latest --platform=win --variant=msi --platform=mac \
                --app=photo --release=v0.5.0 --variant=dmg,flatpak,aarch64
```

#### Release Parameters
- The options form a chain with the scope order `app > release > platform > variant`. A new option keeps the levels above it and resets the levels below it.
  - The example above has three groups:
    1. `art`, releases `v0.41.0`+`latest`, platform `win`, variant `msi`
    2. the same for platform `mac` without a variant
    3. and `photo`, release `v0.5.0`, any platform, variants `dmg`, `flatpak` or `aarch64`.
    - In case `latest` no longer point to `v0.41.0`, **1.** and **2.** are repeated for that tag as well.  
  - Within a group the values of one level are alternatives
  - the levels narrow down each other (platform *and* variant).
  - Matches:
    - An asset is downloaded when any group of its repo accepts it.
    - A requested release that does not exist, or a platform/variant that matches no asset, is reported.
  - Without any of these options everything is downloaded.
- Filters before the first `--app` apply to the default `*` apps if no `--app` is given at all
  - otherwise they are ambiguous and rejected.

##### Parameters:
- **`--release`**: tag or bare version to limit to.
  - `v0.41.0` = `0.41.0`,
  - `latest`
  - `*` or `all` (**default**) for all available releases.
- **`--platform`**: 
  - `win`/`windows`,
  - `mac`/`macos`/`apple`/`osx`/`darwin` (includes `*.app.tar.gz`),
  - `freebsd`/`bsd`, 
  - `linux`,
  - `*` or `all` (**default**) for all available platforms (unfiltered).
  - A suffix is a variant:
    - `--platform=win-x64-setup` is `--platform=win --variant=x64-setup`.
- **`--variant`**: any word of the file name,
  - e.g. `msi`, `exe`, `setup`, `portable`, `dmg`, `deb`, `rpm`, `appimage`, `flatpak`, `tar-gz`, `zip`.
  - `*` or `all` (**default**) for all available variants (unfiltered). 
  - Dashes join words that must all be present (`x64-setup` is equivalent to `x64,setup`).
  - Without a platform it matches on every platform.
  - CPU architectures have aliases:
    - `aarch64` = `arm64` = `armv8` = `m1`, `m2`, … = `apple-chip` = `apple-silicon` = `silicon` (implies macOS `universal` builds, too)
    - `x64` = `x86_64` = `amd64` = `intel` (implies macOS `universal` builds, too)
    - `x86` = `i386`
    - `universal` (macOS) as variant will only match that one exactly, and not load separte `arm64` or `x64` versions.
    - So `--variant=aarch64` also selects the `windows-arm64` builds; add `--platform=linux` to narrow it down.
- **`--dl-cli`**: if the normal apps and/or the CLI tool should be downloaded.
  - i.e. assets with `-cli-` in the name
  - e.g. `photocraft-cli-0.5.0-macos-universal.zip`.
  - `all` = `*` = `both` = `true` = `yes` = `ja` = `j` = `y` = `1`
    - **default**
    - Downloads them all
  - `app` = `false` = `no` = `nein` = `n` = `0`
    - skip the CLI tools.
  - `cli-only` = `only` = `cli` = `nur` = `o` = `-1`
    - skip the Apps themselves.

## Backup refs

After each fetch, every new or changed branch/tag tip gets local branches, so force pushes stay recoverable:

- `bak/{branch,tag}/<name/with/slashes>/<YYYY-MM-DD>/<HH-MM-SS>/<commit>`
- `bak/commit/<sha1>`

Recover an overwritten branch tip with `git branch restored bak/commit/<sha1>`.
