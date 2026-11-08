"""
Wipe the local database so you can record a clean demo.
Stop the server first, run this, then start the server again.

    python backend/scripts/reset_demo.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: E402,F401  (registers the tables)
from app.database import Base, engine  # noqa: E402

if input("Delete ALL contracts, invoices and reminders in the local database? (yes/no) ").strip() == "yes":
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    print("Done. The database is empty. (Invoices already sent stay in your PayPal sandbox.)")
else:
    print("Nothing changed.")
