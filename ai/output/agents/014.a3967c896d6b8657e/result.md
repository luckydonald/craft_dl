Commit c947729 only covers a macOS `open`-based `smb://` mount. The code has no credential unescaping, no unmount or cleanup, and no Linux or other platform handling.

## Main file: `/Users/user/Documents/programming/Python/craft_dl/craft_dl/smb.py` (113 lines, new in c947729)

- **Constants (lines 11-15):**
  ```python
  OPEN = "/usr/bin/open"; MOUNT = "/sbin/mount"; VOLUMES = Path("/Volumes")
  SCHEME = "smb:"; TIMEOUT_SECONDS = 30
  ```
  These are hard-coded macOS paths. There is no `sys.platform` check anywhere.
- **`SmbError(Exception)` (line 18):** raised for every parse, mount and timeout failure.
- **`SmbPath` frozen dataclass (lines 23-45):** fields are `server`, `share` and `subpath`.
  - `url` (line 33) is `f"smb://{self.server}/{quote(self.share)}"`. It percent-encodes the share name only.
  - `volume` (line 38) is `VOLUMES / share`.
  - `local_path` (line 43) is `volume / subpath`, or just `volume` when there is no subpath.
- **`has_protocol(path)` (lines 48-51):** `str(path).lower().startswith("smb:/")`. It matches `smb:/` because `Path("smb://x")` collapses to `smb:/x`.
- **`parse(path)` (lines 54-64):** strips `smb:` and the leading slashes, then partitions on `/` into server, share and subpath.
  - The server string is kept verbatim, so `user@host` stays in it and is never split into user and password.
  - Nothing is unescaped, and there is no `urllib.parse.urlparse` or `unquote`.
  - It raises `SmbError` when the server or share is missing.
- **`mounted_volumes()` (line 68):** runs `/sbin/mount` and returns its stdout.
- **`is_mounted(volume)` (line 73):** checks for `f"on {volume} "` in that output.
- **`open_share(url)` (lines 79-85):** runs `[OPEN, url]` with `check=True`. It wraps `OSError` and `CalledProcessError` into `SmbError`.
- **`wait_until(cond, what, timeout)` (lines 88-98):** polls once per second and raises `SmbError("timed out after Ns waiting for …")`.
- **`mount(path, timeout=30)` (lines 101-112):**
  - It parses the path.
  - If the volume is not mounted, it calls `open_share(target.url)` and waits for `is_mounted`. Otherwise it logs "already mounted".
  - It then waits for `target.local_path.is_dir`, and returns `target.local_path`.

## Where the mounted path is used: `/Users/user/Documents/programming/Python/craft_dl/craft_dl/cli.py`

- Line 12: `from craft_dl import smb`
- Line 27: `DEFAULT_REPO_DIR = Path("~/git/storytold/")`
- Line 89: the `--repo-dir` option has the help text "`smb://<server>/<mount>/<dir>` is mounted first (macOS)."
- Lines 99-108, in `download()`:
  ```python
  console = setup_logging()
  repo_dir = repo_dir.expanduser()
  if smb.has_protocol(repo_dir):
      try: repo_dir = smb.mount(repo_dir)
      except smb.SmbError as error: raise SystemExit(str(error)) from error
  return asyncio.run(download_async(..., repo_dir, ...))
  ```
  Logging is set up before the mount, so the mount steps appear in the log.
- Line 60 and line 69: `download_async(..., repo_dir, ...)` puts `repo_dir` into `Context(repo_dir=repo_dir, ...)`.
- `/Users/user/Documents/programming/Python/craft_dl/craft_dl/sync.py`:
  - Line 31 declares `repo_dir: Path` on the context.
  - Lines 52-56, `local_repo_names()`, list the checkouts in the directory.
  - Line 61 builds `ctx.repo_dir / name`.
  - Line 164 builds `ensure_releases_dir(ctx.repo_dir / name)`.
  - Lines 219-221 are the local-checkout fallback.

## Cleanup and unmount

None exists. A grep for `unmount`, `umount`, `diskutil`, `unquote`, `password` and `webdav` across `craft_dl/` and `README.md` finds nothing. The share stays mounted after the run.

## Docs and config

- `README.md` line 31, under `--repo-dir`: "An `smb://{ServerName}._smb._tcp.local/{Mount}/{dir1/dir2}` path is mounted first (macOS, `open smb://…`, waits up to 30 s) and then used as `/Volumes/{Mount}/{dir1/dir2}`."
- `ai/query.md` lines 195-199 hold the original request and a follow-up. The follow-up reports the Finder error "There was a problem connecting to the server "nohost"" when a fake share was tried.
- There is no `.env` or `.env.example`. The only env-like entry is `.venv`.

## Tests: `/Users/user/Documents/programming/Python/craft_dl/tests/test_smb.py` (55 lines)

- Lines 8-13 test `has_protocol`. They check that `Path("smb://…")` becomes `smb:/…`, that the string form works, and that non-smb paths return False.
- Lines 16-22 test `parse`:
  - `SmbPath("GoldenOak._smb._tcp.local","Shed","dir1/dir2")` is the expected result.
  - `.url` is checked.
  - `smb://user@host/My Share` gives `smb://user@host/My%20Share`.
  - `local_path` is `/Volumes/Shed`.
- Lines 25-28 are parametrized invalid inputs: `smb://host`, `smb://host/`, `smb:///share` and `/Volumes/x`. Each must raise `SmbError`.
- Lines 31-45 test the mount flow. They monkeypatch `VOLUMES`, `open_share`, `mounted_volumes` and `time.sleep`. They check that `open` is called once and is skipped on the second call because the share is already mounted.
- Lines 48-55 test that an unmounted share with a 3 s timeout raises `SmbError` with "timed out".

## Other findings

- There is a stray untracked directory, `/Users/user/Documents/programming/Python/craft_dl/smb:/`, at the repo root. It is not gitignored, and `git status --short smb:` printed nothing, so it may be empty or ignored by another rule.
  - Inside it is `smb:/GoldenOak._smb._tcp.local/Shed/Install/macOS X/.../repos`.
  - It looks like earlier runs treated the `smb:/…` path as a local relative path and created directories. Check whether it is tracked or should be added to `.gitignore`.
- To support credentials such as `smb://user:p%40ss@host/share` or `webdavs://`, the places to change are:
  - `SmbPath`: add user and password fields.
  - `parse` (lines 54-64): split off the `user:pass@` part and call `unquote` on both. At the moment `user@host` stays inside `server`.
  - `url` (line 33): re-quote the credentials correctly.
  - `has_protocol` (line 50): `smb:` is the only scheme it accepts.
  - `mount` and `open_share`: platform branches, since `/usr/bin/open` and `/Volumes` are macOS only. Linux would need `mount -t cifs` or `gio mount`.
  - `cli.download`: unmount in a `finally` if cleanup is wanted.