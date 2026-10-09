# AI query log file

#### General AI development guidelines:
- You may refer to `ai/refrences` for code examples of other plugins or extra documentation provided for this task.
- When writing code, follow these guidelines:
  - Always prefer the early-return pattern to reduce nesting of `if`s, etc.
  - Similarly, prefer `if …` -> `continue`/`return`/`break` early in loops over large nested blocks.
- Language/stack-specific style constraints (Vue/TS frontend, Python backend, …), including test-writing expectations, now live in the `code-style` skill under `ai/skills/code-style/references/` — apply those instead of repeating them here.
- Remember to update the `/CHANGELOG.md` and `/README.md` if existent (including other pre-existing documentation).
- If you want to write Markdown summaries of the task you just did (only if specifically asked for by the user!) write those to `ai/summaries/` folder, and never into the root folder.
  - However, usually you don't need to write Markdown summaries.
- Please prefer to use the read file tool over weird constructs with `cat` etc. Terminal should not be needed for searches most of the time, either.

----

#### Previous user prompts:

❯ Plan [@`ai/initial.md`](./initial.md)

❯ Question answered.
> <details><summary>
>
>> 1. The backup date suffix is written `{YYYY-DD-MM}`. Use that literally or ISO `YYYY-MM-DD`?
>> 2. How should GitHub be accessed (repo list, releases, asset downloads)?
>
> (click to expand)
>
> </summary>
>
>> **Date format** (1/2) <kbd>Single Select</kbd><br>
>> The backup date suffix is written `{YYYY-DD-MM}`. Use that literally or ISO `YYYY-MM-DD`?
> - [ ] 1\. ISO YYYY-MM-DD (Recommended)
>   - _Assume DD-MM was a typo; sorts chronologically._
> - [ ] 2\. Literal YYYY-DD-MM
>   - _Exactly as written in initial.md._
> - [x] 3\. _Type something:_
>   - > Ooops, yes, a typo. Also add time and commit for completeness sake, `…/YYYY-MM-DD/HH-MM-SS/{commit}`
>
>> **GitHub API** (2/2) <kbd>Single Select</kbd><br>
>> How should GitHub be accessed (repo list, releases, asset downloads)?
> - [ ] 1\. httpx + optional GITHUB_TOKEN (Recommended)
>   - _Async, no external CLI dependency; works unauthenticated (60 req/h) and better with a token._
> - [ ] 2\. Shell out to `gh`
>   - _Reuses existing gh auth, but requires gh installed._
> - [x] 3\. _Type something:_
>   - > Both, use `gh`'s creds if available, otherwise env `GITHUB_TOKEN`, but use httpx for single api surface. And `--github-token=…` is overwriting those.
>
> </details>
>

