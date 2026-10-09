# Platform, variant and release filters for release downloads

**Commit style:** Skill `/commit-with-lplp-style` is active, and `/code-style` rules apply (see `ai/skills/code-style/references/py.md`).

## Context

The downloader (`craft_dl/`, commits `c98dc8b` and `58e9577`) currently saves every release and every non-source asset of each selected repo.
Assets are large (a single `photocraft` run filled the disk), so the user wants to select what to fetch: by release, by platform (`win`, `mac`, `linux`, …) and by variant (`msi`, `dmg`, `x64`, `portable`, `setup`, …), configurable per app in one command line.
`README.md` (release notes) and checksum files (`SHA256SUMS.txt`) are always saved for every matched release.

Decisions confirmed with the user:
- Filters form a chain with the scope order `app > release > platform > variant`.
  A new option resets everything *below* its own level and keeps everything above.
  So `--app` resets release, platform and variant; `--release` keeps the app but resets platform and variant; `--platform` keeps app and release but resets variants.
- Within one group the values of one kind are alternatives (OR), across kinds they narrow down (AND): platform AND variant.
  A variant without a platform in its group matches across all platforms.
- `*.app.tar.gz` counts as `mac`, so plain `--platform=mac` also includes it.
  The example in the request was wrong about excluding it, and about including `photocraft-cli-…-macos-universal.zip` for `--variant=dmg,flatpak,aarch64` (no platform in that group, so the CLI zip does not match).
- `aarch64` and `arm64` are *not* aliases for now (literal tokens), matching the example, which excludes `windows-arm64`.
  The alias table lives in one place (`assets.py`), so adding `arm64 = aarch64`, `m1`/`m2`/`apple-silicon`, or `universal` implications later is a one-line change.
- A new `--dl-cli` switch controls assets that contain `-cli-` in their name (e.g. `photocraft-cli-0.5.0-macos-universal.zip`).
- Unit-test matrices run the flags against the asset names of all currently released versions (see Tests).

## CLI

New options on `download`, all optional, all accepting comma-separated and repeated values:

- `--release=v0.41.0,latest`: matches tags by version, so `v0.41.0` and `0.41.0` match `artcraft-v0.41.0` and also split releases such as `artcraft-windows-v0.5.0` next to `artcraft-v0.5.0` (their version part is equal).
  `latest` resolves via the GitHub "latest release" endpoint.
  No `--release` means all releases (today's behavior).
- `--platform=win|windows`, `apple|mac|macos|osx|darwin`, `linux`, `freebsd|bsd`, case-insensitive.
  A dash suffix is sugar for variants: `win-x64-setup` equals `--platform=win --variant=x64-setup`, `mac-universal` equals `--platform=mac --variant=universal`.
- `--variant=msi,dmg,flatpak`: alternatives.
  A dash joins tokens that must *all* be present (`x64-setup` needs both `x64` and `setup`).
- `--dl-cli=` (global, default `both`): `both` = `true|yes|ja|j|y|1`, `app` = `false|no|nein|n|0` (drop assets containing `-cli-`), `cli-only` = `only|cli|nur|o|-1` (keep only those).
  It filters *after* the platform/variant selection, so `--platform=mac` with the default `both` yields the `.dmg`, the `.app.tar.gz` and the CLI zip.
  Invalid values produce a clear error listing the accepted spellings.

Chain semantics, using the corrected version of the user's example:

```
--app=art --release=v0.41.0,latest --platform=win --variant=msi --platform=mac --app=photo --release=v0.5.0 --variant=dmg,flatpak,aarch64
```

Groups: `(art, [v0.41.0, latest], win, [msi])`, `(art, [v0.41.0, latest], mac, [])`, `(photo, [v0.5.0], -, [dmg, flatpak, aarch64])`.
Downloads (plus `README.md` and `SHA256SUMS.txt` where present):
- `artcraft-v0.41.0`: `ArtCraft_0.41.0_x64_en-US.msi`, `ArtCraft_0.41.0_universal.dmg`, `ArtCraft_universal.app.tar.gz`; not `ArtCraft_0.41.0_x64-setup.exe`.
- `photocraft` `v0.5.0`: `…macos-universal.dmg`, both `…linux-*.flatpak`, and the `linux-aarch64` `AppImage`, `AppImage.zsync`, `deb`, `rpm`, `tar.gz`; nothing from `windows-arm64`, `freebsd`, `x86_64` (other than flatpak), `web`, or the CLI zip.

Rules for the chain parser:
- `--app=a,b` gives the following filters to both apps.
- Filter options before the first `--app` apply to the default `*` apps if no `--app` appears anywhere; if an `--app` appears later, orphan filters before it are an error (ambiguous).
- `--platform=win,mac` is one group with two platforms; `--platform=win --platform=mac` yields two groups.
  A `--release` after a platform or variant starts a new group (the lower filters reset), repeated consecutive `--release` values add alternatives.
- An asset is downloaded if *any* group of its repo accepts it (union), so overlapping groups are harmless.

## Implementation

Cyclopts parses each list option separately and loses the interleaving order, so the chain is built from the raw tokens.

- `craft_dl/chain.py` (new): `Selector` frozen dataclass `(apps: tuple[str, ...], releases, platforms, variants)` and `parse_chain(tokens: Sequence[str]) -> list[Selector]`, a small state machine over `--app/--release/--platform/--variant` in both `--opt=value` and `--opt value` form.
  Also `selector_args(selectors)` that renders a repo's selectors back into CLI arguments, for retry commands.
- `craft_dl/assets.py` (new): pure functions.
  - `tokens(name)`: lowercase, normalize known compounds first (`x86_64`/`x86-64`/`amd64` become one token so `x86` does not match `x86_64`; `en-us`), then split on non-alphanumerics.
  - `platform_of(name)`: from tokens (`windows|win`, `macos|mac|darwin|osx`, `linux`, `freebsd`), falling back to extension (`msi|exe` is windows, `dmg|pkg|app.tar.gz` is mac, `deb|rpm|appimage|flatpak|snap` is linux), else `None` (e.g. `photocraft-web-0.5.0.zip`, matched only when no platform filter is given).
  - `PLATFORM_ALIASES`, `VARIANT_ALIASES` (empty for now), `is_cli(name)` (token `cli`), `is_checksum(name)` (`sha256sums`, `checksums`, `*.sha256`, `*.sha512`).
- `craft_dl/filtering.py` (new): `CliMode` enum with the spelling table and parser, `release_matches(selector, tag, latest_tag)` (compares the version part of the tag; exact tag also matches), `asset_matches(selector, name)`, and `select_assets(selectors, release, cli_mode, latest_tag) -> list[AssetInfo]` which always keeps checksum files of matched releases.
- `craft_dl/cli.py`: add `release`, `platform`, `variant` (list options, for validation and `--help`) and `dl_cli`; build the chain from the raw argv via `cli.parse_args(tokens)` and pass it to the command through a non-parsed parameter (`Parameter(parse=False)`).
  If that cyclopts hook turns out unavailable in the installed version, fall back to `main()` calling `parse_chain(sys.argv[1:])` and handing the result to `download_async`.
  Each chain group's `apps` are resolved with the existing `selection.resolve_apps`, so `*`, `**`, `photo` and `craft-fonts` keep working.
  The repo (`--dl=repo`) part uses the union of all groups' apps, so filters never change which repos are cloned.
- `craft_dl/sync.py`: `Context` gains `selectors: dict[str, list[Selector]]` (per resolved repo) and `cli_mode`.
  `list_all_releases` resolves the latest tag once when any selector mentions `latest` and drops non-matching releases before any file is written; a requested release that does not exist is recorded as an error (`release v9.9.9 not found`), so it appears in the retry summary.
  A repo without selectors (no filters given) keeps today's download-everything behavior.
- `craft_dl/releases.py`: `sync_release` receives the already-filtered asset list (README is still written for matched releases); no changes to the download logic itself (`.part` files, skip-existing).
- `craft_dl/report.py`: retry commands include the repo's own filters (`--app=photocraft --release=v0.5.0 --variant=…`) via `selector_args`, so a retry doesn't widen the download.
- Filters that match no asset at all (e.g. the `flatpack` typo, which is not fuzzy-matched) log a warning naming the filter and the release, so typos are visible; they do not change the exit code.
- `README.md`: document the chain semantics, the platform and variant vocabulary, `--dl-cli`, and the corrected example.

## Tests (pytest)

### Snapshot of all currently released assets

- `tests/data/release_assets.json`: for every `storytold` `*craft` repo, every release tag with its asset names, as returned by the GitHub API today (about 12 repos; a few KB).
  Generated once with a read-only `gh api repos/storytold/<repo>/releases --paginate` and committed as a fixture, so the tests run offline and stay deterministic.
  A short note in the test module says how to regenerate it when new naming schemes appear.
- Covers the real naming schemes: `ArtCraft_<v>_x64_en-US.msi`, `ArtCraft_<v>_x64-setup.exe`, `ArtCraft_<v>_universal.dmg`, `ArtCraft_universal.app.tar.gz`, legacy `…_windows.exe` and `…_darwin.dmg`, the `<app>-<v>-<os>-<arch>[-portable].<ext>` family, `<app>-cli-<v>-macos-universal.zip`, `<app>-web-<v>.zip`, `.AppImage.zsync`, `.flatpak`, `freebsd` tarballs, `SHA256SUMS.txt`.

### Matrix tests (`tests/test_matrix.py`, parametrized over the snapshot)

- **Every asset is classifiable:** for each asset in the snapshot, `platform_of` returns a platform, except an explicit allow-list (`*-web-*.zip`, checksum files); a new unknown naming scheme fails the test and must be added consciously.
- **Every documented flag matches something:** a table of all documented platforms (`win`, `windows`, `apple`, `mac`, `macos`, `osx`, `darwin`, `linux`, `freebsd`, `bsd`) and all documented variants and compound forms (`msi`, `exe`, `setup`, `portable`, `dmg`, `deb`, `rpm`, `appimage`, `flatpak`, `tar-gz`, `zip`, `x64`, `x86`, `x86_64`, `aarch64`, `arm64` (expected to match only if the snapshot has such files; marked `xfail` otherwise), `universal`, `win-portable`, `win-x64`, `win-setup`, `win-x64-setup`, `mac-universal`, `linux-aarch64`), each parametrized per repo: assert at least one asset of some release matches, or that the pair is listed in an explicit "expected to match nothing" table (e.g. `freebsd` for repos without BSD builds), so a regression that silently matches nothing is caught.
- **Platform × variant cross matrix:** for every (platform, variant) pair, the selection equals the brute-force result of `platform_of(name) == platform and variant tokens ⊆ tokens(name)`, which cross-checks the selection pipeline against the primitives for all released names.
- **Alias equivalence:** `win`/`windows`, `mac`/`macos`/`apple`/`osx`/`darwin`, and `--platform=win --variant=x64` vs. `--platform=win-x64` select identical sets for every repo.
- **Invariants over all releases:** checksum files are always selected for a matched release; `--dl-cli=app` never returns an asset with `-cli-`, `--dl-cli=cli-only` returns only those, `both` is their union; selecting `win` ∪ `mac` ∪ `linux` ∪ `freebsd` ∪ unclassified equals all assets (nothing lost, nothing double-counted by accident).
- **Release matching matrix:** every tag in the snapshot is matched by its own exact tag and by its bare version (`0.41.0`, `v0.41.0`); split releases (`artcraft-windows-v0.5.0` and `artcraft-v0.5.0`) both match `v0.5.0`; `latest` matches exactly the tag given as latest.

### Focused unit tests

- `tests/test_assets.py`: tokens and `platform_of` spot checks (`x64_en-US.msi` is windows, `universal.app.tar.gz` is mac, `x86_64` does not match variant `x86`, `web` has no platform).
- `tests/test_chain.py`: reset rules (`--app` resets all, `--release` resets platform and variant, `--platform` resets variants), comma and repeated forms, `win-x64-setup` sugar, `--opt value` form, orphan-filter error, and the full example above.
- `tests/test_filtering.py`: the corrected example's exact download list for `artcraft-v0.41.0` and `photocraft` `v0.5.0`; `--dl-cli` spellings; union of overlapping groups.
- `tests/test_report.py`: retry commands keep the repo's filters.
- `tests/test_sync.py`: with a `FakeSource` and `respx`, only matching assets are requested and `README.md` and `SHA256SUMS.txt` are written.

## Verification

1. `uv run pytest` passes, including the matrices against the committed snapshot.
2. Dry check without downloading much: `uv run craft_dl --dl=release --repo-dir=$(mktemp -d) --app=art --release=v0.41.0 --platform=win --variant=msi` downloads `README.md` and the single `.msi` (check `df -h` first, since a previous full run filled the disk).
3. `uv run craft_dl --help` shows the new options, and invalid `--dl-cli=maybe` and `--platform=amiga` fail with a helpful message.
4. Run the corrected example from this plan against a temp dir and compare the resulting file list to the expectation above.

## Notes

- Not covered on purpose: fuzzy matching of misspelled variants, and architecture aliases (see the decision above).
- Existing behavior without any new option is unchanged.
