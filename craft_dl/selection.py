import re
from collections.abc import Iterable, Sequence

DEFAULT_PATTERN = re.compile(r"^[a-z0-9]+craft$", re.IGNORECASE)
ALL_DEFAULT = "*"
ALL_REPOS = "**"
SUFFIX = "craft"


def split_values(values: Sequence[str]) -> list[str]:
    """Accept both repeated (`--app=a --app=b`) and comma-separated (`--app=a,b`) values."""
    result: list[str] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part and part not in result:
                result.append(part)
            # end if
        # end for
    # end for
    return result
# end def


def candidates(name: str) -> list[str]:
    """`photo` -> `photocraft`, `photo`; names already ending in `craft` are used as is."""
    if name.lower().endswith(SUFFIX):
        return [name]
    # end if
    return [name + SUFFIX, name]
# end def


def resolve_apps(apps: Sequence[str], available: Iterable[str]) -> tuple[list[str], list[str]]:
    """Resolve `--app` values against the known repository names.

    Returns `(resolved repo names, unresolved app values)`.
    """
    names = list(available)
    by_lower = {name.lower(): name for name in names}
    resolved: list[str] = []
    unresolved: list[str] = []

    def add(name: str) -> None:
        if name not in resolved:
            resolved.append(name)
        # end if
    # end def

    for app in apps or [ALL_DEFAULT]:
        if app == ALL_REPOS:
            for name in names:
                add(name)
            # end for
            continue
        # end if
        if app == ALL_DEFAULT:
            for name in names:
                if DEFAULT_PATTERN.match(name):
                    add(name)
                # end if
            # end for
            continue
        # end if
        for candidate in candidates(app):
            found = by_lower.get(candidate.lower())
            if found is not None:
                add(found)
                break
            # end if
        else:
            unresolved.append(app)
        # end for
    # end for
    return resolved, unresolved
# end def
