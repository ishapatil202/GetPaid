"""
Test setup. Every test runs WITHOUT the real AI or the real PayPal:
both are replaced by fakes, so tests are free, fast and need no internet or keys.
"""
import os
import re
import tempfile
from pathlib import Path

# Must be set before the app is imported (config reads them at import time).
_tmp = tempfile.mkdtemp()
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_tmp}/test.db",
    "OPENAI_API_KEY": "test-key-never-used",
    "PAYPAL_CLIENT_ID": "test-client-id",
    "PAYPAL_CLIENT_SECRET": "test-client-secret",
    "PAYPAL_BUYER_EMAIL": "buyer@example.com",
    "PAYPAL_ENV": "sandbox",
    "SECRET_KEY": "test-secret-key",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.schemas import ContractExtraction, ExtractionResult, Milestone, MoneyField, TextField  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
BRIGHTLEAF_TEXT = (SAMPLES / "contract_01.txt").read_text()


def brightleaf_extraction() -> ContractExtraction:
    """What a correct AI answer for the Brightleaf contract looks like."""
    return ContractExtraction(
        client_name=TextField(value="Brightleaf Coffee Co.", source_quote="Brightleaf Coffee Co."),
        client_email=TextField(value="ap@brightleaf.example", source_quote="billing contact ap@brightleaf.example"),
        freelancer_name=TextField(value="Maria Lopez Design", source_quote="Maria Lopez Design"),
        currency="USD",
        contract_total=MoneyField(value=3000, source_quote="The total fee for this project is $3,000 USD"),
        payment_terms=TextField(value="Net 15", source_quote="(Net 15)"),
        late_fee=TextField(value="5% of the overdue amount", source_quote="a late fee of 5% of the overdue amount"),
        milestones=[
            Milestone(title="Brand discovery workshop and moodboard", amount=600, due_date="2026-11-20", due_rule=None,
                      source_quote="Brand discovery workshop and moodboard: $600, due on November 20, 2026."),
            Milestone(title="Primary logo design", amount=1200, due_date="2026-12-04", due_rule=None,
                      source_quote="Primary logo design with two rounds of revisions: $1,200, due on December 4, 2026."),
            Milestone(title="Brand guidelines document", amount=1000, due_date=None,
                      due_rule="within 15 days of final delivery",
                      source_quote="Brand guidelines document: $1,000, due within 15 days of final delivery."),
        ],
        ai_concerns=[],
    )


def fake_extract(text: str) -> ExtractionResult:
    """Stands in for the AI call. Our real verification code still runs on the result."""
    from app.extraction import verify
    data = brightleaf_extraction()
    highlights, issues = verify(text, data)
    return ExtractionResult(extraction=data, highlights=highlights, issues=issues, model="fake-model",
                            prompt_version="test", latency_ms=1, input_tokens=0, output_tokens=0)


def fake_reminder_call(system, user, name, schema, temperature=0.0):
    """Stands in for the AI writing a reminder: follows the rules, so drafts pass our checks."""
    days = re.search(r"Days late: (\d+)", user).group(1)
    quote = re.search(r'Contract sentence for this payment: "(.*)"', user).group(1)
    firm = "Write a firm reminder" in user
    body = f'Hi Brightleaf Coffee Co. team,\n\nThis payment is {days} days late. As agreed, "{quote}"'
    body += " The late fee now applies. Please pay within 5 business days." if firm else " Just a friendly nudge!"
    body += "\n\nBest regards,\nMaria Lopez Design"
    return {"subject": "Payment reminder", "body": body, "contract_quote": quote}, "fake-model", 5


class FakePayPal:
    """Behaves like our PayPalClient, but keeps invoices in memory."""

    def __init__(self):
        self.invoices: dict[str, dict] = {}
        self.reminders: list[tuple] = []

    def create_invoice(self, **fields):
        invoice_id = f"INV2-TEST-{len(self.invoices) + 1:04d}"
        self.invoices[invoice_id] = {"status": "DRAFT", **fields}
        return invoice_id

    def send_invoice(self, invoice_id):
        self.invoices[invoice_id]["status"] = "SENT"

    def get_invoice(self, invoice_id):
        inv = self.invoices[invoice_id]
        result = {"id": invoice_id, "status": inv["status"],
                  "detail": {"invoice_number": invoice_id[-4:],
                             "metadata": {"recipient_view_url": f"https://sandbox.example/pay/{invoice_id}"}}}
        if inv["status"] == "PAID":
            result["payments"] = {"transactions": [{"payment_date": "2026-11-08T10:00:00Z"}]}
        return result

    def remind(self, invoice_id, subject, note):
        self.reminders.append((invoice_id, subject, note))

    def mark_paid(self, invoice_id):
        self.invoices[invoice_id]["status"] = "PAID"


@pytest.fixture
def client(monkeypatch):
    """A logged-in test client with a fresh, empty database and fake AI + PayPal."""
    from app import agent, main
    from app.database import Base, engine

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    paypal = FakePayPal()
    monkeypatch.setattr(main, "extract_contract", fake_extract)
    monkeypatch.setattr(main, "get_paypal", lambda: paypal)
    monkeypatch.setattr(agent, "structured_call", fake_reminder_call)

    with TestClient(main.app) as test_client:
        token = test_client.post("/auth/demo").json()["token"]
        test_client.headers["Authorization"] = f"Bearer {token}"
        test_client.paypal = paypal
        yield test_client
