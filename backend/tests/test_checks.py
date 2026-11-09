"""The money checks: the rules that decide whether invoices can be sent."""
from types import SimpleNamespace as M

from app.checks import BLOCKING_CODES, payment_checks


def codes(issues):
    return {i.code for i in issues}


def test_flags_payments_that_do_not_add_up_to_the_total():
    issues = payment_checks("a@b.co", 3000, "USD", [M(title="A", amount=600, due_date="2099-01-01", due_rule=None),
                                                    M(title="B", amount=2200, due_date="2099-02-01", due_rule=None)])
    assert "total_mismatch" in codes(issues)
    assert "200.00" in next(i.message for i in issues if i.code == "total_mismatch")


def test_no_flags_when_everything_is_right():
    issues = payment_checks("a@b.co", 1500, "USD", [M(title="A", amount=1500, due_date="2099-01-01", due_rule=None)])
    assert issues == []


def test_missing_due_date_blocks_sending_and_shows_the_contract_rule():
    issues = payment_checks("a@b.co", 1000, "USD",
                            [M(title="Guidelines", amount=1000, due_date=None, due_rule="15 days after delivery")])
    issue = next(i for i in issues if i.code == "missing_due_date")
    assert "15 days after delivery" in issue.message
    assert "missing_due_date" in BLOCKING_CODES


def test_missing_client_email_blocks_sending():
    issues = payment_checks(None, None, "USD", [M(title="A", amount=10, due_date="2099-01-01", due_rule=None)])
    assert "missing_client_email" in codes(issues)


def test_past_due_date_is_only_a_note_not_a_blocker():
    issues = payment_checks("a@b.co", None, "USD", [M(title="A", amount=10, due_date="2020-01-01", due_rule=None)])
    assert codes(issues) == {"due_date_past"}
    assert "due_date_past" not in BLOCKING_CODES


def test_zero_amount_and_unreadable_date_are_flagged():
    issues = payment_checks("a@b.co", None, "USD", [M(title="A", amount=0, due_date="next Tuesday", due_rule=None)])
    assert {"bad_amount", "bad_due_date"} <= codes(issues)
