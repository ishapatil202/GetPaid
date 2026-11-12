"""Database tables."""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Contract(Base):
    __tablename__ = "contracts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    raw_text: Mapped[str] = mapped_column(Text)
    client_name: Mapped[Optional[str]] = mapped_column(String(255))
    client_email: Mapped[Optional[str]] = mapped_column(String(255))
    freelancer_name: Mapped[Optional[str]] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    contract_total: Mapped[Optional[float]] = mapped_column(Float)
    payment_terms: Mapped[Optional[str]] = mapped_column(String(255))
    late_fee: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="review")  # review -> sent
    extraction: Mapped[dict] = mapped_column(JSON)  # full AI result + checks, kept for audit
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    milestones: Mapped[List["Milestone"]] = relationship(
        back_populates="contract", order_by="Milestone.position", cascade="all, delete-orphan"
    )


class Milestone(Base):
    __tablename__ = "milestones"
    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500))
    amount: Mapped[float] = mapped_column(Float)
    due_date: Mapped[Optional[str]] = mapped_column(String(10))  # YYYY-MM-DD
    due_rule: Mapped[Optional[str]] = mapped_column(String(500))
    source_quote: Mapped[str] = mapped_column(Text)
    span_start: Mapped[Optional[int]] = mapped_column(Integer)  # where the quote sits in the contract
    span_end: Mapped[Optional[int]] = mapped_column(Integer)

    contract: Mapped[Contract] = relationship(back_populates="milestones")
    invoice: Mapped[Optional["Invoice"]] = relationship(back_populates="milestone", uselist=False)


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    milestone_id: Mapped[int] = mapped_column(ForeignKey("milestones.id"), unique=True)
    paypal_invoice_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    invoice_number: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))  # PayPal status: SENT, PAID, ...
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3))
    due_date: Mapped[Optional[str]] = mapped_column(String(10))
    pay_link: Mapped[Optional[str]] = mapped_column(Text)
    sent_to: Mapped[Optional[str]] = mapped_column(String(255))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    milestone: Mapped[Milestone] = relationship(back_populates="invoice")


class ExtractionLog(Base):
    """One row per AI call: which model, how fast, how many tokens. Used for evals and cost tracking."""
    __tablename__ = "extraction_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"), index=True)
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(20))
    latency_ms: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    issue_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentRun(Base):
    """One run of the reminder agent, with every step it took (for transparency)."""
    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    steps: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    invoices_checked: Mapped[int] = mapped_column(Integer, default=0)
    late_found: Mapped[int] = mapped_column(Integer, default=0)
    drafts_created: Mapped[int] = mapped_column(Integer, default=0)


class Reminder(Base):
    """A reminder the agent drafted. Nothing is sent until the user approves it."""
    __tablename__ = "reminders"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    agent_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("agent_runs.id"))
    tone: Mapped[str] = mapped_column(String(10))  # friendly | firm
    days_overdue: Mapped[int] = mapped_column(Integer)
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    contract_quote: Mapped[Optional[str]] = mapped_column(Text)
    quote_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft | sent | skipped
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    invoice: Mapped[Invoice] = relationship()


class WebhookEvent(Base):
    """Every PayPal webhook we accepted. The unique event id makes processing idempotent."""
    __tablename__ = "webhook_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    paypal_event_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[Optional[str]] = mapped_column(String(100))
    result: Mapped[str] = mapped_column(String(255), default="")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
