import { useEffect, useMemo, useRef, useState } from "react";
import { api, Contract, Milestone } from "../api";
import { invoiceState, money, niceDate } from "../format";

type Mark = { key: string; start: number; end: number; kind: "milestone" | "field" };
type Segment = { text: string; mark?: Mark };

const FIELD_LABELS: Record<string, string> = {
  client_name: "Client",
  client_email: "Billing email",
  contract_total: "Contract total",
  payment_terms: "Payment terms",
  late_fee: "Late fee",
};

// Split the contract into plain text and highlighted pieces.
function buildSegments(text: string, marks: Mark[]): Segment[] {
  const sorted = [...marks].sort((a, b) => a.start - b.start);
  const segments: Segment[] = [];
  let position = 0;
  for (const mark of sorted) {
    if (mark.start < position) continue; // skip overlaps
    if (mark.start > position) segments.push({ text: text.slice(position, mark.start) });
    segments.push({ text: text.slice(mark.start, mark.end), mark });
    position = mark.end;
  }
  if (position < text.length) segments.push({ text: text.slice(position) });
  return segments;
}

export default function Review({ contractId }: { contractId: number }) {
  const [contract, setContract] = useState<Contract | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [saving, setSaving] = useState(false);
  const markRefs = useRef<Record<string, HTMLElement | null>>({});

  useEffect(() => {
    api.contract(contractId).then(setContract).catch((e: Error) => setError(e.message));
  }, [contractId]);

  useEffect(() => {
    if (!selected) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    markRefs.current[selected]?.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
  }, [selected]);

  const marks = useMemo<Mark[]>(() => {
    if (!contract) return [];
    const list: Mark[] = [];
    for (const m of contract.milestones) {
      if (m.span_start !== null && m.span_end !== null) {
        list.push({ key: `m${m.id}`, start: m.span_start, end: m.span_end, kind: "milestone" });
      }
    }
    for (const h of contract.highlights) {
      if (h.field in FIELD_LABELS && h.start !== null && h.end !== null) {
        list.push({ key: `f:${h.field}`, start: h.start, end: h.end, kind: "field" });
      }
    }
    return list;
  }, [contract]);

  const segments = useMemo(() => (contract ? buildSegments(contract.raw_text, marks) : []), [contract, marks]);
  const hasSource = (key: string) => marks.some((m) => m.key === key);

  async function save(action: () => Promise<Contract>) {
    setSaving(true);
    setError(null);
    try {
      setContract(await action());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function sendInvoices() {
    if (!contract) return;
    setSending(true);
    setError(null);
    try {
      setContract(await api.sendInvoices(contract.id));
    } catch (e) {
      setError((e as Error).message);
      api.contract(contract.id).then(setContract).catch(() => undefined);
    } finally {
      setSending(false);
    }
  }

  if (!contract) {
    return error ? <p className="error-text" role="alert">{error}</p> : <p className="muted">Loading contract…</p>;
  }

  const pending = contract.milestones.filter((m) => !m.invoice);
  const sent = contract.milestones.length > 0 && pending.length === 0;
  const milestoneSum = contract.milestones.reduce((sum, m) => sum + m.amount, 0);
  const sumMatches = contract.contract_total === null || Math.abs(milestoneSum - contract.contract_total) < 0.01;
  const blocking = contract.issues.filter((i) => i.severity !== "low");
  const notes = contract.issues.filter((i) => i.severity === "low");

  return (
    <div className="review">
      <div className="review-head">
        <a className="back-link" href="#/">All contracts</a>
        <h1>{contract.client_name || contract.title}</h1>
        <p className="muted">
          {contract.freelancer_name ? `${contract.freelancer_name} for ${contract.client_name ?? "the client"}. ` : ""}
          Click a payment to see where it comes from in the contract.
        </p>
      </div>

      <div className="review-grid">
        {/* ---------- Left: the contract ---------- */}
        <article className="paper contract-paper" aria-label="Contract text">
          <div className="contract-text">
            {segments.map((segment, i) =>
              segment.mark ? (
                <mark
                  key={i}
                  ref={(el) => (markRefs.current[segment.mark!.key] = el)}
                  className={`source source-${segment.mark.kind}${selected === segment.mark.key ? " is-active" : ""}`}
                  onClick={() => setSelected(segment.mark!.key)}
                >
                  {segment.text}
                </mark>
              ) : (
                <span key={i}>{segment.text}</span>
              )
            )}
          </div>
        </article>

        {/* ---------- Right: what the AI found ---------- */}
        <aside className="review-panel">
          {contract.issues.length === 0 ? (
            <div className="check check-ok">Everything checks out. The invoices are ready to send.</div>
          ) : (
            <div className="checks" aria-live="polite">
              {blocking.map((issue, i) => (
                <div key={`b${i}`} className={`check check-${issue.severity}`}>{issue.message}</div>
              ))}
              {notes.length > 0 && (
                <details className="notes">
                  <summary>{notes.length} {notes.length === 1 ? "note" : "notes"} from the AI</summary>
                  <ul>{notes.map((n, i) => <li key={i}>{n.message}</li>)}</ul>
                </details>
              )}
            </div>
          )}

          <section className="panel-section">
            <h2>Client</h2>
            <dl className="facts">
              {(["client_name", "client_email", "payment_terms", "late_fee"] as const).map((field) => {
                const key = `f:${field}`;
                const value = contract[field];
                return (
                  <div
                    key={field}
                    className={`fact${selected === key ? " is-active" : ""}${hasSource(key) ? " has-source" : ""}`}
                    onClick={() => hasSource(key) && setSelected(key)}
                  >
                    <dt>{FIELD_LABELS[field]}</dt>
                    <dd>
                      {field === "client_email" && !sent ? (
                        <input
                          type="email"
                          defaultValue={value ?? ""}
                          key={value ?? "empty"}
                          placeholder="Add the client's email"
                          aria-label="Billing email"
                          onBlur={(e) => {
                            const next = e.target.value.trim();
                            if (next !== (value ?? "")) save(() => api.updateContract(contract.id, { client_email: next || null }));
                          }}
                        />
                      ) : (
                        value || <span className="muted">Not in the contract</span>
                      )}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </section>

          <section className="panel-section">
            <h2>Payments</h2>
            <ol className="milestones">
              {contract.milestones.map((m) => (
                <MilestoneRow
                  key={m.id}
                  milestone={m}
                  currency={contract.currency}
                  active={selected === `m${m.id}`}
                  onSelect={() => setSelected(`m${m.id}`)}
                  onSave={(body) => save(() => api.updateMilestone(m.id, body))}
                />
              ))}
            </ol>
            <p className={`sum-line${sumMatches ? "" : " sum-mismatch"}`}>
              Payments add up to <strong>{money(milestoneSum, contract.currency)}</strong>
              {contract.contract_total !== null && (
                <> of the <strong>{money(contract.contract_total, contract.currency)}</strong> contract total</>
              )}
            </p>
          </section>

          {error && <p className="error-text" role="alert">{error}</p>}

          {sent ? (
            <div className="sent-box">
              <p>All invoices are sent through PayPal.</p>
              <a className="button button-primary" href="#/invoices">See invoices</a>
            </div>
          ) : (
            <div className="send-box">
              <button
                className="button button-primary button-large"
                onClick={sendInvoices}
                disabled={!contract.can_send || sending || saving}
              >
                {sending
                  ? "Sending with PayPal…"
                  : `Send ${pending.length} ${pending.length === 1 ? "invoice" : "invoices"} with PayPal`}
              </button>
              {!contract.can_send && <p className="fine-print">Fix the items above to send.</p>}
              {contract.can_send && !sumMatches && (
                <p className="fine-print">The payments don't match the contract total. You can still send if that's expected.</p>
              )}
            </div>
          )}

          {contract.ai_model && (
            <p className="fine-print">
              Read by {contract.ai_model} in {((contract.ai_latency_ms ?? 0) / 1000).toFixed(1)} seconds.
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}

type RowProps = {
  milestone: Milestone;
  currency: string;
  active: boolean;
  onSelect: () => void;
  onSave: (body: { amount?: number; due_date?: string }) => void;
};

function MilestoneRow({ milestone: m, currency, active, onSelect, onSave }: RowProps) {
  const locked = Boolean(m.invoice);
  const state = m.invoice ? invoiceState(m.invoice.status, m.invoice.due_date) : null;

  return (
    <li className={`milestone${active ? " is-active" : ""}`} onClick={onSelect}>
      <div className="milestone-title">{m.title}</div>
      {locked ? (
        <div className="milestone-sent">
          <span>{money(m.amount, currency)}</span>
          <span>Due {niceDate(m.invoice!.due_date)}</span>
          <span className={`badge badge-${state!.tone}`}>{state!.label}</span>
          {m.invoice!.pay_link && (
            <a href={m.invoice!.pay_link} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
              Open in PayPal
            </a>
          )}
        </div>
      ) : (
        <div className="milestone-fields">
          <label>
            <span>Amount</span>
            <input
              type="number"
              min="0"
              step="0.01"
              defaultValue={m.amount}
              key={`a${m.amount}`}
              onClick={(e) => e.stopPropagation()}
              onBlur={(e) => {
                const next = Number(e.target.value);
                if (!Number.isNaN(next) && next !== m.amount) onSave({ amount: next });
              }}
            />
          </label>
          <label>
            <span>Due date</span>
            <input
              type="date"
              defaultValue={m.due_date ?? ""}
              key={`d${m.due_date}`}
              className={m.due_date ? "" : "needs-value"}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => {
                if (/^\d{4}-\d{2}-\d{2}$/.test(e.target.value)) onSave({ due_date: e.target.value });
              }}
            />
          </label>
          {!m.due_date && m.due_rule && <p className="milestone-rule">Contract says: {m.due_rule}</p>}
        </div>
      )}
    </li>
  );
}
