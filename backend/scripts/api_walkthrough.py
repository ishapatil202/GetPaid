"""
Walk through the whole backend flow against the running server.

1. In one terminal:   uvicorn app.main:app --reload --app-dir backend
2. In another:        python backend/scripts/api_walkthrough.py
"""
import sys
from pathlib import Path

import httpx

API = "http://localhost:8000"
SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "contract_01.txt"


def show_issues(contract):
    if not contract["issues"]:
        print("   ✅ No problems")
    for issue in contract["issues"]:
        print(f"   [{issue['severity']}] {issue['message']}")
    print(f"   Ready to send: {'YES' if contract['can_send'] else 'NO'}")


def main():
    client = httpx.Client(base_url=API, timeout=120)
    try:
        client.get("/health").raise_for_status()
    except httpx.ConnectError:
        sys.exit("❌ The server isn't running. Start it first: uvicorn app.main:app --reload --app-dir backend")

    print("1. Demo login...")
    login = client.post("/auth/demo").json()
    client.headers["Authorization"] = f"Bearer {login['token']}"
    print(f"   ✅ Logged in as {login['name']}")

    print("2. Uploading the sample contract (AI is reading it, ~10 seconds)...")
    response = client.post("/contracts", json={"text": SAMPLE.read_text()})
    if response.status_code != 200:
        sys.exit(f"❌ {response.status_code}: {response.text}")
    contract = response.json()
    print(f"   ✅ Contract #{contract['id']}: {contract['title']}")
    for m in contract["milestones"]:
        print(f"   - {m['title']}: {m['amount']:,.2f} due {m['due_date'] or '(no date)'}")
    show_issues(contract)

    print("3. Fixing the missing due date (like a user would on the review screen)...")
    missing = [m for m in contract["milestones"] if not m["due_date"]]
    for m in missing:
        contract = client.patch(f"/milestones/{m['id']}", json={"due_date": "2026-12-31"}).json()
        print(f"   ✅ Set '{m['title']}' due 2026-12-31")
    show_issues(contract)

    print("4. Sending PayPal invoices...")
    response = client.post(f"/contracts/{contract['id']}/send")
    if response.status_code != 200:
        sys.exit(f"❌ {response.status_code}: {response.text}")
    contract = response.json()
    for m in contract["milestones"]:
        inv = m["invoice"]
        print(f"   ✅ {m['title']}: {inv['status']}  {inv['pay_link']}")

    print("5. Checking status with PayPal...")
    refreshed = client.post("/invoices/refresh").json()
    print(f"   {len(refreshed['changed'])} status changes")

    print("6. Dashboard:")
    for key, value in client.get("/dashboard").json().items():
        print(f"   {key:15} {value}")

    print("\n🎉 Backend works end to end. Pay one of the links above as the sandbox buyer,")
    print("   then run:  python backend/scripts/api_walkthrough.py --refresh")


def refresh_only():
    client = httpx.Client(base_url=API, timeout=60)
    client.headers["Authorization"] = f"Bearer {client.post('/auth/demo').json()['token']}"
    result = client.post("/invoices/refresh").json()
    for change in result["changed"]:
        print(f"   {change['invoice']}: {change['from']} -> {change['to']}")
    for key, value in client.get("/dashboard").json().items():
        print(f"   {key:15} {value}")


if __name__ == "__main__":
    refresh_only() if "--refresh" in sys.argv else main()
