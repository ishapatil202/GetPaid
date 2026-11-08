"""The exact shapes of data the AI must return, and what we return after checking it."""
from typing import List, Optional

from pydantic import BaseModel


# ---------- What the AI fills in ----------

class TextField(BaseModel):
    value: Optional[str]
    source_quote: Optional[str]  # exact words copied from the contract


class MoneyField(BaseModel):
    value: Optional[float]
    source_quote: Optional[str]


class Milestone(BaseModel):
    title: str
    amount: float
    due_date: Optional[str]   # YYYY-MM-DD, or None if it depends on an event
    due_rule: Optional[str]   # e.g. "15 days after final delivery"
    source_quote: str


class ContractExtraction(BaseModel):
    client_name: TextField
    client_email: TextField
    freelancer_name: TextField
    currency: str
    contract_total: MoneyField
    payment_terms: TextField
    late_fee: TextField
    milestones: List[Milestone]
    ai_concerns: List[str]


# ---------- What our own code adds after checking the AI ----------

class Highlight(BaseModel):
    field: str            # e.g. "client_name" or "milestones[1]"
    quote: str
    start: Optional[int]  # character position in the contract (for highlighting)
    end: Optional[int]
    found: bool           # did the quote really appear in the contract?


class Issue(BaseModel):
    code: str             # e.g. "total_mismatch"
    severity: str         # "high" | "medium" | "low"
    message: str


class ExtractionResult(BaseModel):
    extraction: ContractExtraction
    highlights: List[Highlight]
    issues: List[Issue]
    model: str
    prompt_version: str
    latency_ms: int
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
