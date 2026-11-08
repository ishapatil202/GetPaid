"""Shapes of the data the API sends and receives."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from .schemas import Highlight, Issue


class LoginOut(BaseModel):
    token: str
    name: str
    email: str


class ContractIn(BaseModel):
    text: str = Field(min_length=50, max_length=50_000)
    title: Optional[str] = None


class ContractUpdate(BaseModel):
    client_name: Optional[str] = None
    client_email: Optional[str] = None
    contract_total: Optional[float] = None


class MilestoneUpdate(BaseModel):
    title: Optional[str] = None
    amount: Optional[float] = None
    due_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class InvoiceOut(BaseModel):
    id: int
    paypal_invoice_id: str
    invoice_number: Optional[str]
    status: str
    amount: float
    currency: str
    due_date: Optional[str]
    pay_link: Optional[str]
    sent_to: Optional[str]
    sent_at: datetime
    paid_at: Optional[datetime]
    milestone_title: Optional[str] = None
    contract_id: Optional[int] = None
    contract_title: Optional[str] = None
    client_name: Optional[str] = None


class MilestoneOut(BaseModel):
    id: int
    position: int
    title: str
    amount: float
    due_date: Optional[str]
    due_rule: Optional[str]
    source_quote: str
    span_start: Optional[int]
    span_end: Optional[int]
    invoice: Optional[InvoiceOut]


class ContractOut(BaseModel):
    id: int
    title: str
    raw_text: str
    client_name: Optional[str]
    client_email: Optional[str]
    freelancer_name: Optional[str]
    currency: str
    contract_total: Optional[float]
    payment_terms: Optional[str]
    late_fee: Optional[str]
    status: str
    created_at: datetime
    milestones: List[MilestoneOut]
    highlights: List[Highlight]
    issues: List[Issue]
    can_send: bool
    ai_model: Optional[str]
    ai_latency_ms: Optional[int]


class ContractSummary(BaseModel):
    id: int
    title: str
    client_name: Optional[str]
    contract_total: Optional[float]
    currency: str
    status: str
    created_at: datetime
    milestone_count: int
    paid_count: int


class Dashboard(BaseModel):
    currency: str
    invoiced: float
    paid: float
    outstanding: float
    overdue: float
    invoice_count: int
    paid_count: int
    overdue_count: int
