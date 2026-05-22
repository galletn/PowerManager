"""Plan-string assertion helpers for the test suite.

Leading underscore signals to pytest that this is a non-test module (it is
imported by conftest and tests, not collected for test discovery).

`assert_plan_contains` and `assert_plan_no_match` use a word-boundary regex
so that a pattern like 'SOLAR START' will NOT match a hypothetical superset
plan entry like 'SOLAR STARTUP' or 'SOLAR STARTSKIPPED'. This is stricter
than `pattern in entry`, which is what these helpers exist to replace.
"""

import re


def _compile_word_boundary(pattern: str) -> re.Pattern[str]:
    """Compile `pattern` with no-word-char-adjacent anchors.

    Uses `(?<!\\w)` / `(?!\\w)` instead of `\\b` so patterns ending in a
    non-word character (e.g. `'PAUSE (insufficient solar)'` ending in `)`)
    still anchor correctly. A plain trailing `\\b` requires a word/non-word
    transition at the right edge, which is absent when the pattern itself
    already ends in a non-word character.

    Raises ValueError on empty pattern: an empty pattern would match every
    position with non-word neighbors on both sides (always true between
    e.g. ': ' or end-of-string), so `assert_plan_contains(plan, '')` would
    silently pass on every non-trivial plan — a footgun.
    """
    if not pattern:
        raise ValueError("pattern must be a non-empty string")
    return re.compile(r'(?<!\w)' + re.escape(pattern) + r'(?!\w)')


def assert_plan_contains(plan: list[str], pattern: str, *, msg: str = "") -> None:
    """Assert at least one plan entry contains `pattern` as a word-boundary match.

    Tighter than `pattern in entry` because the boundary assertions prevent
    matching superset entries like 'SOLAR STARTUP' when looking for 'SOLAR
    START'.

    Use for POSITIVE witness: "this plan WAS emitted".
    """
    regex = _compile_word_boundary(pattern)
    for entry in plan:
        if regex.search(entry):
            return
    detail = f" ({msg})" if msg else ""
    raise AssertionError(
        f"Expected plan to contain pattern {pattern!r}{detail}; got plan={plan!r}"
    )


def assert_plan_no_match(plan: list[str], pattern: str, *, msg: str = "") -> None:
    """Assert NO plan entry contains `pattern` (word-boundary anchored).

    Use for NEGATIVE witness: "this plan was NOT emitted".
    """
    regex = _compile_word_boundary(pattern)
    for entry in plan:
        if regex.search(entry):
            detail = f" ({msg})" if msg else ""
            raise AssertionError(
                f"Expected plan to NOT contain pattern {pattern!r}{detail}; "
                f"matched entry={entry!r}; full plan={plan!r}"
            )
