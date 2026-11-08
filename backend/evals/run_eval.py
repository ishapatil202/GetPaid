"""
Grade the AI's contract reading against a hand-labeled answer key.

Run from the project folder:
    python backend/evals/run_eval.py
Saves a full JSON report and a markdown summary in backend/evals/results/.
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # backend/

from app import config  # noqa: E402
from app.extraction import extract_contract  # noqa: E402
from evals.scoring import score_contract, summarize  # noqa: E402

# Estimated list prices for gpt-4o-mini, USD per 1M tokens. Check current pricing before quoting.
PRICE_IN_PER_M = 0.15
PRICE_OUT_PER_M = 0.60


def run_one(item: dict) -> dict:
    text = (HERE / "contracts" / f"{item['id']}.txt").read_text()
    try:
        result = extract_contract(text)
    except Exception as error:  # a crash counts as all fields wrong
        return {"id": item["id"], "category": item["category"], "error": str(error)}
    extraction = result.extraction.model_dump()
    fake_empty = sum(1 for k in ("client_name", "client_email", "freelancer_name", "payment_terms", "late_fee")
                     if isinstance(extraction[k]["value"], str)
                     and extraction[k]["value"].strip().lower() in ("null", "none", "n/a"))
    score = score_contract(item["expected"], item["expected_flags"], extraction, [i.code for i in result.issues])
    return {
        "id": item["id"],
        "category": item["category"],
        "score": score,
        "quotes_found": sum(1 for h in result.highlights if h.found),
        "quotes_total": len(result.highlights),
        "fake_empty_values": fake_empty,
        "latency_ms": result.latency_ms,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "model": result.model,
        "extraction": extraction,
        "issues": [i.model_dump() for i in result.issues],
    }


def main():
    dataset = json.loads((HERE / "dataset.json").read_text())["contracts"]
    only = sys.argv[1] if len(sys.argv) > 1 else None
    if only:
        dataset = [d for d in dataset if d["id"].startswith(only)]
    print(f"Grading {len(dataset)} contracts with {config.OPENAI_MODEL} (prompt {config.PROMPT_VERSION})...\n")

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(run_one, dataset))

    failed = [r for r in rows if "error" in r]
    rows = [r for r in rows if "error" not in r]
    for r in failed:
        print(f"❌ {r['id']}: crashed: {r['error']}")

    print(f"{'contract':24} {'category':17} {'fields':>7}  flags")
    for r in rows:
        s = r["score"]
        flag_note = "ok"
        if s["flags"]["false_negative"]:
            flag_note = "MISSED " + ", ".join(s["flags"]["false_negative"])
        if s["flags"]["false_positive"]:
            flag_note += " | FALSE ALARM " + ", ".join(s["flags"]["false_positive"])
        mark = "✅" if s["all_correct"] else "⚠️ "
        print(f"{mark} {r['id']:22} {r['category']:17} {s['fields_correct']:>3}/{s['fields_total']:<3}  {flag_note}")
        for name, ok in s["fields"].items():
            if not ok:
                print(f"      wrong: {name}")

    if not rows:
        return
    summary = summarize(rows)
    cost = summary["input_tokens"] / 1e6 * PRICE_IN_PER_M + summary["output_tokens"] / 1e6 * PRICE_OUT_PER_M
    summary["estimated_cost_usd"] = round(cost, 4)
    summary["crashed"] = len(failed)

    lines = [
        f"Field accuracy:           {summary['field_accuracy']:.1%} ({summary['fields_correct']}/{summary['fields_total']} fields)",
        f"Contracts fully correct:  {summary['contracts_fully_correct']}/{summary['contracts']}",
        f"Planted problems caught:  {summary['planted_problems_caught']}/{summary['planted_problems_total']} "
        f"(false alarms: {summary['false_alarms']})",
        f"Quotes found in contract: {summary['quote_grounding']:.1%}",
        f"Fake 'null' text values:  {sum(r['fake_empty_values'] for r in rows)}",
        f"Prompt injection resisted:{summary['injection_resisted']:>2}/{summary['injection_total']}",
        f"Average time per contract: {summary['avg_latency_ms'] / 1000:.1f}s",
        f"Estimated cost per contract: ${cost / len(rows):.5f}",
    ]
    print("\n" + "\n".join(lines))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    report = {"run_at": stamp, "model": rows[0]["model"], "prompt_version": config.PROMPT_VERSION,
              "summary": summary, "contracts": rows}
    (out / f"eval-{stamp}.json").write_text(json.dumps(report, indent=2))
    md = [f"# Extraction eval ({stamp})", "", f"Model: `{rows[0]['model']}`, prompt `{config.PROMPT_VERSION}`, "
          f"{summary['contracts']} hand-labeled synthetic contracts.", "", "| Metric | Result |", "|---|---|"]
    md += [f"| {line.split(':', 1)[0].strip()} | {line.split(':', 1)[1].strip()} |" for line in lines]
    (out / "latest.md").write_text("\n".join(md) + "\n")
    print(f"\nSaved results/eval-{stamp}.json and results/latest.md")


if __name__ == "__main__":
    main()
