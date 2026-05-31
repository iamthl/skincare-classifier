"""
Skincare Routine Classifier
===========================

A rule-based decision component that converts a structured user profile
(skin type, age, concerns, sensitivities, climate, budget, routine
preference) into a personalised, ordered skincare routine.

The component is intentionally deterministic and pure so that every
decision branch can be exercised by automated tests in the CI/CD
pipeline. Validation, normalisation and recommendation are kept in
separate helpers to maximise readability, testability and to keep
each function below the project's flake8 complexity gate.

Author : CSY3056 - Assignment 1
Python : 3.11+
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Mapping, Tuple


# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------
# Using frozensets gives O(1) membership tests *and* immutability, which
# prevents accidental mutation of the allowed-value vocabularies.

VALID_SKIN_TYPES: FrozenSet[str] = frozenset(
    {"oily", "dry", "combination", "normal", "sensitive"}
)

VALID_CONCERNS: FrozenSet[str] = frozenset(
    {
        "acne",
        "aging",
        "hyperpigmentation",
        "dehydration",
        "redness",
        "dullness",
        "blackheads",
    }
)

VALID_CLIMATES: FrozenSet[str] = frozenset({"humid", "dry", "temperate", "cold"})

VALID_BUDGETS: FrozenSet[str] = frozenset({"low", "medium", "high"})

VALID_PREFERENCES: FrozenSet[str] = frozenset(
    {"minimal", "balanced", "comprehensive"}
)

# Ingredients which are recognised as sensitivities. Anything outside this
# set is still accepted (users may know their own triggers), but the known
# ones drive built-in exclusion rules.
KNOWN_SENSITIVITIES: FrozenSet[str] = frozenset(
    {"fragrance", "alcohol", "essential_oils", "retinoids", "salicylic_acid"}
)

# Age must be a non-negative integer; an upper bound guards against typos
# (e.g. someone entering 200 instead of 20).
MIN_AGE: int = 0
MAX_AGE: int = 120


# ---------------------------------------------------------------------------
# Custom exception hierarchy
# ---------------------------------------------------------------------------
# A small hierarchy lets callers either catch everything (InvalidProfileError)
# or react to a specific failure mode. This is friendlier to consumers of
# this component than raising bare ValueError / TypeError everywhere.

class InvalidProfileError(Exception):
    """Base class for any problem with the supplied ``user_profile``."""


class MissingFieldError(InvalidProfileError):
    """A required key is absent from the profile."""


class InvalidFieldValueError(InvalidProfileError):
    """A field is present but contains an unsupported or malformed value."""


class IncompatibleSelectionError(InvalidProfileError):
    """The combination of fields is internally inconsistent or unsafe."""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
# Each field has its own tiny validator. Splitting the work this way keeps
# cyclomatic complexity low and lets the test suite target one rule at a time.

REQUIRED_FIELDS: Tuple[str, ...] = (
    "skin_type",
    "age",
    "concerns",
    "climate",
    "budget",
    "routine_preference",
)


def _check_required_fields(profile: Mapping[str, Any]) -> None:
    for field in REQUIRED_FIELDS:
        if field not in profile:
            raise MissingFieldError(f"Missing required field: '{field}'")


def _check_choice(field: str, value: Any, allowed: FrozenSet[str]) -> None:
    """Reject any value not present in the allowed vocabulary."""
    if not isinstance(value, str) or value not in allowed:
        raise InvalidFieldValueError(
            f"{field} must be one of {sorted(allowed)}, got {value!r}"
        )


def _check_age(age: Any) -> None:
    # ``bool`` is a subclass of ``int``; reject it explicitly so True/False
    # cannot sneak through the type check.
    if isinstance(age, bool) or not isinstance(age, int):
        raise InvalidFieldValueError(
            f"age must be an int, got {type(age).__name__}"
        )
    if age < MIN_AGE or age > MAX_AGE:
        raise InvalidFieldValueError(
            f"age must be between {MIN_AGE} and {MAX_AGE}, got {age}"
        )


def _check_string_list(field: str, value: Any) -> None:
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise InvalidFieldValueError(f"{field} must be a list of strings")


def _check_concerns(concerns: Any) -> None:
    _check_string_list("concerns", concerns)
    unknown = set(concerns) - VALID_CONCERNS
    if unknown:
        raise InvalidFieldValueError(
            f"Unsupported concerns: {sorted(unknown)}. "
            f"Allowed: {sorted(VALID_CONCERNS)}"
        )


def _check_combinations(age: int, concerns: List[str]) -> None:
    # Safety rule: anti-aging is not appropriate for minors. Catching this
    # at validation time prevents downstream rules from producing an unsafe
    # routine in the first place.
    if age < 18 and "aging" in concerns:
        raise IncompatibleSelectionError(
            "Anti-aging routines are not appropriate for users under 18."
        )


def _validate_profile(profile: Mapping[str, Any]) -> None:
    """Validate the structure and contents of ``profile``.

    Raises one of the ``InvalidProfileError`` subclasses on failure.
    Splitting the work into focused helpers keeps this dispatcher trivial.
    """
    if not isinstance(profile, Mapping):
        raise InvalidProfileError(
            f"user_profile must be a mapping, got {type(profile).__name__}"
        )

    _check_required_fields(profile)
    _check_choice("skin_type", profile["skin_type"], VALID_SKIN_TYPES)
    _check_age(profile["age"])
    _check_concerns(profile["concerns"])
    _check_choice("climate", profile["climate"], VALID_CLIMATES)
    _check_choice("budget", profile["budget"], VALID_BUDGETS)
    _check_choice("routine_preference", profile["routine_preference"],
                  VALID_PREFERENCES)

    # Sensitivities is optional; default to empty list when absent.
    _check_string_list("sensitivities", profile.get("sensitivities", []))

    _check_combinations(profile["age"], profile["concerns"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _age_band(age: int) -> str:
    """Map a numeric age to a coarse band used by the recommendation logic."""
    if age < 18:
        return "teen"
    if age < 30:
        return "young_adult"
    if age < 45:
        return "adult"
    if age < 60:
        return "mature"
    return "senior"


def _cleanser_for(skin_type: str) -> str:
    """Pick a cleanser style appropriate to the user's skin type."""
    # A simple lookup table keeps the rule explicit and trivially testable.
    return {
        "oily": "Gel cleanser (low-pH, oil-controlling)",
        "dry": "Cream cleanser (hydrating, non-foaming)",
        "combination": "Gentle gel cleanser (balanced)",
        "normal": "Gentle foaming cleanser",
        "sensitive": "Fragrance-free milk cleanser",
    }[skin_type]


def _moisturiser_for(skin_type: str, climate: str) -> str:
    """Pick a moisturiser whose richness matches both skin type and climate.

    Climate adjusts richness: humid -> lighter, cold/dry -> richer.
    """
    base = {
        "oily": "Oil-free gel moisturiser",
        "dry": "Rich cream moisturiser with ceramides",
        "combination": "Lightweight lotion moisturiser",
        "normal": "Balanced lotion moisturiser",
        "sensitive": "Fragrance-free barrier cream",
    }[skin_type]
    if climate in {"cold", "dry"} and skin_type != "oily":
        return base + " (layered with a facial oil at night)"
    if climate == "humid" and skin_type == "dry":
        return base.replace("Rich cream", "Lightweight lotion")
    return base


def _budget_tier_note(budget: str) -> str:
    """Human-readable note describing the spending tier."""
    return {
        "low": "Drugstore-tier products prioritised; expect 3-5 SKUs total.",
        "medium": "Mix of drugstore and mid-range actives.",
        "high": "Premium/dermatologist-tier products acceptable.",
    }[budget]


def _item_triggers_sensitivity(lower_item: str, sens: str) -> bool:
    """Return True iff ``lower_item`` contains ``sens`` and is not labelled
    as being free of it (e.g. "fragrance-free milk cleanser")."""
    if sens not in lower_item:
        return False
    # Recognise common "free-from" phrasing to avoid false positives.
    if f"{sens}-free" in lower_item or f"{sens} free" in lower_item:
        return False
    return True


def _filter_against_sensitivities(
    items: List[str], sensitivities: List[str]
) -> Tuple[List[str], List[str]]:
    """Remove routine items containing any sensitised ingredient.

    Returns the surviving items plus a list of warnings explaining the
    removals. Matching is case-insensitive and substring-based so that
    "Salicylic acid 2% serum" is removed when the user declares
    ``"salicylic_acid"`` as a sensitivity, while "Fragrance-free milk
    cleanser" is *kept* when the user is sensitive to fragrance.
    """
    kept: List[str] = []
    warnings: List[str] = []
    normalised_sens = [s.lower().replace("_", " ") for s in sensitivities]
    for item in items:
        lower_item = item.lower()
        triggered = next(
            (s for s in normalised_sens
             if _item_triggers_sensitivity(lower_item, s)),
            None,
        )
        if triggered:
            warnings.append(
                f"Removed '{item}' due to sensitivity: {triggered}"
            )
            continue
        kept.append(item)
    return kept, warnings


# ---------------------------------------------------------------------------
# Routine builders
# ---------------------------------------------------------------------------
# Splitting morning / evening / weekly out of the public function keeps the
# top-level orchestration concise and each builder independently testable.

def _build_morning_routine(
    skin_type: str, concerns: List[str], climate: str
) -> List[str]:
    """Construct an ordered morning routine.

    Order matters in skincare (cleanser -> treatments -> moisturiser -> SPF)
    so we append step-by-step rather than working from a set.
    """
    routine: List[str] = [_cleanser_for(skin_type)]

    if "redness" in concerns or skin_type == "sensitive":
        routine.append("Centella/azelaic soothing serum")

    if "dehydration" in concerns or skin_type == "dry":
        routine.append("Hyaluronic acid hydrating serum")

    if "hyperpigmentation" in concerns or "dullness" in concerns:
        routine.append("Vitamin C antioxidant serum (10-15%)")

    routine.append(_moisturiser_for(skin_type, climate))
    # SPF is non-negotiable in every routine, regardless of preference.
    routine.append("Broad-spectrum SPF 30+ sunscreen")
    return routine


def _build_evening_routine(
    skin_type: str,
    concerns: List[str],
    climate: str,
    preference: str,
    age_band: str,
) -> List[str]:
    """Construct an ordered evening routine."""
    routine: List[str] = []

    # A double cleanse only makes sense if there is sunscreen/makeup to remove.
    if preference in {"balanced", "comprehensive"}:
        routine.append("Oil cleanser / micellar water (first cleanse)")
    routine.append(_cleanser_for(skin_type))

    if "acne" in concerns or "blackheads" in concerns:
        routine.append("Salicylic acid 2% serum")

    if "aging" in concerns and age_band != "teen":
        # Defensive: validator already rules out teen + aging, but assert
        # the invariant explicitly so the code is robust to future changes.
        routine.append("Retinoids (start 2x/week, build tolerance)")

    if "hyperpigmentation" in concerns and preference == "comprehensive":
        routine.append("Niacinamide 10% serum")

    routine.append(_moisturiser_for(skin_type, climate))
    return routine


def _build_weekly_treatments(
    skin_type: str, concerns: List[str], climate: str,
    preference: str, age_band: str,
) -> List[str]:
    """Construct the list of weekly extras."""
    if preference == "minimal":
        return []

    weekly: List[str] = []
    if "dullness" in concerns:
        weekly.append("AHA exfoliating mask (1x/week)")
    if "blackheads" in concerns:
        weekly.append("Clay mask (1x/week)")
    if skin_type in {"dry", "normal"} and climate in {"cold", "dry"}:
        weekly.append("Hydrating sheet mask (2x/week)")
    if preference == "comprehensive" and age_band in {
        "adult", "mature", "senior"
    }:
        weekly.append("Peptide treatment mask (1x/week)")
    return weekly


def _apply_minimal_preference(
    morning: List[str], evening: List[str], preference: str,
) -> Tuple[List[str], List[str]]:
    """Trim morning/evening lists to the essentials for 'minimal' users.

    Honoured *after* concern-based additions so the SPF and moisturiser
    are still preserved when we cut the middle out.

    Index assumptions — guaranteed by ``_build_morning_routine``'s fixed order:
      * ``morning[0]``  — always the cleanser (first step appended)
      * ``morning[-2]`` — always the moisturiser (second-to-last, appended
                          before SPF by every code path in the builder)
      * ``morning[-1]`` — always the SPF (unconditional last append)
    The property test ``test_morning_routine_always_ends_with_spf`` asserts
    the SPF invariant across 100 randomly generated profiles; if a future
    change to ``_build_morning_routine`` breaks the ordering, that property
    will fail before this function can produce a corrupt routine.
    """
    if preference != "minimal":
        return morning, evening
    new_morning = [
        morning[0],        # cleanser
        morning[-2],       # moisturiser
        morning[-1],       # SPF
    ]
    new_evening = [evening[0], evening[-1]] if len(evening) >= 2 else evening
    return new_morning, new_evening


def _strip_retinoids_for_minors(
    morning: List[str], evening: List[str], weekly: List[str],
    age_band: str,
) -> Tuple[List[str], List[str], List[str], List[str]]:
    """Belt-and-braces removal of any retinoid step for teens."""
    if age_band != "teen":
        return morning, evening, weekly, []

    before = len(morning) + len(evening) + len(weekly)
    morning = [s for s in morning if "retinoid" not in s.lower()]
    evening = [s for s in evening if "retinoid" not in s.lower()]
    weekly = [w for w in weekly if "retinoid" not in w.lower()]
    warnings: List[str] = []
    if before != len(morning) + len(evening) + len(weekly):
        warnings.append(
            "Removed retinoid-based steps because user is under 18."
        )
    return morning, evening, weekly, warnings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def recommend_skincare_routine(
    user_profile: Mapping[str, Any],
) -> Dict[str, Any]:
    """Generate a personalised skincare routine for ``user_profile``.

    The function is deterministic: identical inputs always produce
    identical outputs, which is essential for reproducible CI testing.

    Parameters
    ----------
    user_profile : Mapping[str, Any]
        Required keys:
            * ``skin_type`` (str): one of ``VALID_SKIN_TYPES``
            * ``age`` (int): 0..120 inclusive
            * ``concerns`` (list[str]): each in ``VALID_CONCERNS``
            * ``climate`` (str): one of ``VALID_CLIMATES``
            * ``budget`` (str): one of ``VALID_BUDGETS``
            * ``routine_preference`` (str): one of ``VALID_PREFERENCES``
        Optional keys:
            * ``sensitivities`` (list[str]): ingredients to avoid

    Returns
    -------
    Dict[str, Any]
        A dictionary with the following keys::

            {
              "age_band":            str,
              "morning_routine":     list[str],   # ordered steps
              "evening_routine":     list[str],   # ordered steps
              "weekly_treatments":   list[str],
              "warnings":            list[str],
              "notes":               list[str],
            }

    Raises
    ------
    InvalidProfileError
        If ``user_profile`` is not a mapping.
    MissingFieldError
        If a required key is missing.
    InvalidFieldValueError
        If a field has an unsupported type or value.
    IncompatibleSelectionError
        If the combination of fields is unsafe (e.g. anti-aging for a minor).

    Examples
    --------
    >>> routine = recommend_skincare_routine({
    ...     "skin_type": "oily",
    ...     "age": 25,
    ...     "concerns": ["acne"],
    ...     "climate": "humid",
    ...     "budget": "medium",
    ...     "routine_preference": "balanced",
    ... })
    >>> "morning_routine" in routine
    True
    """
    _validate_profile(user_profile)

    skin_type: str = user_profile["skin_type"]
    age: int = user_profile["age"]
    concerns: List[str] = list(user_profile["concerns"])
    climate: str = user_profile["climate"]
    budget: str = user_profile["budget"]
    preference: str = user_profile["routine_preference"]
    sensitivities: List[str] = list(user_profile.get("sensitivities", []))

    age_band = _age_band(age)
    notes: List[str] = [_budget_tier_note(budget)]

    morning = _build_morning_routine(skin_type, concerns, climate)
    evening = _build_evening_routine(
        skin_type, concerns, climate, preference, age_band
    )
    weekly = _build_weekly_treatments(
        skin_type, concerns, climate, preference, age_band
    )

    morning, evening = _apply_minimal_preference(morning, evening, preference)
    if preference == "minimal" and "aging" in concerns and age_band != "teen":
        notes.append(
            "Anti-aging steps (retinoids) are excluded by the 'minimal' routine "
            "preference; choose 'balanced' or 'comprehensive' to include them."
        )

    morning, evening, weekly, minor_warnings = _strip_retinoids_for_minors(
        morning, evening, weekly, age_band
    )
    warnings: List[str] = list(minor_warnings)

    if morning and "SPF" in morning[-1]:
        spf_step = morning[-1]
        morning_body, w1 = _filter_against_sensitivities(morning[:-1], sensitivities)
        morning = morning_body + [spf_step]
    else:  # pragma: no cover  — SPF is always the last morning step (see
        # _build_morning_routine and _apply_minimal_preference); this branch
        # is defensive code for a future rule change that drops SPF, not a
        # reachable path via the current public API.
        morning, w1 = _filter_against_sensitivities(morning, sensitivities)
    evening, w2 = _filter_against_sensitivities(evening, sensitivities)
    weekly, w3 = _filter_against_sensitivities(weekly, sensitivities)
    warnings.extend(w1 + w2 + w3)

    # Inform about unrecognised sensitivities so the user can double-check.
    unknown_sens = [
        s for s in sensitivities
        if s.lower().replace(" ", "_") not in KNOWN_SENSITIVITIES
    ]
    if unknown_sens:
        notes.append(
            f"Custom sensitivities recorded but not in the known list: "
            f"{sorted(unknown_sens)}"
        )

    return {
        "age_band": age_band,
        "morning_routine": morning,
        "evening_routine": evening,
        "weekly_treatments": weekly,
        "warnings": warnings,
        "notes": notes,
    }
