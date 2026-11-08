"""
GetPaid API.

Run from the project folder:
    uvicorn app.main:app --reload --app-dir backend
Then open http://localhost:8000/docs
"""
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

import openai
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from . import config
from .agent import run_reminder_agent
from .ask import ask_to_filters
from .api_schemas import (AgentRunOut, AgentRunResult, AskIn, AskOut, ContractIn, ContractOut, ContractSummary, ContractUpdate,
                          Dashboard, InvoiceOut, LoginOut, MilestoneOut, MilestoneUpdate, ReminderOut, ReminderUpdate)
from .auth import create_token, get_current_user, get_or_create_demo_user
from .checks import BLOCKING_CODES, payment_checks
from .database import Base, engine, get_db
from .extraction import extract_contract
from .models import AgentRun, Contract, ExtractionLog, Invoice, Milestone, Reminder, User
from .paypal_client import PayPalError, get_paypal, invoice_summary
from .pdf_text import PdfTextError, pdf_to_text
from .schemas import Highlight, Issue

FINAL_STATUSES = {"PAID", "MARKED_AS_PAID", "CANCELLED", "REFUNDED", "MARKED_AS_REFUNDED"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)  # creates tables on first run
    yield


app = FastAPI(
    title="GetPaid API",
    description="Contract-to-cash for freelancers: AI reads the contract, PayPal sends and tracks the invoices.",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=config.FRONTEND_ORIGINS,
                   allow_methods=["*"], allow_headers=["*"])


# ---------- helpers ----------

def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def invoice_out(inv: Invoice) -> InvoiceOut:
    m = inv.milestone
    return InvoiceOut(
        id=inv.id, paypal_invoice_id=inv.paypal_invoice_id, invoice_number=inv.invoice_number,
        status=inv.status, amount=inv.amount, currency=inv.currency, due_date=inv.due_date,
        pay_link=inv.pay_link, sent_to=inv.sent_to, sent_at=inv.sent_at, paid_at=inv.paid_at,
        milestone_title=m.title if m else None,
        contract_id=m.contract_id if m else None,
        contract_title=m.contract.title if m else None,
        client_name=m.contract.client_name if m else None,
    )


def live_issues(contract: Contract) -> list[Issue]:
    """Checks on the CURRENT data (after the user's edits), plus the AI's own notes."""
    not_invoiced = [m for m in contract.milestones if m.invoice is None]
    issues = payment_checks(contract.client_email, contract.contract_total, contract.currency,
                            contract.milestones, date_milestones=not_invoiced)
    for stored in (contract.extraction or {}).get("issues", []):
        if stored.get("code") in ("quote_not_found", "ai_concern"):
            issues.append(Issue(**stored))
    return issues


def contract_out(contract: Contract) -> ContractOut:
    issues = live_issues(contract)
    pending = [m for m in contract.milestones if m.invoice is None]
    extraction = contract.extraction or {}
    return ContractOut(
        id=contract.id, title=contract.title, raw_text=contract.raw_text,
        client_name=contract.client_name, client_email=contract.client_email,
        freelancer_name=contract.freelancer_name, currency=contract.currency,
        contract_total=contract.contract_total, payment_terms=contract.payment_terms,
        late_fee=contract.late_fee, status=contract.status, created_at=contract.created_at,
        milestones=[
            MilestoneOut(id=m.id, position=m.position, title=m.title, amount=m.amount, due_date=m.due_date,
                         due_rule=m.due_rule, source_quote=m.source_quote, span_start=m.span_start,
                         span_end=m.span_end, invoice=invoice_out(m.invoice) if m.invoice else None)
            for m in contract.milestones
        ],
        highlights=[Highlight(**h) for h in extraction.get("highlights", [])],
        issues=issues,
        can_send=bool(pending) and not any(i.code in BLOCKING_CODES for i in issues),
        ai_model=extraction.get("model"),
        ai_latency_ms=extraction.get("latency_ms"),
    )


def own_contract(db: Session, user: User, contract_id: int) -> Contract:
    contract = db.get(Contract, contract_id)
    if contract is None or contract.user_id != user.id:
        raise HTTPException(status_code=404, detail="Contract not found.")
    return contract


# ---------- health & login ----------

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["system"])
def health():
    return {
        "ok": True,
        "ai_configured": bool(config.OPENAI_API_KEY),
        "paypal_configured": bool(config.PAYPAL_CLIENT_ID and config.PAYPAL_CLIENT_SECRET),
        "paypal_env": config.PAYPAL_ENV,
    }


@app.post("/auth/demo", response_model=LoginOut, tags=["auth"])
def demo_login(db: Session = Depends(get_db)):
    """One-click login as the demo freelancer (for judges)."""
    user = get_or_create_demo_user(db)
    return LoginOut(token=create_token(user.id), name=user.name, email=user.email)


@app.get("/me", tags=["auth"])
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "name": user.name, "email": user.email}


# ---------- contracts ----------

def create_contract_from_text(text: str, title: str | None, user: User, db: Session) -> ContractOut:
    """Shared by paste and PDF upload: AI extracts payment details, our checks verify them."""
    try:
        result = extract_contract(text)
    except openai.OpenAIError as error:
        raise HTTPException(status_code=502, detail=f"AI service error: {error}")

    data = result.extraction
    spans = {h.field: h for h in result.highlights}
    title = title or " – ".join(x for x in (data.client_name.value, "Contract") if x)

    contract = Contract(
        user_id=user.id, title=title[:255], raw_text=text,
        client_name=data.client_name.value, client_email=data.client_email.value,
        freelancer_name=data.freelancer_name.value, currency=(data.currency or "USD")[:3].upper(),
        contract_total=data.contract_total.value, payment_terms=data.payment_terms.value,
        late_fee=data.late_fee.value, extraction=result.model_dump(mode="json"),
    )
    for i, m in enumerate(data.milestones):
        span = spans.get(f"milestones[{i}]")
        contract.milestones.append(Milestone(
            position=i, title=m.title[:500], amount=m.amount, due_date=m.due_date, due_rule=m.due_rule,
            source_quote=m.source_quote,
            span_start=span.start if span else None, span_end=span.end if span else None,
        ))
    db.add(contract)
    db.flush()
    db.add(ExtractionLog(contract_id=contract.id, model=result.model, prompt_version=result.prompt_version,
                         latency_ms=result.latency_ms, input_tokens=result.input_tokens,
                         output_tokens=result.output_tokens, issue_count=len(result.issues)))
    db.commit()
    return contract_out(contract)



@app.post("/contracts", response_model=ContractOut, tags=["contracts"])
def create_contract(body: ContractIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Pasted contract text -> AI extraction -> checks."""
    return create_contract_from_text(body.text, body.title, user, db)


@app.post("/contracts/upload", response_model=ContractOut, tags=["contracts"])
async def upload_contract(file: UploadFile = File(...), user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """Upload a PDF (or .txt) contract. The text is pulled out, then it works like pasted text."""
    data = await file.read()
    name = (file.filename or "").lower()
    try:
        if name.endswith(".pdf") or data[:5] == b"%PDF-":
            text = pdf_to_text(data)
        else:
            text = data.decode("utf-8", errors="replace").strip()
            if len(text) < 50:
                raise PdfTextError("This file is too short to be a contract.")
    except PdfTextError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return await run_in_threadpool(create_contract_from_text, text[:50_000], None, user, db)


@app.get("/contracts", response_model=list[ContractSummary], tags=["contracts"])
def list_contracts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    contracts = db.query(Contract).filter(Contract.user_id == user.id).order_by(Contract.created_at.desc()).all()
    return [
        ContractSummary(
            id=c.id, title=c.title, client_name=c.client_name, contract_total=c.contract_total,
            currency=c.currency, status=c.status, created_at=c.created_at,
            milestone_count=len(c.milestones),
            paid_count=sum(1 for m in c.milestones if m.invoice and m.invoice.status in ("PAID", "MARKED_AS_PAID")),
        )
        for c in contracts
    ]


@app.get("/contracts/{contract_id}", response_model=ContractOut, tags=["contracts"])
def get_contract(contract_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return contract_out(own_contract(db, user, contract_id))


@app.patch("/contracts/{contract_id}", response_model=ContractOut, tags=["contracts"])
def update_contract(contract_id: int, body: ContractUpdate, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    contract = own_contract(db, user, contract_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(contract, field, value)
    db.commit()
    return contract_out(contract)


@app.patch("/milestones/{milestone_id}", response_model=ContractOut, tags=["contracts"])
def update_milestone(milestone_id: int, body: MilestoneUpdate, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    milestone = db.get(Milestone, milestone_id)
    if milestone is None or milestone.contract.user_id != user.id:
        raise HTTPException(status_code=404, detail="Milestone not found.")
    if milestone.invoice is not None:
        raise HTTPException(status_code=409, detail="This milestone was already invoiced.")
    changes = body.model_dump(exclude_unset=True)
    if "due_date" in changes and changes["due_date"]:
        try:
            date.fromisoformat(changes["due_date"])
        except ValueError:
            raise HTTPException(status_code=422, detail="Due date must be a real date (YYYY-MM-DD).")
    for field, value in changes.items():
        setattr(milestone, field, value)
    db.commit()
    return contract_out(milestone.contract)


@app.post("/contracts/{contract_id}/send", response_model=ContractOut, tags=["invoices"])
def send_invoices(contract_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create and send one PayPal invoice per milestone that isn't invoiced yet."""
    contract = own_contract(db, user, contract_id)
    blocking = [i.message for i in live_issues(contract) if i.code in BLOCKING_CODES]
    if blocking:
        raise HTTPException(status_code=400, detail={"message": "Fix these first.", "issues": blocking})
    pending = [m for m in contract.milestones if m.invoice is None]
    if not pending:
        raise HTTPException(status_code=400, detail="All milestones are already invoiced.")

    # In sandbox, send to the test buyer so the demo payment works.
    recipient = config.PAYPAL_BUYER_EMAIL if (config.PAYPAL_ENV != "live" and config.PAYPAL_BUYER_EMAIL) \
        else contract.client_email

    try:
        paypal = get_paypal()
        for m in pending:
            paypal_id = paypal.create_invoice(
                recipient_email=recipient,
                recipient_name=contract.client_name,
                currency=contract.currency,
                item_name=m.title,
                item_description=f'Per contract: "{m.source_quote}"',
                amount=m.amount,
                due_date=m.due_date,
                note=f"{contract.title}. Payment terms: {contract.payment_terms or 'see contract'}.",
            )
            paypal.send_invoice(paypal_id)
            summary = invoice_summary(paypal.get_invoice(paypal_id))
            m.invoice = Invoice(
                user_id=user.id, paypal_invoice_id=paypal_id,
                invoice_number=summary["invoice_number"], status=summary["status"], amount=m.amount,
                currency=contract.currency, due_date=m.due_date, pay_link=summary["pay_link"], sent_to=recipient,
            )
            db.commit()  # save each invoice right away, so a later failure doesn't lose it
    except PayPalError as error:
        db.commit()
        raise HTTPException(status_code=502, detail=error.message)

    contract.status = "sent"
    db.commit()
    db.refresh(contract)
    return contract_out(contract)


# ---------- invoices ----------

def _user_invoices(db: Session, user: User):
    return db.query(Invoice).filter(Invoice.user_id == user.id).order_by(Invoice.sent_at.desc()).all()


@app.get("/invoices", response_model=list[InvoiceOut], tags=["invoices"])
def list_invoices(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [invoice_out(inv) for inv in _user_invoices(db, user)]


@app.post("/invoices/refresh", tags=["invoices"])
def refresh_invoices(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Ask PayPal for the latest status of every open invoice."""
    changed = []
    try:
        paypal = get_paypal()
        for inv in _user_invoices(db, user):
            if inv.status in FINAL_STATUSES:
                continue
            summary = invoice_summary(paypal.get_invoice(inv.paypal_invoice_id))
            if summary["status"] != inv.status:
                changed.append({"invoice": inv.paypal_invoice_id, "from": inv.status, "to": summary["status"]})
                inv.status = summary["status"]
                if summary["status"] in ("PAID", "MARKED_AS_PAID"):
                    inv.paid_at = _parse_dt(summary["paid_at"]) or datetime.now(timezone.utc)
            inv.pay_link = summary["pay_link"] or inv.pay_link
        db.commit()
    except PayPalError as error:
        raise HTTPException(status_code=502, detail=error.message)
    return {"changed": changed, "invoices": [invoice_out(inv) for inv in _user_invoices(db, user)]}


@app.post("/invoices/ask", response_model=AskOut, tags=["invoices"])
def ask_invoices(body: AskIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Plain-English question -> filter settings for the invoice table. Changes no data."""
    clients = sorted({inv.milestone.contract.client_name for inv in _user_invoices(db, user)
                      if inv.milestone and inv.milestone.contract.client_name})
    try:
        return AskOut(**ask_to_filters(body.question, clients))
    except (openai.OpenAIError, RuntimeError) as error:
        raise HTTPException(status_code=502, detail=f"AI service error: {error}")


@app.get("/dashboard", response_model=Dashboard, tags=["invoices"])
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    invoices = _user_invoices(db, user)
    today = date.today().isoformat()
    paid = [i for i in invoices if i.status in ("PAID", "MARKED_AS_PAID")]
    open_ = [i for i in invoices if i.status not in FINAL_STATUSES]
    overdue = [i for i in open_ if i.due_date and i.due_date < today]
    return Dashboard(
        currency=invoices[0].currency if invoices else "USD",
        invoiced=round(sum(i.amount for i in invoices), 2),
        paid=round(sum(i.amount for i in paid), 2),
        outstanding=round(sum(i.amount for i in open_), 2),
        overdue=round(sum(i.amount for i in overdue), 2),
        invoice_count=len(invoices), paid_count=len(paid), overdue_count=len(overdue),
    )


# ---------- reminder agent ----------

def reminder_out(r: Reminder) -> ReminderOut:
    inv = r.invoice
    m = inv.milestone
    return ReminderOut(
        id=r.id, invoice_id=inv.id, paypal_invoice_id=inv.paypal_invoice_id, pay_link=inv.pay_link,
        milestone_title=m.title, client_name=m.contract.client_name, contract_id=m.contract_id,
        amount=inv.amount, currency=inv.currency, due_date=inv.due_date, days_overdue=r.days_overdue,
        tone=r.tone, subject=r.subject, body=r.body, contract_quote=r.contract_quote,
        quote_verified=r.quote_verified, status=r.status, created_at=r.created_at, sent_at=r.sent_at,
    )


def run_out(run: AgentRun) -> AgentRunOut:
    return AgentRunOut(
        id=run.id, started_at=run.started_at, finished_at=run.finished_at, steps=run.steps or [],
        summary=run.summary, invoices_checked=run.invoices_checked, late_found=run.late_found,
        drafts_created=run.drafts_created,
    )


def own_reminder(db: Session, user: User, reminder_id: int) -> Reminder:
    reminder = db.get(Reminder, reminder_id)
    if reminder is None or reminder.user_id != user.id:
        raise HTTPException(status_code=404, detail="Reminder not found.")
    return reminder


@app.post("/agent/run", response_model=AgentRunResult, tags=["agent"])
def run_agent(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Check every open invoice with PayPal and draft reminders for late ones. Sends nothing."""
    try:
        run, drafts = run_reminder_agent(db, user, get_paypal())
    except PayPalError as error:
        raise HTTPException(status_code=502, detail=error.message)
    return AgentRunResult(run=run_out(run), reminders=[reminder_out(r) for r in drafts])


@app.get("/agent/runs/latest", response_model=AgentRunOut | None, tags=["agent"])
def latest_run(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run = db.query(AgentRun).filter(AgentRun.user_id == user.id).order_by(AgentRun.id.desc()).first()
    return run_out(run) if run else None


@app.get("/reminders", response_model=list[ReminderOut], tags=["agent"])
def list_reminders(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reminders = db.query(Reminder).filter(Reminder.user_id == user.id).order_by(Reminder.id.desc()).all()
    return [reminder_out(r) for r in reminders]


@app.patch("/reminders/{reminder_id}", response_model=ReminderOut, tags=["agent"])
def edit_reminder(reminder_id: int, body: ReminderUpdate, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    reminder = own_reminder(db, user, reminder_id)
    if reminder.status != "draft":
        raise HTTPException(status_code=409, detail="Only drafts can be edited.")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(reminder, field, value)
    db.commit()
    return reminder_out(reminder)


@app.post("/reminders/{reminder_id}/approve", response_model=ReminderOut, tags=["agent"])
def approve_reminder(reminder_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The human approves: PayPal sends the reminder to the client."""
    reminder = own_reminder(db, user, reminder_id)
    if reminder.status != "draft":
        raise HTTPException(status_code=409, detail=f"This reminder is already {reminder.status}.")
    try:
        get_paypal().remind(reminder.invoice.paypal_invoice_id, reminder.subject, reminder.body)
    except PayPalError as error:
        raise HTTPException(status_code=502, detail=error.message)
    reminder.status = "sent"
    reminder.sent_at = datetime.now(timezone.utc)
    db.commit()
    return reminder_out(reminder)


@app.post("/reminders/{reminder_id}/skip", response_model=ReminderOut, tags=["agent"])
def skip_reminder(reminder_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reminder = own_reminder(db, user, reminder_id)
    if reminder.status != "draft":
        raise HTTPException(status_code=409, detail=f"This reminder is already {reminder.status}.")
    reminder.status = "skipped"
    db.commit()
    return reminder_out(reminder)
