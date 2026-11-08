"""
The AI brain: contract text -> structured payment data, then our own checks.

1. The AI fills a strict JSON form (it cannot return any other shape).
2. Our code verifies the AI: every quote must really exist in the contract,
   amounts must add up, and each milestone needs a usable due date.
"""
import re
import time
from datetime import date

from openai import BadRequestError, OpenAI

from . import config
from .checks import payment_checks
from .schemas import ContractExtraction, ExtractionResult, Highlight, Issue

# ---------- 1. The form the AI must fill (strict JSON schema) ----------

def _field(kind, description):
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["value", "source_quote"],
        "properties": {
            "value": {"type": [kind, "null"], "description": description},
            "source_quote": {
                "type": ["string", "null"],
                "description": "Exact words copied from the contract that support the value.",
            },
        },
    }


MILESTONE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "amount", "due_date", "due_rule", "source_quote"],
    "properties": {
        "title": {"type": "string"},
        "amount": {"type": "number", "description": "Amount as a plain number, e.g. 1200.00"},
        "due_date": {"type": ["string", "null"], "description": "YYYY-MM-DD, or null if not a fixed date"},
        "due_rule": {"type": ["string", "null"], "description": "Rule if the date depends on an event"},
        "source_quote": {"type": "string", "description": "Exact contract words for this milestone"},
    },
}

EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "client_name", "client_email", "freelancer_name", "currency", "contract_total",
        "payment_terms", "late_fee", "milestones", "ai_concerns",
    ],
    "properties": {
        "client_name": _field("string", "The client (who pays)"),
        "client_email": _field("string", "Client billing email"),
        "freelancer_name": _field("string", "The freelancer or agency (who gets paid)"),
        "currency": {"type": "string", "description": "ISO code, e.g. USD"},
        "contract_total": _field("number", "Total contract value"),
        "payment_terms": _field("string", "e.g. 'Net 15'"),
        "late_fee": _field("string", "Late fee rule, if any"),
        "milestones": {"type": "array", "items": MILESTONE_SCHEMA},
        "ai_concerns": {
            "type": "array",
            "items": {"type": "string"},
            "description": "One-sentence notes on anything ambiguous or risky for getting paid",
        },
    },
}

SYSTEM_PROMPT = """You extract payment information from freelance contracts.
Rules:
- source_quote must be copied EXACTLY, word for word, from the contract. Use a short span (one sentence or phrase). Never paraphrase.
- If a value is not stated in the contract, use null. Never guess or invent.
- Amounts are plain numbers (e.g. 1200.00), without currency symbols.
- Dates are YYYY-MM-DD. If a due date depends on an event (e.g. "15 days after final delivery"), set due_date to null and put the rule in due_rule.
- Today's date is {today}. Use it to fill in missing years.
- ai_concerns: list anything ambiguous or risky for getting paid, one sentence each. Use an empty list if none."""


# ---------- 2. Calling the AI ----------

def _call_model(contract_text: str):
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    request = dict(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(today=date.today().isoformat())},
            {"role": "user", "content": f"CONTRACT:\n\n{contract_text}"},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "contract_extraction", "strict": True, "schema": EXTRACTION_SCHEMA},
        },
        temperature=0,
    )
    try:
        return client.chat.completions.create(**request)
    except BadRequestError as error:
        if "temperature" in str(error):  # some newer models don't accept temperature
            request.pop("temperature")
            return client.chat.completions.create(**request)
        raise


# ---------- 3. Our own checks on the AI's answer ----------

def find_span(contract: str, quote: str | None):
    """Find where a quote appears in the contract (ignores extra spaces and capitals)."""
    if not quote or not quote.strip():
        return None
    index = contract.find(quote)
    if index >= 0:
        return index, index + len(quote)
    pattern = r"\s+".join(re.escape(word) for word in quote.split())
    match = re.search(pattern, contract, re.IGNORECASE)
    return (match.start(), match.end()) if match else None


def verify(contract: str, data: ContractExtraction):
    highlights: list[Highlight] = []
    issues: list[Issue] = []

    def check_quote(field_name, value, quote):
        if value in (None, ""):
            return
        span = find_span(contract, quote)
        highlights.append(Highlight(field=field_name, quote=quote or "",
                                    start=span[0] if span else None,
                                    end=span[1] if span else None,
                                    found=span is not None))
        if span is None:
            issues.append(Issue(code="quote_not_found", severity="medium",
                                message=f"Couldn't find the source for '{field_name}' in the contract. Please double-check this value."))

    for name in ("client_name", "client_email", "freelancer_name", "contract_total", "payment_terms", "late_fee"):
        field = getattr(data, name)
        check_quote(name, field.value, field.source_quote)

    for i, milestone in enumerate(data.milestones):
        check_quote(f"milestones[{i}]", milestone.title, milestone.source_quote)

    issues.extend(payment_checks(data.client_email.value, data.contract_total.value,
                                 data.currency, data.milestones))

    for concern in data.ai_concerns:
        issues.append(Issue(code="ai_concern", severity="low", message=concern))

    return highlights, issues


# ---------- 4. Everything together ----------

def extract_contract(contract_text: str) -> ExtractionResult:
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is empty in your .env file.")

    started = time.perf_counter()
    response = _call_model(contract_text)
    latency_ms = int((time.perf_counter() - started) * 1000)

    message = response.choices[0].message
    if getattr(message, "refusal", None):
        raise RuntimeError(f"The AI refused: {message.refusal}")

    data = ContractExtraction.model_validate_json(message.content)
    highlights, issues = verify(contract_text, data)
    usage = response.usage

    return ExtractionResult(
        extraction=data,
        highlights=highlights,
        issues=issues,
        model=response.model,
        prompt_version=config.PROMPT_VERSION,
        latency_ms=latency_ms,
        input_tokens=getattr(usage, "prompt_tokens", None),
        output_tokens=getattr(usage, "completion_tokens", None),
    )
