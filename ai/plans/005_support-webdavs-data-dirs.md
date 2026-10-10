# Support `webdavs://` data dirs

## Context

`--repo-dir` accepts local paths and, since c947729, `smb://…` (mounted via Finder first).
The request is to accept `webdavs://user:escaped%20password@domain.example.com/some/path` too, **without mounting**: read and write the server directly, asynchronously, using HTTP range requests where seeking helps.
Decisions from the user: for a webdavs dir only the release assets are stored there (git sync is skipped with a warning), and `_releases_/latest` becomes a `latest.txt` file holding the tag.

## Approach

Introduce a small async storage layer, so `assets.py` and `sync.py` stop touching `pathlib` directly for release data.
WebDAV is spoken with the `httpx.AsyncClient` that is already a dependency (via githubkit); no new package.

### `craft_dl/store.py` (new)

A `Store` protocol, all methods `async`, paths relative to the store root (posix strings):

- `exists_size(path) -> int | None` (size or `None` if missing).
- `mkdirs(path)`.
- `write_text(path, text)`.
- `write_stream(path, chunks: AsyncIterator[bytes], size) -> None`, atomic: no truncated file at the final name.
- `read(path, start=0, end=None) -> bytes`, a ranged read.
- `set_latest(tag)` (see below).

`LocalStore(root: Path)` wraps today's behavior: `.part` file then `replace`, the symlink `latest` logic from `link_latest` (`craft_dl/assets.py:41`), and the `release_dir` path-escape check (`assets.py:32`).
File writes stay synchronous inside the async methods, as they are now.

`WebdavStore(base_url, user, password, client)` in `craft_dl/webdav.py`:

- `parse(path) -> WebdavLocation(base_url, user, password)`.
  `Path("webdavs://x")` collapses to `webdavs:/x`, so `has_protocol` matches `webdav:/` and `webdavs:/` like `smb.has_protocol` (`craft_dl/smb.py:48`), then re-expands before `urllib.parse.urlsplit`.
  `unquote` user and password; `base_url` is `https://host[:port]/path` (`webdav` → `http`) with no credentials in it.
  `WebdavError` for a missing host.
- Credentials go in `httpx.BasicAuth` on a dedicated client, never in a URL, argv or log line; error messages are built from `base_url`.
  The existing GitHub client (`ctx.http`) must not receive these credentials, so the WebDAV client is separate and created/closed in `cli.download_async` (`cli.py:60-69`).
- `exists_size`: `PROPFIND` with `Depth: 0` and a `getcontentlength` body, parse the multistatus with `xml.etree.ElementTree`; 404 → `None`.
  If a server rejects PROPFIND, fall back to `HEAD`.
- `mkdirs`: `MKCOL` per path segment (`405` = already exists is fine, `409` means a parent is missing, so create parents top-down).
- `write_text`: `PUT` with the body.
- `write_stream`: `PUT` to `<name>.part` with an async-generator body and an explicit `Content-Length`, then `MOVE` to the final name with `Overwrite: T`, and `DELETE` the `.part` on failure.
  The chunk iterator is the GitHub download stream, so the file is relayed without touching local disk and the progress `FileTracker` advances per chunk exactly as it does today.
- `read(path, start, end)`: `GET` with `Range: bytes=start-end`; expect `206`; if the server answers `200` (no range support) slice the body or raise a clear error.
  This is what makes seeking possible; the skip check stays size-based, so nothing else needs it yet.
- `set_latest(tag)`: `write_text("_releases_/latest.txt", tag + "\n")`.
- Redirects off by default in httpx, which is what we want for `PUT`; allow them only if a real server needs it.

### Wiring

- `assets.py`: `ensure_releases_dir`, `write_readme`, `download_asset`, `sync_release` take a `Store` instead of a `Path`.
  `download_asset` does `store.exists_size` for the skip check, then `store.write_stream(path, response.aiter_bytes(), asset.size)`, wrapped so the tracker advances per chunk.
  Exceptions caught in `sync_release` (`assets.py:135`) gain `WebdavError`; httpx errors from the WebDAV side are `httpx.HTTPError` already.
- `sync.py`: `Context.repo_dir: Path` (line 31) becomes `store_for(name)`/a `Store` factory.
  `sync_releases` (line 161) builds `store.sub(name)` and calls `set_latest(listing.latest_tag)` instead of `link_latest`.
  `sync_repo` (line 194) skips the `Dl.repo` step for a non-local store with `logger.warning`, and the steps count (line 196) must follow.
  `local_repo_names` (line 52, offline fallback) is local-only: with a webdav dir the fallback has no checkouts to list, so it returns `[]` and logs that.
- `cli.py:99-108`: add a branch next to the smb one: `webdav.has_protocol(repo_dir)` → `webdav.parse`, else the existing smb/local path.
  Update the `--repo-dir` help (`cli.py:89`) and `README.md:31` (scheme, `%`-escaping of user/password, releases only, `latest.txt`).

## Tests

New `tests/test_webdav.py` using `respx` (already a dev dependency) to fake the server:

- `has_protocol` / `parse`: unescaping `escaped%20password`, `%40` and `%3A` in credentials, port, empty path, invalid input; `base_url` has no credentials.
- `WebdavStore` against respx routes: PROPFIND size parsing and 404, MKCOL parent ordering and 405 tolerance, the `.part` PUT then MOVE sequence, `.part` DELETE on a failing source stream, ranged `read` (206 and the 200 fallback), `Authorization: Basic` header present.
- `download_asset` with a `WebdavStore`: skips when the size matches, uploads otherwise.

Existing `tests/` for assets/sync keep passing through `LocalStore`; adjust them for the new signatures.

## Verification

- `pytest`.
- Manual against a real server: `craft_dl download --repo-dir 'webdavs://user:pass%20word@host/some/path'`, confirm `_releases_/<tag>/` files and `latest.txt` appear, a second run skips them, git is skipped with a warning, and the password is absent from logs.
