"""
Test suite for the Skincare Routine Classifier.

Goals
-----
* Cover every decision branch in ``recommend_skincare_routine`` so the
  CI coverage gate is meaningful.
* Use ``@pytest.mark.parametrize`` to drive concise, table-style tests.
* Exercise normal cases, edge cases, boundary values and failure modes
  (each custom exception is asserted separately).
* Keep tests independent and deterministic so they can be re-run in any
  order by the Jenkins pipeline.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from src.component import (
    IncompatibleSelectionError,
    InvalidFieldValueError,
    InvalidProfileError,
    MissingFieldError,
    REQUIRED_FIELDS,
    VALID_BUDGETS,
    VALID_CLIMATES,
    VALID_CONCERNS,
    VALID_PREFERENCES,
    VALID_SKIN_TYPES,
    _strip_retinoids_for_minors,
    recommend_skincare_routine,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def baseline_profile() -> Dict[str, Any]:
    """A minimal, valid profile used as a starting point for many tests.

    Returning a fresh dict each call protects tests from cross-contamination
    when they mutate the fixture.
    """
    return {
        "skin_type": "normal",
        "age": 30,
        "concerns": [],
        "climate": "temperate",
        "budget": "medium",
        "routine_preference": "balanced",
        "sensitivities": [],
    }


# ---------------------------------------------------------------------------
# Normal behaviour
# ---------------------------------------------------------------------------

class TestHappyPath:
    """Tests covering successful classification with valid input."""

    def test_returns_expected_top_level_keys(self, baseline_profile):
        result = recommend_skincare_routine(baseline_profile)
        assert set(result.keys()) == {
            "age_band",
            "morning_routine",
            "evening_routine",
            "weekly_treatments",
            "warnings",
            "notes",
        }

    def test_morning_always_ends_with_sunscreen(self, baseline_profile):
        result = recommend_skincare_routine(baseline_profile)
        # SPF is critical regardless of preference; verify the rule.
        assert "SPF" in result["morning_routine"][-1]

    def test_function_is_deterministic(self, baseline_profile):
        # Two identical calls must produce equal outputs (no hidden state).
        a = recommend_skincare_routine(dict(baseline_profile))
        b = recommend_skincare_routine(dict(baseline_profile))
        assert a == b

    def test_input_dict_is_not_mutated(self, baseline_profile):
        snapshot = dict(baseline_profile)
        snapshot["concerns"] = list(baseline_profile["concerns"])
        recommend_skincare_routine(baseline_profile)
        assert baseline_profile == snapshot


# ---------------------------------------------------------------------------
# Parameterised decision-path coverage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("skin_type", sorted(VALID_SKIN_TYPES))
def test_every_skin_type_is_accepted(baseline_profile, skin_type):
    baseline_profile["skin_type"] = skin_type
    result = recommend_skincare_routine(baseline_profile)
    # Every skin type produces a non-empty morning routine.
    assert result["morning_routine"]


@pytest.mark.parametrize("climate", sorted(VALID_CLIMATES))
def test_every_climate_is_accepted(baseline_profile, climate):
    baseline_profile["climate"] = climate
    result = recommend_skincare_routine(baseline_profile)
    assert result["morning_routine"]


@pytest.mark.parametrize("budget", sorted(VALID_BUDGETS))
def test_budget_drives_notes(baseline_profile, budget):
    baseline_profile["budget"] = budget
    result = recommend_skincare_routine(baseline_profile)
    # The first note always describes the budget tier.
    assert result["notes"], "expected a budget tier note"
    assert any(budget in n.lower() or "tier" in n.lower() or
               "premium" in n.lower() or "drugstore" in n.lower() or
               "mid-range" in n.lower() for n in result["notes"])


@pytest.mark.parametrize("preference", sorted(VALID_PREFERENCES))
def test_every_preference_is_accepted(baseline_profile, preference):
    baseline_profile["routine_preference"] = preference
    result = recommend_skincare_routine(baseline_profile)
    assert result["morning_routine"]
    assert result["evening_routine"]


@pytest.mark.parametrize("concern", sorted(VALID_CONCERNS - {"aging"}))
def test_each_concern_adds_or_keeps_steps(baseline_profile, concern):
    """Every single-concern profile yields a coherent routine."""
    baseline_profile["concerns"] = [concern]
    result = recommend_skincare_routine(baseline_profile)
    assert result["morning_routine"]
    assert result["evening_routine"]


@pytest.mark.parametrize(
    "age,expected_band",
    [
        (0, "teen"),
        (17, "teen"),
        (18, "young_adult"),
        (29, "young_adult"),
        (30, "adult"),
        (44, "adult"),
        (45, "mature"),
        (59, "mature"),
        (60, "senior"),
        (120, "senior"),
    ],
)
def test_age_band_boundaries(baseline_profile, age, expected_band):
    """Boundary-value test for the age banding logic."""
    baseline_profile["age"] = age
    # Aging concern is incompatible with teens; clear it for safety.
    baseline_profile["concerns"] = []
    result = recommend_skincare_routine(baseline_profile)
    assert result["age_band"] == expected_band


# ---------------------------------------------------------------------------
# Concern-specific rules
# ---------------------------------------------------------------------------

class TestConcernSpecificRules:
    def test_acne_adds_salicylic_to_evening(self, baseline_profile):
        baseline_profile["concerns"] = ["acne"]
        result = recommend_skincare_routine(baseline_profile)
        assert any(
            "Salicylic" in s for s in result["evening_routine"]
        )

    def test_hyperpigmentation_adds_vitamin_c(self, baseline_profile):
        baseline_profile["concerns"] = ["hyperpigmentation"]
        result = recommend_skincare_routine(baseline_profile)
        assert any(
            "Vitamin C" in s for s in result["morning_routine"]
        )

    def test_aging_adds_retinoid_for_adults(self, baseline_profile):
        baseline_profile["age"] = 35
        baseline_profile["concerns"] = ["aging"]
        result = recommend_skincare_routine(baseline_profile)
        assert any(
            "Retinoid" in s for s in result["evening_routine"]
        )

    def test_dehydration_adds_hyaluronic(self, baseline_profile):
        baseline_profile["concerns"] = ["dehydration"]
        result = recommend_skincare_routine(baseline_profile)
        assert any(
            "Hyaluronic" in s for s in result["morning_routine"]
        )

    def test_comprehensive_for_mature_adds_peptide_mask(self, baseline_profile):
        baseline_profile["age"] = 50
        baseline_profile["routine_preference"] = "comprehensive"
        baseline_profile["concerns"] = ["hyperpigmentation"]
        result = recommend_skincare_routine(baseline_profile)
        assert any("Peptide" in w for w in result["weekly_treatments"])

    def test_dullness_minimal_skips_aha_mask(self, baseline_profile):
        baseline_profile["concerns"] = ["dullness"]
        baseline_profile["routine_preference"] = "minimal"
        result = recommend_skincare_routine(baseline_profile)
        assert all("AHA" not in w for w in result["weekly_treatments"])

    def test_blackheads_balanced_adds_clay(self, baseline_profile):
        baseline_profile["concerns"] = ["blackheads"]
        baseline_profile["routine_preference"] = "balanced"
        result = recommend_skincare_routine(baseline_profile)
        assert any("Clay" in w for w in result["weekly_treatments"])


# ---------------------------------------------------------------------------
# Climate-specific rules
# ---------------------------------------------------------------------------

class TestClimateRules:
    def test_cold_climate_layers_facial_oil_for_dry_skin(self, baseline_profile):
        baseline_profile["skin_type"] = "dry"
        baseline_profile["climate"] = "cold"
        result = recommend_skincare_routine(baseline_profile)
        assert any(
            "facial oil" in s.lower() for s in result["morning_routine"]
        )

    def test_humid_climate_lightens_moisturiser_for_normal_skin(
        self, baseline_profile
    ):
        baseline_profile["skin_type"] = "normal"
        baseline_profile["climate"] = "humid"
        result = recommend_skincare_routine(baseline_profile)
        # Heavy "Rich cream" wording should not survive in humid climates
        assert all(
            "Rich cream" not in s for s in result["morning_routine"]
        )

    def test_dry_climate_normal_skin_gets_layered_oil(self, baseline_profile):
        baseline_profile["skin_type"] = "normal"
        baseline_profile["climate"] = "dry"
        result = recommend_skincare_routine(baseline_profile)
        assert any(
            "facial oil" in s.lower() for s in result["morning_routine"]
        )

    def test_humid_climate_lightens_moisturiser_for_dry_skin(
        self, baseline_profile
    ):
        """dry skin + humid climate is the only combination that triggers
        the Rich-cream → Lightweight-lotion substitution rule in
        ``_moisturiser_for``. Without this test that branch was never taken."""
        baseline_profile["skin_type"] = "dry"
        baseline_profile["climate"] = "humid"
        result = recommend_skincare_routine(baseline_profile)
        # The rich cream should have been substituted with a lighter option.
        assert all("Rich cream" not in s for s in result["morning_routine"])
        # A lotion variant must appear in its place.
        assert any("lotion" in s.lower() for s in result["morning_routine"])


# ---------------------------------------------------------------------------
# Preference rules
# ---------------------------------------------------------------------------

class TestPreferenceRules:
    def test_minimal_strips_evening_to_cleanser_and_moisturiser(
        self, baseline_profile
    ):
        baseline_profile["routine_preference"] = "minimal"
        result = recommend_skincare_routine(baseline_profile)
        # Minimal evening must not contain serums.
        assert len(result["evening_routine"]) <= 2

    def test_minimal_with_aging_concern_adds_note(self, baseline_profile):
        """When 'minimal' preference silently omits retinoids, the user must
        be informed via a note so they can choose a fuller routine."""
        baseline_profile["age"] = 35
        baseline_profile["concerns"] = ["aging"]
        baseline_profile["routine_preference"] = "minimal"
        result = recommend_skincare_routine(baseline_profile)
        assert any("retinoid" in n.lower() for n in result["notes"])

    def test_balanced_includes_double_cleanse(self, baseline_profile):
        baseline_profile["routine_preference"] = "balanced"
        result = recommend_skincare_routine(baseline_profile)
        assert any(
            "Oil cleanser" in s or "micellar" in s.lower()
            for s in result["evening_routine"]
        )

    def test_comprehensive_keeps_full_routine(self, baseline_profile):
        baseline_profile["routine_preference"] = "comprehensive"
        baseline_profile["concerns"] = ["hyperpigmentation"]
        result = recommend_skincare_routine(baseline_profile)
        # Comprehensive should add niacinamide for hyperpigmentation.
        assert any(
            "Niacinamide" in s for s in result["evening_routine"]
        )


# ---------------------------------------------------------------------------
# Sensitivities filter
# ---------------------------------------------------------------------------

class TestSensitivities:
    def test_salicylic_sensitivity_removes_salicylic_serum(
        self, baseline_profile
    ):
        baseline_profile["concerns"] = ["acne"]
        baseline_profile["sensitivities"] = ["salicylic_acid"]
        result = recommend_skincare_routine(baseline_profile)
        assert all(
            "Salicylic" not in s for s in result["evening_routine"]
        )
        assert any(
            "Removed" in w and "salicylic" in w.lower()
            for w in result["warnings"]
        )

    def test_retinoid_sensitivity_removes_retinoid(self, baseline_profile):
        baseline_profile["age"] = 40
        baseline_profile["concerns"] = ["aging"]
        baseline_profile["sensitivities"] = ["retinoids"]
        result = recommend_skincare_routine(baseline_profile)
        assert all("Retinoid" not in s for s in result["evening_routine"])

    def test_unknown_sensitivity_is_noted(self, baseline_profile):
        baseline_profile["sensitivities"] = ["mystery_extract"]
        result = recommend_skincare_routine(baseline_profile)
        assert any("Custom sensitivities" in n for n in result["notes"])

    def test_sensitivity_match_is_case_insensitive(self, baseline_profile):
        baseline_profile["concerns"] = ["acne"]
        baseline_profile["sensitivities"] = ["SALICYLIC_ACID"]
        result = recommend_skincare_routine(baseline_profile)
        assert all(
            "Salicylic" not in s for s in result["evening_routine"]
        )

    def test_fragrance_sensitivity_keeps_fragrance_free_items(
        self, baseline_profile
    ):
        """A 'fragrance-free' product must not be filtered out for a
        fragrance-sensitive user - that would be the opposite of helpful."""
        baseline_profile["skin_type"] = "sensitive"
        baseline_profile["sensitivities"] = ["fragrance"]
        result = recommend_skincare_routine(baseline_profile)
        assert any(
            "milk cleanser" in s.lower() for s in result["morning_routine"]
        )

    def test_spf_preserved_despite_sunscreen_sensitivity(self, baseline_profile):
        """SPF is non-negotiable and must not be removed even if the user
        declares 'sunscreen' as a sensitivity."""
        baseline_profile["sensitivities"] = ["sunscreen"]
        result = recommend_skincare_routine(baseline_profile)
        assert any("SPF" in s for s in result["morning_routine"])
        assert "SPF" in result["morning_routine"][-1]

    def test_known_sensitivity_in_uppercase_not_flagged_as_unknown(
        self, baseline_profile
    ):
        """A known sensitivity submitted in uppercase must be recognised and
        must not generate a misleading 'custom sensitivity' note."""
        baseline_profile["concerns"] = ["acne"]
        baseline_profile["sensitivities"] = ["SALICYLIC_ACID"]
        result = recommend_skincare_routine(baseline_profile)
        assert all("Custom sensitivities" not in n for n in result["notes"])


# ---------------------------------------------------------------------------
# Minor-safety rules
# ---------------------------------------------------------------------------

class TestMinorSafety:
    def test_minor_with_aging_concern_raises(self, baseline_profile):
        baseline_profile["age"] = 16
        baseline_profile["concerns"] = ["aging"]
        with pytest.raises(IncompatibleSelectionError):
            recommend_skincare_routine(baseline_profile)

    def test_minor_routine_never_contains_retinoid(self, baseline_profile):
        baseline_profile["age"] = 15
        baseline_profile["concerns"] = ["acne"]
        result = recommend_skincare_routine(baseline_profile)
        flat = (
            result["morning_routine"]
            + result["evening_routine"]
            + result["weekly_treatments"]
        )
        assert all("Retinoid" not in s for s in flat)

    def test_strip_retinoids_helper_emits_warning(self):
        """Direct unit test for the defensive helper. If an upstream change
        ever lets a retinoid step reach a teen, this guard removes it AND
        records a warning - prove both behaviours explicitly."""
        morning = ["Cleanser", "Retinoids morning step"]
        evening = ["Retinoids evening step", "Moisturiser"]
        weekly = ["Retinoid mask"]
        m, e, w, warnings = _strip_retinoids_for_minors(
            morning, evening, weekly, age_band="teen"
        )
        assert all("Retinoid" not in s for s in m + e + w)
        assert any("under 18" in msg for msg in warnings)

    def test_strip_retinoids_helper_noop_for_adults(self):
        morning = ["Cleanser", "Retinoids step"]
        m, e, w, warnings = _strip_retinoids_for_minors(
            morning, [], [], age_band="adult"
        )
        # Adult routines must not be touched and no warning is emitted.
        assert m == morning
        assert warnings == []


# ---------------------------------------------------------------------------
# Failure cases — every custom exception class is exercised
# ---------------------------------------------------------------------------

class TestValidationFailures:
    @pytest.mark.parametrize(
        "bad_input",
        ["not a dict", 42, None, ["list", "instead"]],
    )
    def test_non_mapping_input_raises(self, bad_input):
        with pytest.raises(InvalidProfileError):
            recommend_skincare_routine(bad_input)

    @pytest.mark.parametrize("missing_field", list(REQUIRED_FIELDS))
    def test_missing_required_field_raises(
        self, baseline_profile, missing_field
    ):
        del baseline_profile[missing_field]
        with pytest.raises(MissingFieldError) as exc_info:
            recommend_skincare_routine(baseline_profile)
        assert missing_field in str(exc_info.value)

    @pytest.mark.parametrize(
        "field,bad_value",
        [
            ("skin_type", "alien"),
            ("skin_type", 123),
            ("climate", "tropical"),
            ("budget", "free"),
            ("routine_preference", "extreme"),
        ],
    )
    def test_invalid_string_value_raises(
        self, baseline_profile, field, bad_value
    ):
        baseline_profile[field] = bad_value
        with pytest.raises(InvalidFieldValueError):
            recommend_skincare_routine(baseline_profile)

    @pytest.mark.parametrize("bad_age", [-1, 121, "30", 30.5, True, None])
    def test_invalid_age_raises(self, baseline_profile, bad_age):
        baseline_profile["age"] = bad_age
        with pytest.raises(InvalidFieldValueError):
            recommend_skincare_routine(baseline_profile)

    @pytest.mark.parametrize("good_age", [0, 18, 60, 120])
    def test_age_boundary_values_accepted(self, baseline_profile, good_age):
        baseline_profile["age"] = good_age
        # Concerns must not violate the minor/aging rule.
        baseline_profile["concerns"] = []
        recommend_skincare_routine(baseline_profile)  # must not raise

    def test_unknown_concern_raises(self, baseline_profile):
        baseline_profile["concerns"] = ["levitation"]
        with pytest.raises(InvalidFieldValueError) as exc_info:
            recommend_skincare_routine(baseline_profile)
        assert "levitation" in str(exc_info.value)

    def test_concerns_must_be_list(self, baseline_profile):
        baseline_profile["concerns"] = "acne"  # string, not list
        with pytest.raises(InvalidFieldValueError):
            recommend_skincare_routine(baseline_profile)

    def test_concerns_must_contain_strings(self, baseline_profile):
        baseline_profile["concerns"] = ["acne", 123]
        with pytest.raises(InvalidFieldValueError):
            recommend_skincare_routine(baseline_profile)

    def test_sensitivities_must_be_list(self, baseline_profile):
        baseline_profile["sensitivities"] = "fragrance"
        with pytest.raises(InvalidFieldValueError):
            recommend_skincare_routine(baseline_profile)

    def test_sensitivities_must_contain_strings(self, baseline_profile):
        baseline_profile["sensitivities"] = ["fragrance", 1.0]
        with pytest.raises(InvalidFieldValueError):
            recommend_skincare_routine(baseline_profile)


# ---------------------------------------------------------------------------
# Exception-hierarchy assertions
# ---------------------------------------------------------------------------

def test_exception_hierarchy_allows_broad_catch(baseline_profile):
    """Any specific failure must also be catchable via InvalidProfileError."""
    baseline_profile["skin_type"] = "alien"
    with pytest.raises(InvalidProfileError):
        recommend_skincare_routine(baseline_profile)


# ---------------------------------------------------------------------------
# Integration-style scenarios
# ---------------------------------------------------------------------------

class TestRealisticScenarios:
    """End-to-end scenarios exercising multiple rules at once."""

    @pytest.mark.parametrize(
        "profile,expectations",
        [
            (
                {
                    "skin_type": "oily",
                    "age": 22,
                    "concerns": ["acne", "blackheads"],
                    "climate": "humid",
                    "budget": "low",
                    "routine_preference": "balanced",
                    "sensitivities": [],
                },
                {"morning_has": "Gel cleanser", "evening_has": "Salicylic"},
            ),
            (
                {
                    "skin_type": "dry",
                    "age": 55,
                    "concerns": ["aging", "dehydration"],
                    "climate": "cold",
                    "budget": "high",
                    "routine_preference": "comprehensive",
                    "sensitivities": [],
                },
                {"morning_has": "Hyaluronic", "evening_has": "Retinoid"},
            ),
            (
                {
                    "skin_type": "sensitive",
                    "age": 28,
                    "concerns": ["redness"],
                    "climate": "temperate",
                    "budget": "medium",
                    "routine_preference": "minimal",
                    "sensitivities": ["fragrance"],
                },
                {"morning_has": "milk cleanser", "evening_count_max": 2},
            ),
        ],
    )
    def test_realistic_profile(
        self, profile: Dict[str, Any], expectations: Dict[str, Any]
    ):
        result = recommend_skincare_routine(profile)

        if "morning_has" in expectations:
            needle = expectations["morning_has"]
            assert any(
                needle.lower() in s.lower() for s in result["morning_routine"]
            ), f"morning routine missing {needle!r}: {result['morning_routine']}"

        if "evening_has" in expectations:
            needle = expectations["evening_has"]
            assert any(
                needle.lower() in s.lower() for s in result["evening_routine"]
            ), f"evening routine missing {needle!r}: {result['evening_routine']}"

        if "evening_count_max" in expectations:
            assert (
                len(result["evening_routine"])
                <= expectations["evening_count_max"]
            )
