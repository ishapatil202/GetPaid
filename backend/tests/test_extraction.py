"""Our own checks on the AI's answer: cleaning, quote matching, evidence."""
from app.extraction import clean_quote, clean_value, find_span, quote_supports, verify
from conftest import BRIGHTLEAF_TEXT, brightleaf_extraction


def test_fake_empty_values_become_real_none():
    assert clean_value("null") is None
    assert clean_value("N/A") is None
    assert clean_value("Net 15") == "Net 15"


def test_quotes_lose_extra_quotation_marks_and_ellipsis():
    assert clean_quote('"for $3,000 total."') == "for $3,000 total."
    assert clean_quote("“I'll refresh the site...”") == "I'll refresh the site"


def test_find_span_tolerates_spacing_case_and_end_punctuation():
    text = "Payment of $1,200, due on\nDecember 4, 2026 is required."
    assert find_span(text, "$1,200, due on December 4, 2026") is not None
    assert find_span(text, "PAYMENT OF $1,200") is not None
    assert find_span(text, "December 4, 2026.") is not None
    assert find_span(text, "something not in the text") is None


def test_quote_must_actually_mention_the_value():
    assert quote_supports("Tidewater Fitness", "- Marcus, Tidewater Fitness")
    assert not quote_supports("Tidewater Fitness", "Sounds good, agreed on all of the above.")
    assert quote_supports(3000.0, "for $3,000 total.")
    assert not quote_supports(3000.0, "for $2,500 total.")


def test_verify_catches_the_planted_problems_in_brightleaf():
    highlights, issues = verify(BRIGHTLEAF_TEXT, brightleaf_extraction())
    found = {i.code for i in issues}
    assert {"total_mismatch", "missing_due_date"} <= found
    assert all(h.found for h in highlights), [h.field for h in highlights if not h.found]


def test_verify_flags_a_made_up_quote():
    data = brightleaf_extraction()
    data.client_email.source_quote = "billing: invented@nowhere.example"
    _, issues = verify(BRIGHTLEAF_TEXT, data)
    assert any(i.code == "quote_not_found" and "client_email" in i.message for i in issues)
