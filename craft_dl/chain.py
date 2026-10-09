from collections.abc import Sequence
from dataclasses import dataclass, field

from craft_dl.assets import split_platform
from craft_dl.selection import ALL_DEFAULT, is_wildcard, split_values

APP, RELEASE, PLATFORM, VARIANT = range(4)
WILDCARD = "*"
OPTIONS = {"--app": APP, "--release": RELEASE, "--platform": PLATFORM, "--variant": VARIANT}


class ChainError(ValueError):
    """The filter options cannot be turned into an unambiguous chain."""
# end class


@dataclass(frozen=True)
class Selector:
    """One group of the chain: assets are taken if the release matches one of `releases`, and the platform one of `platforms`, and any variant fits.

    An empty tuple means "no restriction" for that level.
    """

    apps: tuple[str, ...] = ()
    releases: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    variants: tuple[str, ...] = ()

    @property
    def has_filters(self) -> bool:
        return bool(self.releases or self.platforms or self.variants)
    # end def
# end class


@dataclass
class Builder:
    """Mutable state of the group being built; each level resets the levels below it."""

    levels: list[list[str]] = field(default_factory=lambda: [[], [], [], []])
    done: list[Selector] = field(default_factory=list)

    def deeper_set(self, level: int) -> bool:
        return any(self.levels[deeper] for deeper in range(level + 1, len(self.levels)))
    # end def

    def flush(self) -> None:
        if any(self.levels):
            apps, releases, platforms, variants = (tuple(values) for values in self.levels)
            self.done.append(Selector(apps, releases, platforms, variants))
        # end if
    # end def

    def apply(self, level: int, values: Sequence[str], wildcard: bool = False) -> None:
        """Repeating a level extends it, unless a lower level is already set: then that group is finished and a new one starts.

        A second `--platform` always starts a new group, since it resets the variants. A wildcard (`*`, `all`) lifts the restriction of its level.
        """
        starts_new = self.deeper_set(level) or (level == PLATFORM or wildcard) and bool(self.levels[level])
        if starts_new:
            self.flush()
            self.levels[level] = []
            for deeper in range(level + 1, len(self.levels)):
                self.levels[deeper] = []
            # end for
        # end if
        for value in () if wildcard else values:
            if value not in self.levels[level]:
                self.levels[level].append(value)
            # end if
        # end for
    # end def
# end class


def option_values(tokens: Sequence[str]) -> list[tuple[int, list[str]]]:
    """Pick `--app/--release/--platform/--variant` out of the raw arguments, in order, in both `--opt=value` and `--opt value` form."""
    found: list[tuple[int, list[str]]] = []
    index = 0
    while index < len(tokens):
        name, equals, value = tokens[index].partition("=")
        level = OPTIONS.get(name)
        if level is not None:
            if not equals:
                index += 1
                if index >= len(tokens) or tokens[index].startswith("--"):
                    raise ChainError(f"{name} needs a value")
                # end if
                value = tokens[index]
            # end if
            found.append((level, split_values([value])))
        # end if
        index += 1
    # end while
    return found
# end def


def expand_platforms(values: Sequence[str]) -> list[tuple[int, list[str]]]:
    """`--platform=win-x64,mac` -> `--platform=win --variant=x64 --platform=mac`; plain platforms stay one group."""
    operations: list[tuple[int, list[str]]] = []
    plain: list[str] = []
    for value in values:
        if is_wildcard(value):
            return [(PLATFORM, [WILDCARD])]
        # end if
        try:
            platform, variant = split_platform(value)
        except ValueError as error:
            raise ChainError(str(error)) from error
        # end try
        if variant is None:
            plain.append(platform)
            continue
        # end if
        if plain:
            operations.append((PLATFORM, plain))
            plain = []
        # end if
        operations.append((PLATFORM, [platform]))
        operations.append((VARIANT, [variant]))
    # end for
    if plain:
        operations.append((PLATFORM, plain))
    # end if
    return operations
# end def


def parse_chain(tokens: Sequence[str]) -> list[Selector]:
    """Build the per-app filter groups from the raw arguments; the scope order is `app > release > platform > variant`."""
    builder = Builder()
    for level, values in option_values(tokens):
        operations = expand_platforms(values) if level == PLATFORM else [(level, [value.lower() for value in values] if level != APP else values)]
        for operation_level, operation_values in operations:
            wildcard = operation_level != APP and any(is_wildcard(value) for value in operation_values)
            builder.apply(operation_level, operation_values, wildcard)
        # end for
    # end for
    builder.flush()
    selectors = builder.done
    if any(selector.apps for selector in selectors):
        if any(not selector.apps for selector in selectors):
            raise ChainError("--release/--platform/--variant before the first --app are ambiguous, put them after an --app")
        # end if
        return selectors
    # end if
    return [Selector((ALL_DEFAULT,), s.releases, s.platforms, s.variants) for s in selectors]
# end def


def chain_apps(selectors: Sequence[Selector]) -> list[str]:
    """All distinct `--app` values of the chain, `*` if there is none."""
    apps = split_values([app for selector in selectors for app in selector.apps])
    return apps or [ALL_DEFAULT]
# end def


def selector_args(repo: str, selectors: Sequence[Selector]) -> list[str]:
    """CLI arguments that select just `repo` with the same filters, for retry commands."""
    args: list[str] = []
    for selector in selectors:
        args.append(f"--app={repo}")
        for option, values in (("release", selector.releases), ("platform", selector.platforms), ("variant", selector.variants)):
            if values:
                args.append(f"--{option}={','.join(values)}")
            # end if
        # end for
    # end for
    return args
# end def
