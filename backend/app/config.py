"""Settings loaded from the .env file in the project root (or from Render's environment)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

# AI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
PROMPT_VERSION = "v3"  # v2: real nulls, clean quotes, evidence; v3: terms/late fee use contract wording

# PayPal
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
PAYPAL_ENV = os.getenv("PAYPAL_ENV", "sandbox")
PAYPAL_BASE_URL = "https://api-m.paypal.com" if PAYPAL_ENV == "live" else "https://api-m.sandbox.paypal.com"
# In sandbox, invoices go to this test buyer so the demo can actually pay them.
PAYPAL_BUYER_EMAIL = os.getenv("PAYPAL_BUYER_EMAIL", "")
# ID of the webhook registered in the PayPal developer dashboard (used to verify webhook signatures)
PAYPAL_WEBHOOK_ID = os.getenv("PAYPAL_WEBHOOK_ID", "")

# App
SECRET_KEY = os.getenv("SECRET_KEY") or "dev-only-secret"
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{ROOT / 'backend' / 'getpaid.db'}"
FRONTEND_ORIGINS = [o.strip() for o in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
FRONTEND_ORIGIN_REGEX = os.getenv("FRONTEND_ORIGIN_REGEX") or None
