"""
The reminder agent.

For each open invoice it:
  1. asks PayPal for the real status (tool: paypal.get_invoice)
  2. works out how late it is from the contract's due date
  3. picks a tone with a simple, predictable rule (friendly, or firm after 14 days)
  4. asks the AI to draft a reminder that quotes the contract (tool: ai.draft_reminder)
  5. checks the quote really exists in the contract
  6. saves it as a DRAFT. Nothing is sent until the user approves it.
Every step is logged, so the user can see exactly what the agent did and why.
"""
import logging
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .extraction import find_span
from .llm import reminder_call
from .models import AgentRun, Invoice, Reminder, User
from .paypal_client import PayPalClient, PayPalError, invoice_summary

logger = logging.getLogger("getpaid")

FIRM_AFTER_DAYS = 14
RECENT_REMINDER_DAYS = 3
CLOSED = {"PAID", "MARKED_AS_PAID", "CANCELLED", "REFUNDED", "MARKED_AS_REFUNDED"}

REMINDER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["subject", "body", "contract_quote"],
    "properties": {
        "subject": {"type": "string", "description": "Short email subject line"},
        "body": {"type": "string", "description": "The reminder message, plain text"},
        "contract_quote": {"type": "string", "description": "The exact contract words quoted in the body"},
    },
}

SYSTEM_PROMPT = """You write payment reminders from a freelancer to a client.
Always:
- Greet the client by name, e.g. "Hi Northwind Yoga Studio team,".
- Plain text, under 120 words. No placeholders like [Name]. No links (PayPal adds the payment button).
- Quote exactly ONE phrase from the contract, copied character for character, inside double quotes. Put the identical phrase in contract_quote.
- Never invent facts, amounts, dates or fees.
- End with "Best regards," and the freelancer's name on the next line.
Tone "friendly": warm and short. Assume the payment was simply missed. Do NOT mention late fees, penalties or deadlines.
Tone "firm": polite but direct. Never say "gently". State exactly how many days late the payment is. If the contract has a late fee and the payment is past its threshold, say clearly that the late fee now applies and state its terms. Ask for payment within 5 business days."""


def choose_tone(days_overdue: int) -> str:
    return "firm" if days_overdue > FIRM_AFTER_DAYS else "friendly"


def check_draft(draft: dict, contract_text: str, tone: str, days_overdue: int, late_fee: str | None) -> list[str]:
    """Our own rules the draft must pass. Problems are sent back to the AI to fix."""
    body = draft.get("body", "")
    quote = (draft.get("contract_quote") or "").strip()
    problems = []
    if not quote or find_span(contract_text, quote) is None:
        problems.append("contract_quote is not copied exactly from the contract")
    elif quote not in body:
        problems.append("the body must contain contract_quote exactly, inside double quotes")
    if tone == "friendly" and re.search(r"late fee|penalt|business days", body, re.IGNORECASE):
        problems.append("a friendly reminder must not mention late fees, penalties or deadlines")
    if tone == "firm":
        if str(days_overdue) not in body:
            problems.append(f"say that the payment is {days_overdue} days late")
        if late_fee and "fee" not in body.lower():
            problems.append("say that the contract's late fee now applies")
        if "gently" in body.lower():
            problems.append("a firm reminder must not say 'gently'")
    return problems


def draft_reminder(invoice: Invoice, days_overdue: int, tone: str) -> dict:
    """Ask the AI for a draft, check it, and give it one chance to fix any problems."""
    milestone = invoice.milestone
    contract = milestone.contract
    facts = (
        f"Freelancer: {contract.freelancer_name or 'the freelancer'}\n"
        f"Client: {contract.client_name or 'the client'}\n"
        f"Payment: {milestone.title}\n"
        f"Amount: {invoice.amount:.2f} {invoice.currency}\n"
        f"Due date: {invoice.due_date}\n"
        f"Days late: {days_overdue}\n"
        f"Payment terms: {contract.payment_terms or 'not stated'}\n"
        f"Late fee: {contract.late_fee or 'none in the contract'}\n"
        f'Contract sentence for this payment: "{milestone.source_quote}"\n'
    )
    prompt = f"Write a {tone} reminder.\n\n{facts}\nFULL CONTRACT:\n{contract.raw_text}"

    attempts, total_ms, problems = 0, 0, []
    while True:
        attempts += 1
        data, model, latency_ms = reminder_call(SYSTEM_PROMPT, prompt, temperature=0.2)
        total_ms += latency_ms
        problems = check_draft(data, contract.raw_text, tone, days_overdue, contract.late_fee)
        if not problems or attempts >= 2:
            break
        prompt += ("\n\nYour previous draft had these problems: " + "; ".join(problems)
                   + ". Write it again and fix them.")

    # Guarantee the sign-off, whatever the model did.
    name = contract.freelancer_name
    if name and name not in data["body"]:
        data["body"] = data["body"].rstrip() + f"\n\nBest regards,\n{name}"

    quote = (data.get("contract_quote") or "").strip()
    data["quote_verified"] = bool(quote) and find_span(contract.raw_text, quote) is not None
    data.update(model=model, latency_ms=total_ms, attempts=attempts, problems=problems)
    return data


def _as_utc(value: datetime | None):
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def run_reminder_agent(db: Session, user: User, paypal: PayPalClient):
    today = date.today()
    now = datetime.now(timezone.utc)
    run = AgentRun(user_id=user.id, steps=[], summary="", invoices_checked=0, late_found=0, drafts_created=0)
    steps: list[dict] = []
    drafts: list[Reminder] = []

    def log(tool: str, summary: str, ok: bool = True):
        steps.append({"tool": tool, "summary": summary, "ok": ok})
        logger.info("agent step %s: %s", tool, summary)

    logger.info("agent run started")

    invoices = db.query(Invoice).filter(Invoice.user_id == user.id).all()
    open_invoices = [i for i in invoices if i.status not in CLOSED]
    log("database.list_open_invoices", f"Found {len(open_invoices)} open invoices out of {len(invoices)}.")

    for inv in open_invoices:
        milestone = inv.milestone
        label = f"{milestone.title} ({milestone.contract.client_name or 'client'})"

        # Tool 1: real status from PayPal
        try:
            summary = invoice_summary(paypal.get_invoice(inv.paypal_invoice_id))
        except PayPalError as error:
            log("paypal.get_invoice", f"{label}: couldn't check PayPal ({error.message}).", ok=False)
            continue
        run.invoices_checked += 1
        if summary["status"] != inv.status:
            inv.status = summary["status"]
            if inv.status in ("PAID", "MARKED_AS_PAID"):
                inv.paid_at = now
        if inv.status in CLOSED:
            log("paypal.get_invoice", f"{label}: {inv.status.replace('_', ' ').lower()}. No reminder needed.")
            continue
        if not inv.due_date or inv.due_date >= today.isoformat():
            log("paypal.get_invoice", f"{label}: unpaid, due {inv.due_date or 'on receipt'}. Not late yet.")
            continue

        days = (today - date.fromisoformat(inv.due_date)).days
        run.late_found += 1
        log("paypal.get_invoice", f"{label}: unpaid and {days} days late.")

        # Don't nag: skip if a draft is waiting or a reminder went out recently
        earlier = db.query(Reminder).filter(Reminder.invoice_id == inv.id).all()
        if any(r.status == "draft" for r in earlier):
            log("database.check_reminders", f"{label}: a reminder is already waiting for your approval.")
            continue
        if any(r.status == "sent" and _as_utc(r.sent_at) and now - _as_utc(r.sent_at) < timedelta(days=RECENT_REMINDER_DAYS)
               for r in earlier):
            log("database.check_reminders", f"{label}: reminded in the last {RECENT_REMINDER_DAYS} days. Skipping.")
            continue

        # Rule: how firm to be
        tone = choose_tone(days)
        fee_note = " and mention the late fee" if tone == "firm" and milestone.contract.late_fee else ""
        log("rules.choose_tone", f"{label}: {days} days late, so write a {tone} reminder{fee_note}.")

        # Tool 2: AI drafts the reminder
        logger.info("agent drafting reminder for %s", label)
        try:
            draft = draft_reminder(inv, days, tone)
        except Exception as error:  # keep going with the other invoices
            log("ai.draft_reminder", f"{label}: drafting failed ({error}).", ok=False)
            continue
        verified = draft["quote_verified"]
        retried = " after 1 correction" if draft["attempts"] > 1 else ""
        log("ai.draft_reminder",
            f"{label}: drafted in {draft['latency_ms'] / 1000:.1f}s{retried}. "
            + ("Contract quote verified." if verified else "Contract quote NOT found in the contract. Please check it."),
            ok=verified)
        if draft["problems"]:
            log("rules.check_draft", f"{label}: still needs a human look: {'; '.join(draft['problems'])}.", ok=False)
        else:
            log("rules.check_draft", f"{label}: draft passed all checks (tone, quote, sign-off).")

        reminder = Reminder(
            user_id=user.id, invoice_id=inv.id, tone=tone, days_overdue=days,
            subject=draft["subject"], body=draft["body"], contract_quote=draft.get("contract_quote"),
            quote_verified=verified, status="draft",
        )
        db.add(reminder)
        drafts.append(reminder)
        run.drafts_created += 1

    run.summary = (f"Checked {run.invoices_checked} invoices with PayPal. {run.late_found} late. "
                   f"{run.drafts_created} new {'reminder' if run.drafts_created == 1 else 'reminders'} "
                   f"waiting for your approval.")
    run.steps = steps
    run.finished_at = datetime.now(timezone.utc)
    db.add(run)
    db.flush()
    for reminder in drafts:
        reminder.agent_run_id = run.id
    db.commit()
    return run, drafts
