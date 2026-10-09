from dataclasses import dataclass, field

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

    def retry_commands(self) -> list[str]:
        """One command per failed `--dl` kind, listing only the repos that failed in it."""
        commands: list[str] = []
        for dl in Dl:
            repos: list[str] = []
            for failure in self.failures:
                if failure.dl == dl and failure.repo is not None and failure.repo not in repos:
                    repos.append(failure.repo)
                # end if
            # end for
            if repos:
                apps = " ".join(f"--app={repo}" for repo in repos)
                commands.append(f"uv run craft_dl download --dl={dl.value} {apps}")
            # end if
        # end for
        if any(f.repo is None for f in self.failures):
            commands.append("uv run craft_dl download")
        # end if
        return commands
    # end def

    def render(self) -> str:
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
        lines.extend(f"  {command}" for command in self.retry_commands())
        return "\n".join(lines)
    # end def
# end class
