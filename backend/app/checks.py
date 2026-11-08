"""
Money checks shared by the AI pipeline and the live review screen.
They work on any milestone object with: title, amount, due_date, due_rule.
"""
from datetime import date

from .schemas import Issue

# Problems that must be fixed before invoices can be sent.
BLOCKING_CODES = {"missing_client_email", "no_milestones", "missing_due_date", "bad_amount", "bad_due_date"}


def payment_checks(client_email, contract_total, currency, milestones, date_milestones=None):
    """milestones: all milestones (for the total). date_milestones: the ones whose dates to check."""
    issues: list[Issue] = []
    date_milestones = milestones if date_milestones is None else date_milestones

    if not client_email:
        issues.append(Issue(code="missing_client_email", severity="high",
                            message="No client email found. PayPal needs one to send the invoice."))
    if not milestones:
        issues.append(Issue(code="no_milestones", severity="high",
                            message="No payment milestones found in this contract."))

    milestone_sum = round(sum(m.amount for m in milestones), 2)
    if contract_total is not None and milestones and abs(milestone_sum - contract_total) > 0.01:
        issues.append(Issue(code="total_mismatch", severity="high",
                            message=(f"Milestones add up to {milestone_sum:,.2f} {currency}, but the contract "
                                     f"total is {contract_total:,.2f} {currency} "
                                     f"(difference {abs(contract_total - milestone_sum):,.2f}).")))

    today = date.today()
    for m in date_milestones:
        if m.amount <= 0:
            issues.append(Issue(code="bad_amount", severity="high",
                                message=f"'{m.title}' has an amount of {m.amount}, which can't be invoiced."))
        if not m.due_date:
            rule = f" (contract says: {m.due_rule})" if m.due_rule else ""
            issues.append(Issue(code="missing_due_date", severity="medium",
                                message=f"'{m.title}' has no fixed due date{rule}. Set one before sending."))
            continue
        try:
            due = date.fromisoformat(m.due_date)
        except ValueError:
            issues.append(Issue(code="bad_due_date", severity="medium",
                                message=f"'{m.title}' has an unreadable due date: {m.due_date}."))
            continue
        if due < today:
            issues.append(Issue(code="due_date_past", severity="low",
                                message=f"'{m.title}' was due on {m.due_date}, which is already in the past."))
    return issues
