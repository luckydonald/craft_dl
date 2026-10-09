This is a newly bootstrapped repo, using `base/base` to get started quickly. Here's what we'll gonna build,
please follow /commit-with-lplp-style and /code-style along the way.
Also, if not done already, please enable /plan mode for this.

To run it in the agent you may use `@ai/initial.md`.

# Initial plan
Downloader for the [`*craft` repositories](https://github.com/orgs/storytold/repositories).
Modern python.

## What it does:

1. grab all repositories from `storytold` on github.
2. Filter for those containing `craft` in it's name.
3. For each:
   1. Check if already checked out (`~/git/storytold/${REPO_NAME}`)
      - (a) Not checked out: `git clone` it there.
      - (b) Exists: `git fetch --all`, including forced pushes (see **3.2** to recover previous one).
   2. backuping all new (or changed) branches/tags with:
      - `bak/{branch,tag}/{name/with/possibly/slashes}/{YYYY-DD-MM}`
      - `bak/commit/{sha1}`
      - this makes force pushed updates easily recoverable.
   3. Check if `~/git/storytold/${REPO_NAME}/_releases_/.gitignore` exists.
      - (a) Does not exist:
            1. Create that `_releases_` folder (`--recursive`, not failing if exists)
            2. Write `.gitignore` into it, with just `*` (ignore everything in that folder).
      - (b) Does exists: nothing to do
   4. Pull all current/missing releases into `~/git/storytold/${REPO_NAME}/_releases_/${RELEASE_TAG}`:
      - Release notes written into `README.md`
      - Download every Non-Source code download of that release (source code is in the git already)
      - E.g. `https://github.com/storytold/photocraft/releases/tag/v0.5.0` would contain `README.md` with headline `PhotoCraft v0.5.0`, and the release notes, `photocraft-0.5.0-freebsd-x86_64.tar.gz`, `photocraft-0.5.0-linux-aarch64.AppImage`, … `photocraft-0.5.0-windows-arm64-portable.zip`, …, `photocraft-cli-0.5.0-macos-universal.zip, …, `photocraft-web-0.5.0.zip`, `SHA256SUMS.txt`.
   - Each one of those (sub-) steps shall fail gracefully, and continue with every other remaining steps.
     - the goal is to backup as thoroughly, so if one download fails, rather store the others still, and report all errors at the end instead. Same with git pull etc.
     - _Do save_ (heh), be sorry.
     - Again, failure is alright and should be expected at every step.
       - Provide instructions (and CLI ways) to retries those specific failures directly
         - i.e. `uv run craft_dl download --dl=repo,release --app=photo,craft-fonts,cad`
           - `craft_dl download` and `craft_dl` are synonymous, the `download` is the default subcommand.
           - For `app`, `craft` suffix is implied if not contained, but if not found, try without.
           - If `--dl` or `--app` is ommited, using all (the full list) is implied.
           - instead of comma-separated, you can also repeat those arguments, e.g. `--app=sound --app=word`.
           - allow the special `--app='*'` (default) downloading all found matching repos (as described above)
           - allow the special `--app='**'` which downloads all `storytold/*` repos, not only those with `craft` in it's name.
       - even if the repo list can't be fetched, still run normal git fetch in the existing repositiories.
       - allow `--repo-dir`, where the default is `${HOME}/git/storytold/` as specified above.
4. ???
5. Done
 
