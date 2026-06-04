"""
Command-line entrypoint for the Skincare Routine Classifier.

Wrapping the pure recommend_skincare_routinefunction in a small CLI
turns the library into an artefact that can be exercised by a Jenkins
smoke-test stage and by a human operator with one command. The CLI is
deliberately thin: argument parsing and JSON I/O only - all business
logic stays in src/component.py where it is unit-tested.

Exit codes
----------
The exit code is meaningful so that a CI pipeline (and any shell script)
can branch on it without parsing stdout:

* 0 - success, routine printed to stdout as JSON
* 2 - the user-supplied profile failed validation
* 3 - the input file could not be read or was not valid JSON

Exit codes are stable; tests assert against them so accidental changes
break the build.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List, Optional, Sequence

from src.component import (
    InvalidProfileError,
    recommend_skincare_routine,
)


# Stable, documented exit codes - referenced by tests
EXIT_OK: int = 0
EXIT_VALIDATION_ERROR: int = 2
EXIT_INPUT_ERROR: int = 3


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser

    Split out so tests can introspect it without invoking sys.exit
    """
    parser = argparse.ArgumentParser(
        prog="skincare-cli",
        description=(
            "Generate a personalised skincare routine from a JSON profile "
            "Reads from a file or stdin; writes JSON to stdout"
        ),
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=None,
        help=(
            "Path to a JSON file containing the user profile. "
            "If omitted, the profile is read from stdin."
        ),
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the JSON output (indent=2).",
    )
    return parser


def _load_profile(path: Optional[Path], stdin_text: str) -> Any:
    """Parse a JSON profile from a file or from stdin.

    Returns the parsed object on success. Raises ValueError (the
    base class of json.JSONDecodeError) on a parse failure or
    OSError on a read failure - both are caught by main and
    mapped to EXIT_INPUT_ERROR
    """
    if path is not None:
        # Path.read_text raises OSError if the file is unreadable,
        # which propagates up to main for a single, consistent
        # exit-code mapping
        return json.loads(path.read_text(encoding="utf-8"))
    # Empty stdin is an input error rather than a silent success
    if not stdin_text.strip():
        raise ValueError("No profile provided on stdin")
    return json.loads(stdin_text)


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    stdin: Optional[Any] = None,
    stdout: Optional[Any] = None,
    stderr: Optional[Any] = None,
) -> int:
    """Run the CLI and return an exit code.

    The function never calls sys.exit directly - it returns the code
    instead so tests can call main([...]) and assert on the return
    value. The thin if __name__ == "__main__" block at the bottom
    is the only place that actually exits the process

    Parameters
    ----------
    argv : sequence of str, optional
        Argument vector. Defaults to sys.argv[1:] when None
    stdin, stdout, stderr : file-like, optional
        Injectable streams for testability. Default to the real
        sys.* streams
    """
    # Resolve I/O lazily so tests can inject io.StringIO
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    stderr = stderr if stderr is not None else sys.stderr

    parser = _build_parser()
    args = parser.parse_args(argv)

    # ---- Load and parse the profile ------------------------------------
    try:
        profile = _load_profile(
            args.input,
            stdin.read() if args.input is None else "",
        )
    except (OSError, ValueError) as exc:
        # OSError covers missing/unreadable files; ValueError covers
        # JSONDecodeError (which inherits from ValueError) and the
        # explicit "empty stdin" case above.
        print(f"input error: {exc}", file=stderr)
        return EXIT_INPUT_ERROR

    # ---- Run the recommender -------------------------------------------
    try:
        result = recommend_skincare_routine(profile)
    except InvalidProfileError as exc:
        # All four custom exception classes inherit from
        # InvalidProfileError, so one catch is sufficient.
        print(f"validation error: {exc}", file=stderr)
        return EXIT_VALIDATION_ERROR

    # ---- Render output --------------------------------------------------
    indent = 2 if args.pretty else None
    json.dump(result, stdout, indent=indent, sort_keys=False)
    # json.dump does not append a newline; do so for shell-friendly
    # behaviour (e.g. $(cli) | jq .)
    stdout.write("\n")
    return EXIT_OK


# Defensive default for the __main__ block: argv is taken from
# sys.argv and the process exits with the returned code
def _entrypoint(argv: Optional[List[str]] = None) -> None:  # pragma: no cover
    sys.exit(main(argv))


if __name__ == "__main__":  # pragma: no cover
    _entrypoint()
