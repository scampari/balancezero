"""Unit tests for api_helpers pure functions.

changes/022 adds `description_similarity` — the fuzzy match used by Plaid
sync to decide whether an incoming transaction is the one a user already
entered by hand. Contract (spec/plaid-sync.md § Manual-transaction
adoption): lower-case each side, reduce it to alphanumerics separated by
single spaces, then `difflib.SequenceMatcher(None, a, b).ratio()`. No
substring shortcut. The 0.80 acceptance threshold lives in plaid_api /
the adoption logic, not here — these tests pin the ratio function itself.
"""

import difflib

import api_helpers

ADOPTION_THRESHOLD = 0.80  # spec/plaid-sync.md § Manual-transaction adoption


class TestDescriptionSimilarity:
    def test_when_only_case_and_punctuation_differ_then_ratio_is_1(self):
        # Arrange / Act
        ratio = api_helpers.description_similarity("AMAZON  MKTPL*1A2B", "amazon mktpl 1a2b")

        # Assert — normalization folds case, the "*" and the doubled space
        assert ratio == 1.0

    def test_ratio_is_difflib_on_the_normalized_text(self):
        # Arrange — the contract's normalization applied by hand: lower-case,
        # every non-alphanumeric run collapsed to one space, trimmed.
        normalized_a = "whole foods mkt 5th ave"
        normalized_b = "whole foods market"
        expected = difflib.SequenceMatcher(None, normalized_a, normalized_b).ratio()

        # Act
        ratio = api_helpers.description_similarity("Whole Foods Mkt — 5th Ave!", "WHOLE FOODS MARKET")

        # Assert — same value difflib gives on the normalized strings
        assert ratio == expected

    def test_same_merchant_with_a_store_number_clears_the_threshold(self):
        # "Blue Bottle Coffee 0123" vs the card network's version of it
        ratio = api_helpers.description_similarity("BLUE BOTTLE COFFEE 0123", "SQ *BLUE BOTTLE COFFEE 0123")

        assert ratio >= ADOPTION_THRESHOLD

    def test_unrelated_merchants_are_below_the_threshold(self):
        ratio = api_helpers.description_similarity("Blue Bottle Coffee", "Shell Gas")

        assert ratio < ADOPTION_THRESHOLD

    def test_boundary_pair_just_above_threshold(self):
        # "spotify usa" vs "spotify usa 3xy" -> 22/26 == 0.846
        ratio = api_helpers.description_similarity("Spotify USA", "SPOTIFY USA 3XY")

        assert ratio >= ADOPTION_THRESHOLD

    def test_boundary_pair_just_below_threshold(self):
        # "uber trip" vs "lyft ride" -> well under 0.80
        ratio = api_helpers.description_similarity("Uber Trip", "Lyft Ride")

        assert ratio < ADOPTION_THRESHOLD
