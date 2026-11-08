"""Small PayPal Invoicing v2 client (the Step 1 test script, made reusable)."""
import time
from datetime import date

import httpx

from . import config


class PayPalError(Exception):
    def __init__(self, status: int, message: str, body=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.body = body


class PayPalClient:
    def __init__(self, client_id: str, client_secret: str, base_url: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url
        self._token = None
        self._token_expires = 0.0

    # ----- low level -----

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        response = httpx.post(
            f"{self.base_url}/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.client_secret),
            timeout=30,
        )
        if response.status_code >= 400:
            raise PayPalError(response.status_code, "PayPal login failed. Check PAYPAL_CLIENT_ID / SECRET.",
                              response.text)
        body = response.json()
        self._token = body["access_token"]
        self._token_expires = time.time() + body.get("expires_in", 300)
        return self._token

    def _request(self, method: str, path: str, json=None, headers=None):
        all_headers = {"Authorization": f"Bearer {self._access_token()}", **(headers or {})}
        response = httpx.request(method, f"{self.base_url}{path}", json=json, headers=all_headers, timeout=30)
        if response.status_code >= 400:
            try:
                body = response.json()
                message = body.get("message") or body.get("error_description") or response.text
                details = body.get("details") or []
                if details and isinstance(details[0], dict):
                    message += " " + (details[0].get("description") or details[0].get("issue") or "")
            except ValueError:
                body, message = response.text, response.text
            raise PayPalError(response.status_code, f"PayPal error {response.status_code}: {message}", body)
        return response.json() if response.content else {}

    # ----- invoicing -----

    def create_invoice(self, *, recipient_email, recipient_name, currency, item_name,
                       item_description, amount, due_date, note) -> str:
        if due_date and date.fromisoformat(due_date) >= date.today():
            payment_term = {"term_type": "DUE_ON_DATE_SPECIFIED", "due_date": due_date}
        else:
            payment_term = {"term_type": "DUE_ON_RECEIPT"}
        billing_info = {"email_address": recipient_email}
        if recipient_name:
            billing_info["name"] = {"given_name": recipient_name[:140]}
        body = {
            "detail": {"currency_code": currency, "note": note[:4000], "payment_term": payment_term},
            "primary_recipients": [{"billing_info": billing_info}],
            "items": [{
                "name": item_name[:200],
                "description": item_description[:1000],
                "quantity": "1",
                "unit_amount": {"currency_code": currency, "value": f"{amount:.2f}"},
            }],
        }
        created = self._request("POST", "/v2/invoicing/invoices", json=body,
                                headers={"Prefer": "return=representation"})
        return created.get("id") or created["href"].rstrip("/").split("/")[-1]

    def send_invoice(self, invoice_id: str):
        self._request("POST", f"/v2/invoicing/invoices/{invoice_id}/send",
                      json={"send_to_invoicer": True, "send_to_recipient": True})

    def get_invoice(self, invoice_id: str) -> dict:
        return self._request("GET", f"/v2/invoicing/invoices/{invoice_id}")

    def remind(self, invoice_id: str, subject: str, note: str):
        self._request("POST", f"/v2/invoicing/invoices/{invoice_id}/remind",
                      json={"subject": subject[:4000], "note": note[:4000], "send_to_invoicer": True})


_client = None


def get_paypal() -> PayPalClient:
    global _client
    if not (config.PAYPAL_CLIENT_ID and config.PAYPAL_CLIENT_SECRET):
        raise PayPalError(500, "PayPal keys are missing in .env")
    if _client is None:
        _client = PayPalClient(config.PAYPAL_CLIENT_ID, config.PAYPAL_CLIENT_SECRET, config.PAYPAL_BASE_URL)
    return _client


def invoice_summary(invoice: dict) -> dict:
    """Pull the fields we store from a PayPal invoice."""
    detail = invoice.get("detail", {})
    paid_at = None
    transactions = (invoice.get("payments") or {}).get("transactions") or []
    if transactions:
        paid_at = transactions[-1].get("payment_date")
    return {
        "status": invoice.get("status", "UNKNOWN"),
        "invoice_number": detail.get("invoice_number"),
        "pay_link": (detail.get("metadata") or {}).get("recipient_view_url"),
        "paid_at": paid_at,
    }
