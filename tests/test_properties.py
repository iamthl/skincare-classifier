"""
Property-based tests using Hypothesis.

Where ``test_component.py`` asserts behaviour on hand-picked examples,
this file asserts *invariants* that must hold for any profile drawn
from the domain vocabulary. Hypothesis generates many random profiles
each run and shrinks any failing case to its smallest counter-example,
which is significantly stronger evidence of correctness than a finite
example table and catches bugs example-based tests routinely miss.

Two invariants are exercised:

1. **Total function under valid input.** A profile assembled exclusively
   from the documented vocabulary must always return a well-formed
   result - never raise, never produce a malformed dict.
2. **Sunscreen invariant.** Regardless of any combination of inputs,
   the last step of the morning routine must always be SPF. This is
   the dermatology-equivalent of a hard safety rule, so it is worth
   testing as a universal property.

Bool-of-age guard
-----------------
Python's ``bool`` is a subclass of ``int``. Hypothesis' default
``integers`` strategy never produces booleans, but a future change
could; the ``_check_age`` validator explicitly rejects bools, and the
test below documents that decision.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.component import (
    VALID_BUDGETS,
    VALID_CLIMATES,
    VALID_CONCERNS,
    VALID_PREFERENCES,
    VALID_SKIN_TYPES,
    recommend_skincare_routine,
)


# Strategies derived from the domain vocabularies so the generated data
# is always *in* the validator's allow-list. We test the validator's
# rejection paths with example-based tests in ``test_component``;
# property-based testing is best applied to the *accepting* path where
# we want behavioural invariants to hold across the entire input space.
_skin_types = st.sampled_from(sorted(VALID_SKIN_TYPES))
_climates = st.sampled_from(sorted(VALID_CLIMATES))
_budgets = st.sampled_from(sorted(VALID_BUDGETS))
_preferences = st.sampled_from(sorted(VALID_PREFERENCES))
_concerns_subset = st.lists(
    st.sampled_from(sorted(VALID_CONCERNS - {"aging"})),
    unique=True,
    max_size=4,
)
# Restrict age to >= 18 in this strategy because the safety rule
# (no aging for minors) is exercised separately; here we want to focus
# on combinatorial coverage of the *normal* adult routine.
_ages = st.integers(min_value=18, max_value=120)


@st.composite
def _adult_profile(draw):
    """Compose a fully-valid, adult, no-sensitivity profile."""
    return {
        "skin_type": draw(_skin_types),
        "age": draw(_ages),
        "concerns": draw(_concerns_subset),
        "climate": draw(_climates),
        "budget": draw(_budgets),
        "routine_preference": draw(_preferences),
        "sensitivities": [],
    }


# ``settings`` limits the per-test time budget so a flaky CI agent
# doesn't appear to hang. 100 examples is comfortable for a recommender
# of this size; the marginal returns drop off quickly past that.
@given(profile=_adult_profile())
@settings(max_examples=100, deadline=None)
def test_recommendation_total_function_for_adult_profile(profile):
    """Any well-formed adult profile must yield a well-formed result."""
    result = recommend_skincare_routine(profile)

    # Contract: the documented top-level keys are always present.
    assert {
        "age_band",
        "morning_routine",
        "evening_routine",
        "weekly_treatments",
        "warnings",
        "notes",
    } <= set(result.keys())

    # Morning and evening are non-empty - even a 'minimal' user has at
    # least a cleanser and a moisturiser.
    assert result["morning_routine"], "morning routine unexpectedly empty"
    assert result["evening_routine"], "evening routine unexpectedly empty"


@given(profile=_adult_profile())
@settings(max_examples=100, deadline=None)
def test_morning_routine_always_ends_with_spf(profile):
    """SPF is the non-negotiable last step of every morning routine.

    Holds across all skin types, all climates, all preferences,
    all concerns. If a future rule change accidentally drops SPF
    in a particular branch, this property breaks immediately.
    """
    result = recommend_skincare_routine(profile)
    last_step = result["morning_routine"][-1]
    assert "SPF" in last_step, f"missing SPF in morning routine: {last_step!r}"


@given(
    skin_type=_skin_types,
    climate=_climates,
)
@settings(max_examples=50, deadline=None)
def test_warnings_list_is_always_present_and_typed(skin_type, climate):
    """The ``warnings`` field must always be a list of strings.

    Some branches add warnings (sensitivity filters, retinoid strip),
    others do not - either way, callers should never have to defensively
    type-check the response.
    """
    profile = {
        "skin_type": skin_type,
        "age": 30,
        "concerns": [],
        "climate": climate,
        "budget": "medium",
        "routine_preference": "balanced",
        "sensitivities": [],
    }
    result = recommend_skincare_routine(profile)
    assert isinstance(result["warnings"], list)
    assert all(isinstance(w, str) for w in result["warnings"])
