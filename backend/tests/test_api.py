"""End-to-end API flows, with fake AI and fake PayPal (see conftest.py)."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from conftest import BRIGHTLEAF_TEXT, SAMPLES


def _days_from_today(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def _upload_brightleaf(client):
    response = client.post("/contracts", json={"text": BRIGHTLEAF_TEXT})
    assert response.status_code == 200, response.text
    return response.json()


def test_health_and_login_required():
    from app.main import app
    with TestClient(app) as anonymous:
        assert anonymous.get("/health").json()["ok"] is True
        assert anonymous.get("/contracts").status_code == 401


def test_contract_review_edit_send_and_get_paid(client):
    contract = _upload_brightleaf(client)
    codes = {i["code"] for i in contract["issues"]}
    assert {"total_mismatch", "missing_due_date"} <= codes
    assert contract["can_send"] is False  # a payment has no due date yet

    # Sending is refused until the problem is fixed
    assert client.post(f"/contracts/{contract['id']}/send").status_code == 400

    # The freelancer sets the missing date: the blocking warning disappears
    missing = next(m for m in contract["milestones"] if m["due_date"] is None)
    contract = client.patch(f"/milestones/{missing['id']}", json={"due_date": _days_from_today(30)}).json()
    assert contract["can_send"] is True
    assert "missing_due_date" not in {i["code"] for i in contract["issues"]}

    # Send: one PayPal invoice per payment, each quoting the contract
    contract = client.post(f"/contracts/{contract['id']}/send").json()
    assert contract["status"] == "sent"
    assert all(m["invoice"]["status"] == "SENT" for m in contract["milestones"])
    sent = list(client.paypal.invoices.values())
    assert len(sent) == 3
    assert all(inv["item_description"].startswith('Per contract: "') for inv in sent)
    assert all(inv["recipient_email"] == "buyer@example.com" for inv in sent)  # sandbox test buyer

    # Sent invoices can't be edited any more
    first = contract["milestones"][0]
    assert client.patch(f"/milestones/{first['id']}", json={"amount": 1}).status_code == 409

    # The client pays one invoice; "Check for payments" picks it up
    client.paypal.mark_paid(first["invoice"]["paypal_invoice_id"])
    refreshed = client.post("/invoices/refresh").json()
    assert refreshed["changed"] == [{"invoice": first["invoice"]["paypal_invoice_id"], "from": "SENT", "to": "PAID"}]
    dashboard = client.get("/dashboard").json()
    assert dashboard["paid"] == 600 and dashboard["paid_count"] == 1 and dashboard["invoiced"] == 2800


def test_reminder_agent_drafts_waits_for_approval_and_does_not_nag(client):
    contract = _upload_brightleaf(client)
    m1, m2, m3 = contract["milestones"]
    client.patch(f"/milestones/{m1['id']}", json={"due_date": _days_from_today(-20)})  # 20 days late
    client.patch(f"/milestones/{m2['id']}", json={"due_date": _days_from_today(-5)})   # 5 days late
    client.patch(f"/milestones/{m3['id']}", json={"due_date": _days_from_today(30)})   # not due yet
    assert client.post(f"/contracts/{contract['id']}/send").status_code == 200

    result = client.post("/agent/run").json()
    assert result["run"]["late_found"] == 2 and result["run"]["drafts_created"] == 2
    tones = {r["days_overdue"]: r["tone"] for r in result["reminders"]}
    assert tones == {20: "firm", 5: "friendly"}
    assert all(r["status"] == "draft" and r["quote_verified"] for r in result["reminders"])
    assert client.paypal.reminders == []  # nothing is sent without approval

    firm = next(r for r in result["reminders"] if r["tone"] == "firm")
    approved = client.post(f"/reminders/{firm['id']}/approve").json()
    assert approved["status"] == "sent"
    assert len(client.paypal.reminders) == 1
    assert client.post(f"/reminders/{firm['id']}/approve").status_code == 409  # can't send twice

    # Running again creates nothing new: one is pending approval, one was just sent
    again = client.post("/agent/run").json()
    assert again["run"]["drafts_created"] == 0


def test_pdf_upload_and_bad_file(client):
    pdf = (SAMPLES / "brightleaf_contract.pdf").read_bytes()
    ok = client.post("/contracts/upload", files={"file": ("brightleaf.pdf", pdf, "application/pdf")})
    assert ok.status_code == 200, ok.text
    assert "December 4, 2026" in ok.json()["raw_text"]

    bad = client.post("/contracts/upload", files={"file": ("fake.pdf", b"not a pdf", "application/pdf")})
    assert bad.status_code == 422


def test_ask_your_invoices_answer_is_sanity_checked(client, monkeypatch):
    from app import ask

    def fake_ai(*args, **kwargs):
        return ({"status": "bogus", "client_contains": "  Northwind ", "payment_contains": "",
                 "amount_min": 2000, "amount_max": 1000, "days_late_min": -3,
                 "sort_by": "amount", "sort_direction": None, "explanation": "Test."}, "fake-model", 3)

    monkeypatch.setattr(ask, "structured_call", fake_ai)
    answer = client.post("/invoices/ask", json={"question": "big ones from northwind"}).json()
    assert answer["status"] == "all"                                   # unknown status rejected
    assert (answer["amount_min"], answer["amount_max"]) == (1000, 2000)  # swapped into order
    assert answer["days_late_min"] is None                               # negative removed
    assert answer["client_contains"] == "Northwind" and answer["payment_contains"] is None
    assert answer["sort_direction"] == "desc"


def test_users_cannot_see_each_others_contracts(client):
    from app.auth import create_token
    from app.database import SessionLocal
    from app.models import User

    contract = _upload_brightleaf(client)
    with SessionLocal() as db:
        other = User(email="other@example.com", name="Someone Else")
        db.add(other)
        db.commit()
        other_token = create_token(other.id)
    response = client.get(f"/contracts/{contract['id']}", headers={"Authorization": f"Bearer {other_token}"})
    assert response.status_code == 404
