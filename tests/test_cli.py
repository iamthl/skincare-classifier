"""
Tests for the CLI entrypoint.

The CLI is a thin shell around the component, so these tests focus on
the I/O boundaries it owns: argument parsing, JSON in / JSON out, and
exit-code mapping. Component-level logic is already covered exhaustively
in ``tests/test_component.py``,  deliberately do not retest it here.
"""

from __future__ import annotations

import io
import json
from typing import Any, Dict

import pytest

from src import cli


@pytest.fixture
def valid_profile() -> Dict[str, Any]:
    """A minimal, valid profile - mirrors the one in test_component."""
    return {
        "skin_type": "normal",
        "age": 30,
        "concerns": [],
        "climate": "temperate",
        "budget": "medium",
        "routine_preference": "balanced",
        "sensitivities": [],
    }


def _run(argv, stdin_text: str = "") -> tuple[int, str, str]:
    """Invoke ``cli.main`` with captured streams and return ``(code, out, err)``.

    A small helper keeps each test focused on assertions rather than
    boilerplate around stream injection.
    """
    stdin = io.StringIO(stdin_text)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli.main(argv, stdin=stdin, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


class TestStdinHappyPath:
    """When the profile is piped on stdin we expect JSON-out / code 0."""

    def test_returns_exit_ok_and_json(self, valid_profile):
        code, out, err = _run([], stdin_text=json.dumps(valid_profile))
        assert code == cli.EXIT_OK
        assert err == ""
        # Output must parse back to a dict containing the documented keys
        # - this is the API contract a downstream tool would rely on.
        parsed = json.loads(out)
        assert "morning_routine" in parsed
        assert "evening_routine" in parsed

    def test_pretty_flag_produces_indented_json(self, valid_profile):
        code, out, _ = _run(["--pretty"], stdin_text=json.dumps(valid_profile))
        assert code == cli.EXIT_OK
        # An indented dump contains newlines + leading spaces; the
        # compact form does not. Cheap but unambiguous discriminator.
        assert "\n  " in out


class TestFileInput:
    """The CLI must accept ``-i path/to/profile.json`` equivalently."""

    def test_reads_profile_from_file(self, tmp_path, valid_profile):
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(json.dumps(valid_profile), encoding="utf-8")

        code, out, err = _run(["-i", str(profile_path)])
        assert code == cli.EXIT_OK, err
        assert "morning_routine" in json.loads(out)

    def test_missing_file_returns_input_error(self, tmp_path):
        bogus = tmp_path / "does-not-exist.json"
        code, out, err = _run(["-i", str(bogus)])
        # An OSError from Path.read_text must surface as EXIT_INPUT_ERROR,
        # never as a Python traceback.
        assert code == cli.EXIT_INPUT_ERROR
        assert out == ""
        assert "input error" in err

    def test_malformed_json_file_returns_input_error(self, tmp_path):
        bad_path = tmp_path / "broken.json"
        bad_path.write_text("{ this is : not valid json", encoding="utf-8")
        code, _, err = _run(["-i", str(bad_path)])
        assert code == cli.EXIT_INPUT_ERROR
        assert "input error" in err


class TestStdinErrors:
    def test_empty_stdin_returns_input_error(self):
        code, _, err = _run([], stdin_text="")
        assert code == cli.EXIT_INPUT_ERROR
        # Message should mention the failure mode so a human can fix it.
        assert "No profile" in err or "profile" in err.lower()

    def test_invalid_json_on_stdin_returns_input_error(self):
        code, _, err = _run([], stdin_text="not json at all")
        assert code == cli.EXIT_INPUT_ERROR
        assert "input error" in err


class TestValidationErrors:
    """Domain validation failures must map to ``EXIT_VALIDATION_ERROR``."""

    def test_invalid_profile_returns_validation_error_code(self, valid_profile):
        valid_profile["skin_type"] = "alien"
        code, out, err = _run([], stdin_text=json.dumps(valid_profile))
        assert code == cli.EXIT_VALIDATION_ERROR
        assert out == ""
        # Message must mention the failing field for shell-friendly UX.
        assert "skin_type" in err

    def test_missing_required_field_returns_validation_error(
        self, valid_profile
    ):
        del valid_profile["age"]
        code, _, err = _run([], stdin_text=json.dumps(valid_profile))
        assert code == cli.EXIT_VALIDATION_ERROR
        assert "age" in err


def test_parser_has_documented_flags():
    """A small belt-and-braces check on the CLI's public contract.

    If a future change accidentally drops ``-i`` or ``--pretty`` (both
    are documented in the README), this test fails immediately rather
    than waiting for a user to discover it.
    """
    parser = cli._build_parser()
    option_strings = {action.option_strings[0] for action in parser._actions
                      if action.option_strings}
    assert "-i" in option_strings or "--input" in option_strings
    assert "--pretty" in option_strings
