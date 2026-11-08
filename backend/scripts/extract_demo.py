"""
Try the AI brain on one contract.

Run from the project folder:
    python backend/scripts/extract_demo.py backend/samples/contract_01.txt
Add --json to see the raw result.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so "app" can be imported

import openai  # noqa: E402

from app import config  # noqa: E402
from app.extraction import extract_contract  # noqa: E402

ICONS = {"high": "🔴", "medium": "🟠", "low": "🟡"}


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python backend/scripts/extract_demo.py <contract.txt> [--json]")
    contract = Path(sys.argv[1]).read_text()
    print(f"Reading {sys.argv[1]} with {config.OPENAI_MODEL}...\n")

    try:
        result = extract_contract(contract)
    except openai.NotFoundError:
        print(f"❌ The model '{config.OPENAI_MODEL}' is not available on your account.")
        names = sorted(m.id for m in openai.OpenAI(api_key=config.OPENAI_API_KEY).models.list()
                       if "mini" in m.id)
        print("Models with 'mini' you can use (put one in .env as OPENAI_MODEL=...):")
        print("  " + "\n  ".join(names[:15]))
        return
    except openai.AuthenticationError:
        print("❌ OpenAI rejected the key. Check OPENAI_API_KEY in .env (no spaces or quotes).")
        return

    if "--json" in sys.argv:
        print(result.model_dump_json(indent=2))
        return

    data = result.extraction
    found = {h.field: h.found for h in result.highlights}
    mark = lambda name: "✓ quote found" if found.get(name) else "✗ no source"

    print("CONTRACT DETAILS")
    for name in ("client_name", "client_email", "freelancer_name", "contract_total", "payment_terms", "late_fee"):
        field = getattr(data, name)
        if field.value is not None:
            print(f"  {name:16} {str(field.value):38} {mark(name)}")
        else:
            print(f"  {name:16} {'(not in contract)':38}")
    print(f"  {'currency':16} {data.currency}")

    print("\nMILESTONES")
    for i, m in enumerate(data.milestones):
        due = m.due_date or f"no date ({m.due_rule})"
        print(f"  {i + 1}. {m.title:30} {m.amount:>10,.2f}   due {due:20} {mark(f'milestones[{i}]')}")

    print("\nCHECKS")
    if not result.issues:
        print("  ✅ No problems found")
    for issue in result.issues:
        print(f"  {ICONS.get(issue.severity, '•')} {issue.message}")

    print(f"\n{result.latency_ms} ms · {result.input_tokens} input + {result.output_tokens} output tokens · {result.model}")


if __name__ == "__main__":
    main()
