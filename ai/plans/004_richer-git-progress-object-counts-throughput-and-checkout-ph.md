# Richer git progress: object counts, throughput and checkout phase

**Commit style:** Skill `/commit-with-lplp-style` is active, and `/code-style` rules apply (see `ai/skills/code-style/references/py.md` and `md.md`).

## Context

Commit `304d71a` made the in-repo bar move during `git clone`/`git fetch` by parsing the percentages of git's `--progress` output on stderr.
It only uses the percent and shows no detail, so the bar gives no hint what git is doing, and phases without a percentage (`Enumerating objects: 866, done.`) or after the transfer (`Updating files: 45% (9/20)` during a clone, or the `git checkout -B` in `init_and_fetch`) are invisible.
The user asked to use the counts git already prints (objects, files, indexes: `XXX/YYY`) and whether a porcelain/machine-readable progress mode exists.

Findings on the porcelain question (git 2.50.1, `git help fetch`):
- `git fetch --porcelain` only formats the ref-update lines on stdout; it has no progress output.
- `--progress` merely forces the normal human progress on stderr, which is the only live progress source; trace2 only reports totals when a phase ends.
- So the right move is to parse the stderr progress lines fully, not to look for another mode.

## Design

Parse each progress line into a small structure and show it on the bar, while keeping one monotonic overall fraction.

- `craft_dl/git_ops.py`:
  - Replace `fraction_of` by `parse_progress(line) -> GitProgress | None`, a frozen dataclass `(phase, percent, done, total, rate)`.
    It matches `Phase: NN% (done/total)` for `Counting objects`, `Compressing objects`, `Receiving objects`, `Resolving deltas`, `Updating files` (older git: `Checking out files`), and the count-only `Enumerating objects: N`.
    The optional tail `, 4.45 MiB | 3.92 MiB/s` becomes `rate` (`3.92 MiB/s`); `remote: ` prefixes are accepted.
  - `PHASES` maps phase to its share of the whole run (counting 0–5%, compressing 5–10%, receiving 10–70%, resolving 70–90%, updating files 90–100%), so `fraction` stays monotonic across the phases of a clone.
    A fetch never reaches `Updating files`, so its callback also reports 1.0 when the process ends; the existing `best` guard keeps the value monotonic.
  - `ProgressCallback` becomes `Callable[[float, str], None]`: the fraction plus a short detail text such as `Receiving objects 120/866 · 3.92 MiB/s`.
  - `init_and_fetch` passes `--progress` to `git checkout -B` and reports its `Updating files` phase through the same callback.
- `craft_dl/progress.py`: `Bars.step_progress(fraction, detail="")` stores the detail in a task field, and a new `TextColumn("{task.fields[detail]}")` shows it right of the time column; `work_done` clears it.
- `craft_dl/backup_refs.py`: the batch callback passes `Creating backup refs 1500/2626` as detail, so that step reads the same way.
- `craft_dl/sync.py`: no change beyond the signature (it already passes `ctx.bars.step_progress`).
- Logging stays as is: finished lines are logged, in-flight updates only drive the bar.
  `Enumerating objects` and `Updating files … done.` finish with `\n`, so they appear in the log too.

## Tests

- `tests/test_git_ops.py`: `parse_progress` on real lines (`Receiving objects:  45% (390/866), 1.20 MiB | 3.92 MiB/s`, `Receiving objects: 100% (866/866), 4.45 MiB | 3.92 MiB/s, done.`, `remote: Counting objects: 100% (71/71), done.`, `Updating files:  45% (9/20)`, `Enumerating objects: 866, done.`, a non-progress line), the monotonic fraction across a full clone transcript fed through `read_stderr`, and the detail texts.
- `test_step_progress_is_partial_then_whole` also asserts the detail field and that `work_done` clears it.
- `tests/test_backup_refs.py`: the progress callback receives increasing fractions and the `x/y` detail.

## Verification

1. `uv run pytest` passes.
2. Check disk first (`df -h .`, it was nearly full), then in a temp dir: `uv run craft_dl --dl=repo --app=gridcraft --repo-dir=$(mktemp -d)` shows the detail text changing through the phases and ends at 100%; running it again (fetch with nothing new) finishes cleanly without a stuck bar.
3. An existing non-git directory (`init_and_fetch` path) also shows `Updating files` progress.

## Notes

- No new dependency and no change to what git is asked to do beyond `--progress` on `git checkout -B`.
- Parsing stays tolerant: unknown lines are ignored for the bar and still logged.
