"""
Step 1: PayPal sandbox test for GetPaid.

Creates one test invoice, sends it to your sandbox buyer (Personal account),
and prints a link where you can pay it.

Run:           python3 spike/paypal_test.py
Check status:  python3 spike/paypal_test.py --check INVOICE_ID

Uses only Python's standard library, so nothing needs to be installed.
"""
import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

BASE_URL = "https://api-m.sandbox.paypal.com"  # sandbox only, never real money
ROOT = Path(__file__).resolve().parent.parent


def load_env():
    """Read KEY=value lines from the .env file into environment variables."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        sys.exit("No .env file found in the project folder.")
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

    missing = [k for k in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_BUYER_EMAIL")
               if not os.environ.get(k)]
    if missing:
        sys.exit(f"Please fill these in your .env file: {', '.join(missing)}")


def make_ssl_context():
    try:
        import certifi  # used if available; fixes certificate errors on some Macs
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_CONTEXT = make_ssl_context()


def call(method, path, token=None, body=None, form=None, basic=None, headers=None, allow_fail=False):
    """Send one request to PayPal and return the JSON reply."""
    all_headers = dict(headers or {})
    data = None
    if form is not None:
        data = form.encode()
        all_headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        all_headers["Content-Type"] = "application/json"
    if basic:
        all_headers["Authorization"] = "Basic " + basic
    if token:
        all_headers["Authorization"] = "Bearer " + token

    request = urllib.request.Request(BASE_URL + path, data=data, headers=all_headers, method=method)
    try:
        with urllib.request.urlopen(request, context=SSL_CONTEXT, timeout=30) as response:
            raw = response.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        if allow_fail:
            return None
        print(f"\n❌ PayPal returned an error ({error.code}) for {method} {path}")
        print(error.read().decode())
        sys.exit(1)
    except urllib.error.URLError as error:
        print(f"\n❌ Could not reach PayPal: {error.reason}")
        if "CERTIFICATE_VERIFY_FAILED" in str(error.reason):
            print("Fix: open Finder -> Applications -> Python 3.12 -> double-click "
                  "'Install Certificates.command', then run this script again.")
        sys.exit(1)


def get_access_token():
    """Step A: log in to PayPal with the Client ID and Secret."""
    credentials = f"{os.environ['PAYPAL_CLIENT_ID']}:{os.environ['PAYPAL_CLIENT_SECRET']}"
    basic = base64.b64encode(credentials.encode()).decode()
    reply = call("POST", "/v1/oauth2/token", form="grant_type=client_credentials", basic=basic)
    has_invoicing = "invoicing" in reply.get("scope", "")
    print(f"    Invoicing permission on this app: {'YES' if has_invoicing else 'NO'}")
    return reply["access_token"]


def create_invoice(token):
    """Step B: create a draft invoice for one milestone."""
    generated = call("POST", "/v2/invoicing/generate-next-invoice-number", token=token, allow_fail=True)
    number = (generated or {}).get("invoice_number")
    due_date = (date.today() + timedelta(days=14)).isoformat()
    invoice = {
        "detail": {
            "currency_code": "USD",
            "note": "Test invoice from GetPaid (Step 1).",
            "payment_term": {"term_type": "DUE_ON_DATE_SPECIFIED", "due_date": due_date},
        },
        "primary_recipients": [
            {"billing_info": {"email_address": os.environ["PAYPAL_BUYER_EMAIL"]}}
        ],
        "items": [
            {
                "name": "Milestone 1 - Logo design",
                "quantity": "1",
                "unit_amount": {"currency_code": "USD", "value": "120.00"},
            }
        ],
    }
    if number:
        invoice["detail"]["invoice_number"] = number
    reply = call("POST", "/v2/invoicing/invoices", token=token, body=invoice,
                 headers={"Prefer": "return=representation"})
    invoice_id = reply.get("id")
    if not invoice_id:  # older reply style: the id is at the end of the link
        invoice_id = reply["href"].rstrip("/").split("/")[-1]
    return invoice_id, number or invoice_id


def send_invoice(token, invoice_id):
    """Step C: send the invoice to the client (your sandbox Personal account)."""
    call("POST", f"/v2/invoicing/invoices/{invoice_id}/send", token=token,
         body={"send_to_invoicer": True, "send_to_recipient": True})


def show_invoice(token, invoice_id):
    """Print the invoice status and the link the client uses to pay."""
    invoice = call("GET", f"/v2/invoicing/invoices/{invoice_id}", token=token)
    amount = invoice.get("amount", {})
    pay_link = invoice.get("detail", {}).get("metadata", {}).get("recipient_view_url", "(not available yet)")
    print(f"   Invoice ID: {invoice_id}")
    print(f"   Status:     {invoice.get('status')}")
    print(f"   Amount:     {amount.get('value')} {amount.get('currency_code')}")
    print(f"   Pay link:   {pay_link}")


def main():
    load_env()
    print("1/4 Logging in to PayPal sandbox...")
    token = get_access_token()
    print("    ✅ Logged in")

    if len(sys.argv) == 3 and sys.argv[1] == "--check":
        print("Checking invoice...")
        show_invoice(token, sys.argv[2])
        return

    print("2/4 Creating a draft invoice...")
    invoice_id, number = create_invoice(token)
    print(f"    ✅ Created invoice #{number}")

    print("3/4 Sending it to your sandbox buyer...")
    send_invoice(token, invoice_id)
    print("    ✅ Sent")

    print("4/4 Invoice details:")
    show_invoice(token, invoice_id)
    print("\n🎉 PayPal works! Open the pay link, log in as your sandbox PERSONAL account, and pay.")
    print(f"Then check it with:  python3 spike/paypal_test.py --check {invoice_id}")


if __name__ == "__main__":
    main()
