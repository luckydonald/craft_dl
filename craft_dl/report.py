from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from craft_dl.chain import Selector, selector_args
from craft_dl.models import Dl


@dataclass(frozen=True)
class Failure:
    repo: str | None
    dl: Dl | None
    step: str
    detail: str
# end class


@dataclass
class ErrorCollector:
    failures: list[Failure] = field(default_factory=list)

    def add(self, repo: str | None, dl: Dl | None, step: str, error: BaseException | str) -> None:
        detail = error if isinstance(error, str) else f"{type(error).__name__}: {error}"
        self.failures.append(Failure(repo=repo, dl=dl, step=step, detail=detail))
    # end def

    def retry_commands(self, selectors: Mapping[str, Sequence[Selector]] | None = None, extra_args: Sequence[str] = ()) -> list[str]:
        """One command per failed `--dl` kind, listing only the repos that failed in it.

        Release retries keep the repo's own filters so a retry never widens the download; repos without filters come last,
        because every filter option applies to all the `--app` values before it.
        """
        selectors = selectors or {}
        commands: list[str] = []
        for dl in Dl:
            repos: list[str] = []
            for failure in self.failures:
                if failure.dl == dl and failure.repo is not None and failure.repo not in repos:
                    repos.append(failure.repo)
                # end if
            # end for
            if repos:
                filtered = [repo for repo in repos if dl is Dl.release and selectors.get(repo)]
                args: list[str] = []
                for repo in filtered:
                    args.extend(selector_args(repo, selectors[repo]))
                # end for
                args.extend(f"--app={repo}" for repo in repos if repo not in filtered)
                args.extend(extra_args)
                commands.append(" ".join(["uv run craft_dl download", f"--dl={dl.value}", *args]))
            # end if
        # end for
        if any(f.repo is None for f in self.failures):
            commands.append(" ".join(["uv run craft_dl download", *extra_args]))
        # end if
        return commands
    # end def

    def render(self, selectors: Mapping[str, Sequence[Selector]] | None = None, extra_args: Sequence[str] = ()) -> str:
        if not self.failures:
            return "All done, no errors."
        # end if
        lines = [f"{len(self.failures)} error(s):"]
        for failure in self.failures:
            where = failure.repo or "(repository list)"
            lines.append(f"  - {where} [{failure.step}]: {failure.detail}")
        # end for
        lines.append("")
        lines.append("Retry just the failed parts with:")
        lines.extend(f"  {command}" for command in self.retry_commands(selectors, extra_args))
        return "\n".join(lines)
    # end def
# end class
