# Support `webdavs://` data dirs

## Context

`--repo-dir` already accepts `smb://<server>/<mount>/<dir>`, which `craft_dl/smb.py` mounts through macOS Finder (`open smb://…`) before the downloader uses it (commit c947729).
The request is to accept `webdavs://user:escaped%20password@domain.example.com/some/path` as well, with the credentials percent-escaped in the URL.
Differences from SMB: the URL carries credentials, there is no share/subpath split (the whole URL path is the directory), and Finder gives no predictable `/Volumes/<name>`.

## Approach

Add `craft_dl/webdav.py`, parallel to `smb.py`, and dispatch to it from `cli.download`.
Mount with `/sbin/mount_webdav` onto a mount point we choose, so the resulting local path is deterministic.

- `has_protocol(path)`: matches `webdav:/` and `webdavs:/` (case-insensitive), because `Path("webdavs://x")` collapses to `webdavs:/x`, same as in `smb.has_protocol` (`craft_dl/smb.py:48`).
- `parse(path)` returns a frozen `WebdavPath(scheme, user, password, host, port, path)`.
  Use `urllib.parse.urlsplit` on the re-expanded `scheme://…` string, and `unquote` the username and password.
  Raise `WebdavError` when host is missing.
- `WebdavPath.url` rebuilds `https://host[:port]/path` (`webdavs` → `https`, `webdav` → `http`) without credentials, so they never show up in `ps` or logs.
- `mount_point`: a user-owned directory, e.g. `~/.cache/craft_dl/webdav/<host>-<short hash of url+user>`, created with `mkdir(parents=True, exist_ok=True)`.
  `/Volumes` is root-owned, so `smb.VOLUMES` is not reusable here.
- `mount(path, timeout)`:
  - Skip if `smb.is_mounted(mount_point)` already says so (reuse `mounted_volumes` / `is_mounted` from `smb.py`, moving them to a small shared helper only if the import looks awkward).
  - Otherwise run `mount_webdav -i <url> <mount_point>` and feed `user\npassword\n` on stdin, so the password is never in argv.
  - Reuse `smb.wait_until` for the mount check, and return `mount_point`.
  - Wrap `OSError` / `CalledProcessError` into `WebdavError`, with the password redacted from any message.
- Never log the password; log `user@host/path` only.

Wire-up in `craft_dl/cli.py:99-108`: extend the existing `if smb.has_protocol(repo_dir)` into a second branch for `webdav.has_protocol`, with the same `SystemExit(str(error))` handling.
Update the `--repo-dir` help text (`cli.py:89`) and the `README.md:31` paragraph with the new scheme, the escaping rule (`%20`, `%40`, `%3A`, `%2F` in user and password) and the note that the mount lives under `~/.cache/craft_dl/webdav/`.

## Open point to verify first

Whether `mount_webdav -i` reads username and password from a piped stdin (it is documented as interactive).
If it insists on a tty, fall back to `open webdavs://user:pass@host/path` and poll `mounted_volumes()` for a `https://host/path` source line to find the mount point.
Quick manual check against a real WebDAV server before writing the final code.

## Tests

New `tests/test_webdav.py`, modelled on `tests/test_smb.py`:

- `has_protocol` for `Path("webdavs://…")`, the string form, `webdav://`, and a non-match.
- `parse` unescapes `user:escaped%20password` into `escaped password`, handles a port, an empty path, and `@` / `:` encoded in the password.
- Invalid inputs (`webdavs://`, `webdavs:///path`) raise `WebdavError`.
- `url` contains no credentials.
- Mount flow with monkeypatched `subprocess.run`, `mounted_volumes` and `time.sleep`: stdin gets `user\npassword\n`, argv contains no password, second call is skipped when already mounted, timeout raises.

## Verification

- `pytest tests/test_webdav.py tests/test_smb.py`.
- Manual: `craft_dl download --repo-dir 'webdavs://user:pass%20word@host/some/path'` against a real server, confirm the mount appears, the run uses it, and the password is absent from the log and `ps`.
- Note: unlike smb, nothing unmounts afterwards; keep that consistent for now (unmount is not part of this request).
