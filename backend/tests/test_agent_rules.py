"""The reminder agent's rules: tone choice and the draft checker."""
from app.agent import check_draft, choose_tone

CONTRACT = "Payment (a): $900, due on October 20, 2026. Late payments incur a 1.5% fee."
QUOTE = "$900, due on October 20, 2026"


def test_tone_is_friendly_up_to_14_days_then_firm():
    assert choose_tone(1) == "friendly"
    assert choose_tone(14) == "friendly"
    assert choose_tone(15) == "firm"


def test_good_firm_draft_passes():
    draft = {"body": f'This is 18 days late. Per our contract, "{QUOTE}". The late fee now applies.',
             "contract_quote": QUOTE}
    assert check_draft(draft, CONTRACT, "firm", 18, "1.5%") == []


def test_friendly_draft_must_not_mention_late_fees():
    draft = {"body": f'Quick nudge about "{QUOTE}". Note a late fee may apply.', "contract_quote": QUOTE}
    assert any("friendly" in p for p in check_draft(draft, CONTRACT, "friendly", 5, "1.5%"))


def test_firm_draft_must_state_days_late_and_fee_and_not_say_gently():
    draft = {"body": f'Gently reminding you about "{QUOTE}".', "contract_quote": QUOTE}
    problems = " ".join(check_draft(draft, CONTRACT, "firm", 18, "1.5%"))
    assert "18 days late" in problems and "late fee" in problems and "gently" in problems


def test_firm_draft_must_not_call_itself_friendly():
    draft = {"body": f'This is a friendly reminder: 18 days late. "{QUOTE}" The late fee applies.',
             "contract_quote": QUOTE}
    assert any("friendly" in p for p in check_draft(draft, CONTRACT, "firm", 18, "1.5%"))


def test_invented_quote_is_rejected():
    draft = {"body": 'As agreed, "$5,000 due yesterday".', "contract_quote": "$5,000 due yesterday"}
    assert any("not copied exactly" in p for p in check_draft(draft, CONTRACT, "friendly", 3, None))
