# craft_dl: archive downloader for the `storytold/*craft` repositories

**Commit style:** Skill `/commit-with-lplp-style` is active, and `/code-style` rules apply (see `ai/skills/code-style/references/py.md`).

## Context

`craft_dl` is freshly bootstrapped from `base/base` and contains no Python package yet (no `pyproject.toml`, only base tooling under `scripts/`).
Goal: a CLI that mirrors every `*craft*` repository of the GitHub org `storytold` (git history plus release assets) into `~/git/storytold/`, for archival.
Backup thoroughness beats strictness: every step may fail, the rest continues, and all failures are reported at the end with copy-pasteable retry commands.

Decisions confirmed with the user:
- Backup ref date format is ISO, with time and commit appended: `…/YYYY-MM-DD/HH-MM-SS/{commit}`.
- GitHub is accessed through a typed async client library (`githubkit`, built on `httpx`) instead of a hand-rolled client.
  Token precedence: `--github-token=…`, then `gh auth token` (if `gh` is installed and logged in), then env `GITHUB_TOKEN`, else unauthenticated.
- CLI uses a typed parser (`cyclopts`, driven by type hints), and progress is shown with `rich` (overall bar plus in-repo bar).
- Release downloading is independent of the git clone/fetch step.

## Layout

New package `craft_dl/` at the repo root, Python `3.14+`, fully typed, async where practical, no `_`-prefixed names, `# end if`/`# end def`/… block comments.
Each module is small and separately testable.

- `pyproject.toml`: `uv` project, `requires-python >=3.14`, dependencies `githubkit`, `cyclopts`, `rich`, dev deps `pytest`, `pytest-asyncio`, `respx` (githubkit uses `httpx` underneath); script entry `craft_dl = "craft_dl.cli:main"`.
  The local `uv` is 0.5.14, so `uv self update` (or a pinned `.python-version`) may be needed to get a 3.14 interpreter.
- `craft_dl/__main__.py`: enables `python -m craft_dl`.
- `craft_dl/cli.py`: `cyclopts` app with a typed `download` command registered as `default=True`, so `craft_dl` and `craft_dl download` are synonymous.
  Options are typed parameters (`list[Dl]` with a `Dl` enum of `repo`/`release`, `list[str]` for `--app`), with a small converter that accepts both comma-separated and repeated values.
  Options: `--dl` (`repo`, `release`; comma-separated and repeatable; default all), `--app` (same list semantics; default `*`), `--repo-dir` (default `~/git/storytold/`), `--github-token`.
- `craft_dl/selection.py`: pure functions for parsing the comma-separated/repeated values and for resolving `--app` names against the repo list.
  - `*` (default) means names ending in `craft` with a single word before it, i.e. matching `^[a-z0-9]+craft$` (case-insensitive), so `photocraft` and `artcraft` match but `placeholder-artcraft`, `craft-fonts`, `photocraft-corpus` and `artcraftx` do not; `**` means every repo of the org.
  - A name `photo` tries `photocraft` first (suffix implied if not already ending in `craft`), then falls back to the bare `photo`; an explicit `--app=craft-fonts` tries `craft-fontscraft` first and then resolves to the bare `craft-fonts`, so non-default repos can still be requested by name.
  - Unresolvable names become a reported error, not a crash.
- `craft_dl/github.py`: thin wrapper around `githubkit.GitHub` (async, typed models, built-in pagination): `list_org_repos("storytold")`, `list_releases(repo)`, `get_latest_release(repo)`.
  Asset bytes are streamed with the client's underlying `httpx` session (`browser_download_url`), since the REST models don't cover binary downloads.
- `craft_dl/token.py`: token resolution with the precedence above (runs `gh auth token` via `asyncio.create_subprocess_exec`, tolerating `FileNotFoundError` and non-zero exit).
- `craft_dl/git_ops.py`: thin async wrapper around the `git` binary (`run_git(args, cwd)` returning stdout, raising a typed `GitError` that carries stderr).
  Provides `clone`, `fetch_all`, `list_refs`, `update_ref`, `ref_exists`.
- `craft_dl/backup_refs.py`: builds backup ref names and creates them.
- `craft_dl/releases.py`: `_releases_` folder setup and release downloading.
- `craft_dl/progress.py`: `rich.progress.Progress` with two tasks, an overall bar (repos done / total) and an in-repo bar (steps, and bytes or files during release downloads); log output goes through `rich`'s console so it doesn't tear the bars.
- `craft_dl/report.py`: `ErrorCollector` (repo, step, detail, exception text) plus rendering of the final summary and retry commands.
- `craft_dl/sync.py`: orchestrates the per-repo pipeline.
- `tests/`: one test module per module above.

## Per-repo pipeline (`sync.py`)

Repos are processed one after another, so git output and error reports stay readable.
Within a repo, the `repo` part (clone/fetch + backup refs) and the `release` part (folder setup + releases) are independent tasks: neither requires nor waits for the other, and a failure in one does not skip the other.
Release assets within a repo are downloaded concurrently, bounded by an `asyncio.Semaphore`.
The overall bar advances once per repo, the in-repo bar tracks that repo's steps and downloaded assets.
Every step is wrapped so an exception is recorded in the `ErrorCollector` and the pipeline continues with the next step.

1. **Repo list.**
   Fetch via `GitHubClient`.
   On failure, record the error and fall back to the directories that already exist under `--repo-dir`, filtered by the same `--app` rules (so `git fetch` of existing checkouts still runs).
   Release downloading is skipped in that mode, since there's nothing to ask GitHub for.
2. **Clone or fetch** (`--dl=repo`).
   - Missing `${repo_dir}/${name}`: `git clone https://github.com/storytold/${name}.git`.
   - Directory exists but is not a git repo (e.g. `_releases_` was created first by an independent `--dl=release` run): `git init`, `git remote add origin …`, `git fetch`, and check out the default branch, instead of `git clone`, which would refuse a non-empty directory.
   - Existing: `git fetch --all --tags --force`, which accepts forced pushes and moved tags, deliberately without `--prune` so deleted upstream branches stay recoverable.
3. **Backup refs** (`--dl=repo`, right after step 2, also after a fresh clone).
   Enumerate `refs/remotes/*` (skipping `HEAD`) and `refs/tags/*`.
   For every ref whose commit has no `bak/commit/{sha1}` yet, create:
   - `bak/branch/{name}/{YYYY-MM-DD}/{HH-MM-SS}/{commit}` for a branch, `bak/tag/{name}/{YYYY-MM-DD}/{HH-MM-SS}/{commit}` for a tag (`name` may contain slashes), and
   - `bak/commit/{sha1}`.

   Using the absence of `bak/commit/{sha}` as the "new or changed" test is idempotent and needs no before/after snapshot, so reruns and first clones behave the same, and a force-pushed branch is picked up because its new tip has no backup yet.
   The old tip stays reachable through its earlier `bak/*` refs, which is what makes force pushes recoverable.
   Refs are written as local branches (`refs/heads/bak/...`) via `git update-ref`, so they survive `git fetch` and `git gc`.
   Local `bak/*` branches are excluded from enumeration so backups are never backed up.
   Annotated tags are peeled (`<tag>^{commit}`) to get the commit sha.
   Timestamp uses the time of the backup run, in UTC.
4. **`_releases_` setup** (`--dl=release`, does not require a checkout).
   `Path.mkdir(parents=True, exist_ok=True)` for `${repo}/_releases_`, then write `.gitignore` containing just `*` if it doesn't exist yet.
5. **Releases** (`--dl=release`).
   For each release from the API into `_releases_/${tag_name}/`:
   - Write `README.md` as `# {release name}` followed by the release notes body; always rewritten, because notes can be edited upstream.
   - Download every entry of `assets` (GitHub's auto-generated source archives are not in `assets`, so they are naturally excluded).
     Skip an asset if a file of the same name and size already exists, otherwise stream to `name.part` and rename on success, so a failed download never leaves a truncated file behind.
   - Tag names are validated against `..` and absolute paths before being used as a path.
   - Drafts and prereleases are included when the API returns them.
   - If listing all releases fails (e.g. pagination error, rate limit), fall back to `get_latest_release` so at least the newest release is saved, and record the listing error.
   - One failed asset is recorded and the other assets of the release and the other releases proceed.

## Error reporting and retries

`ErrorCollector` stores `(repo, step, detail)`.
At the end, print a grouped summary, and then one retry command per failing repo covering only the steps that failed, e.g.
`uv run craft_dl download --dl=release --app=photocraft --app=cadcraft`.
Repo-list or unresolved-name failures print the plain `uv run craft_dl` command.
Exit code is `0` when there were no errors and `1` otherwise, so cron/CI can notice partial failures.
Output uses `logging` (not bare prints) for progress, and `print` only for the final summary.

## Tests (pytest, `tests/`)

- `selection`: comma/repeat parsing, `*` vs `**` (assert `placeholder-artcraft`, `craft-fonts` are excluded by `*` but resolvable by name), suffix-implied-then-bare fallback (`photo` -> `photocraft`, `craft-fonts`, unknown names).
- `token`: precedence flag > gh > env > none, with `gh` missing and failing.
- `backup_refs`: ref name construction (slashes in names, UTC time formatting) and idempotence, using a real temporary git repo; simulate a force push and assert the old tip stays reachable via `bak/*`.
- `git_ops` / `sync`: clone-vs-fetch decision using a local bare repo as the "remote"; one failing step does not stop the others.
- `releases`: `respx`-mocked API (githubkit runs on `httpx`) and downloads, covering `.gitignore` creation, README content, skip-existing, `.part` cleanup on failure.
- `report`: retry command generation.
- `cli`: `--dl`/`--app` comma and repeat forms, default command with no subcommand.
- `releases` fallback: listing failure falls back to latest; `--dl=release` works without a checkout and a later `--dl=repo` still succeeds on the pre-created directory.

## Docs

Update `README.md` with usage examples (`--dl`, `--app`, `--repo-dir`, `--github-token`, `*` and `**`, the retry flow), and the `bak/*` ref layout with a short "recover a force-pushed branch" example.

## Verification

1. `uv sync && uv run pytest` passes.
2. `uv run craft_dl --repo-dir=$(mktemp -d) --app=photo`: clones `photocraft`, shows `bak/branch/…`, `bak/tag/…`, `bak/commit/…` in `git branch --list 'bak/*'`, creates `_releases_/.gitignore` containing `*`, and `_releases_/v0.5.0/` holds `README.md` (`# PhotoCraft v0.5.0`), the assets and `SHA256SUMS.txt`.
3. Rerun the same command: no new downloads, no duplicate backup refs.
4. In the clone, rewind a branch on the local copy of the remote (or use the test fixture) and rerun: the old tip remains reachable via a `bak/*` ref.
5. Failure paths: run with no network (or a bogus `--github-token` plus blocked API) and confirm existing checkouts still get `git fetch`, the summary lists the errors, the printed retry command works, and the exit code is `1`.
6. `uv run craft_dl --app='**' --dl=repo` iterates every `storytold` repo.

## Notes

- The default `*` follows the user's `*craft` rule: currently it selects `artcraft`, `photocraft`, `pdfcraft`, `filmcraft`, `vectorcraft`, `lightcraft`, `designcraft`, `effectcraft`, `gridcraft`, `cadcraft`, `deckcraft`, `soundcraft` and skips `craft-fonts`, `placeholder-artcraft`, `photocraft-corpus`, `artcraftx`.
- Unauthenticated GitHub API is limited to 60 requests/hour, which a full run of releases per repo can approach, hence the token support.
