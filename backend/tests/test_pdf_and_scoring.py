"""PDF reading and the eval grader."""
import pytest

from app.pdf_text import PdfTextError, pdf_to_text
from conftest import SAMPLES
from evals.scoring import name_matches, score_contract


def test_sample_pdf_text_keeps_the_payment_sentences():
    text = pdf_to_text((SAMPLES / "brightleaf_contract.pdf").read_bytes())
    assert "$1,200, due on December 4, 2026." in text
    assert "billing contact ap@brightleaf.example" in text  # line break re-joined


def test_non_pdf_file_gives_a_clear_error():
    with pytest.raises(PdfTextError, match="couldn't be read"):
        pdf_to_text(b"this is not a pdf")


def test_name_matching_ignores_company_suffixes_and_accepts_alternatives():
    assert name_matches("Lumen Health", "Lumen Health Inc.")
    assert name_matches("Marcus Lee", ["Tidewater Fitness", "Marcus Lee"])
    assert not name_matches("Northwind", "Brightleaf Coffee Co.")


def _extraction(amount):
    return {"client_name": {"value": "Pebble & Co Books"}, "client_email": {"value": None}, "currency": "usd",
            "contract_total": {"value": 700.0}, "milestones": [{"amount": amount, "due_date": "2026-11-25"}]}


EXPECTED = {"client_name": "Pebble & Co. Books", "client_email": None, "currency": "USD", "contract_total": 700,
            "milestones": [{"amount": 700, "due_date": "2026-11-25"}]}


def test_scoring_a_perfect_answer():
    score = score_contract(EXPECTED, ["missing_client_email"], _extraction(700), ["missing_client_email", "ai_concern"])
    assert score["all_correct"] and score["flags"]["false_negative"] == []


def test_scoring_catches_a_wrong_amount_and_a_missed_flag():
    score = score_contract(EXPECTED, ["missing_client_email"], _extraction(70), [])
    assert score["fields"]["milestone_1_amount"] is False
    assert score["flags"]["false_negative"] == ["missing_client_email"]
