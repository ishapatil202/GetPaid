"""PayPal webhooks: signature check, idempotency, status sync."""
import json
from datetime import date, timedelta

from conftest import BRIGHTLEAF_TEXT

HEADERS = {
    "paypal-auth-algo": "SHA256withRSA",
    "paypal-cert-url": "https://api.sandbox.paypal.com/cert.pem",
    "paypal-transmission-id": "tx-1",
    "paypal-transmission-time": "2026-11-11T10:00:00Z",
    "paypal-transmission-sig": "good-signature",
}


def _sent_invoice_id(client):
    contract = client.post("/contracts", json={"text": BRIGHTLEAF_TEXT}).json()
    missing = next(m for m in contract["milestones"] if not m["due_date"])
    client.patch(f"/milestones/{missing['id']}", json={"due_date": (date.today() + timedelta(days=30)).isoformat()})
    contract = client.post(f"/contracts/{contract['id']}/send").json()
    return contract["milestones"][0]["invoice"]["paypal_invoice_id"]


def _event(event_id, invoice_id):
    return json.dumps({"id": event_id, "event_type": "INVOICING.INVOICE.PAID",
                       "resource": {"invoice": {"id": invoice_id}}})


def test_verified_webhook_marks_invoice_paid_once(client):
    invoice_id = _sent_invoice_id(client)
    client.paypal.mark_paid(invoice_id)

    first = client.post("/webhooks/paypal", content=_event("WH-EVT-1", invoice_id), headers=HEADERS)
    assert first.status_code == 200 and first.json()["result"] == "SENT -> PAID"
    paid = [i for i in client.get("/invoices").json() if i["paypal_invoice_id"] == invoice_id][0]
    assert paid["status"] == "PAID" and paid["paid_at"]

    again = client.post("/webhooks/paypal", content=_event("WH-EVT-1", invoice_id), headers=HEADERS)
    assert again.json() == {"ok": True, "duplicate": True}  # PayPal retries are processed once


def test_webhook_with_bad_signature_is_rejected(client):
    invoice_id = _sent_invoice_id(client)
    client.paypal.mark_paid(invoice_id)
    forged = {**HEADERS, "paypal-transmission-sig": "forged"}
    response = client.post("/webhooks/paypal", content=_event("WH-EVT-2", invoice_id), headers=forged)
    assert response.status_code == 400
    still = [i for i in client.get("/invoices").json() if i["paypal_invoice_id"] == invoice_id][0]
    assert still["status"] == "SENT"  # a fake "paid" message changes nothing


def test_webhook_for_unknown_invoice_is_recorded_and_ignored(client):
    response = client.post("/webhooks/paypal", content=_event("WH-EVT-3", "INV2-NOT-OURS"), headers=HEADERS)
    assert response.status_code == 200 and response.json()["result"] == "unknown invoice"
