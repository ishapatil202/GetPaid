import { useEffect, useState } from "react";
import { AgentRun, api, Reminder } from "../api";
import { money, niceDate } from "../format";

const TOOL_LABELS: Record<string, string> = {
  "database.list_open_invoices": "Looked up open invoices",
  "paypal.get_invoice": "Checked PayPal",
  "database.check_reminders": "Checked past reminders",
  "rules.choose_tone": "Chose the tone",
  "ai.draft_reminder": "AI wrote a draft",
  "rules.check_draft": "Checked the draft",
};

// Find the quote inside the message, ignoring extra spaces, capitals and end punctuation.
function findQuote(body: string, quote: string): [number, number] | null {
  const exact = body.indexOf(quote);
  if (exact >= 0) return [exact, exact + quote.length];
  const words = quote.trim().replace(/[.,;:!?]+$/, "").split(/\s+/).filter(Boolean);
  if (words.length === 0) return null;
  const escaped = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const match = new RegExp(escaped.join("\\s+"), "i").exec(body);
  return match ? [match.index, match.index + match[0].length] : null;
}

// Show the quoted contract words with a highlighter.
function BodyWithQuote({ body, quote }: { body: string; quote: string | null }) {
  const span = quote ? findQuote(body, quote) : null;
  if (!span) return <>{body}</>;
  return (
    <>
      {body.slice(0, span[0])}
      <mark className="quote-mark">{body.slice(span[0], span[1])}</mark>
      {body.slice(span[1])}
    </>
  );
}

export default function Reminders() {
  const [reminders, setReminders] = useState<Reminder[] | null>(null);
  const [run, setRun] = useState<AgentRun | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.reminders(), api.latestRun()])
      .then(([list, latest]) => {
        setReminders(list);
        setRun(latest);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  async function runAgent() {
    setRunning(true);
    setError(null);
    try {
      const result = await api.runAgent();
      setRun(result.run);
      setReminders(await api.reminders());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  function replace(updated: Reminder) {
    setReminders((list) => (list ? list.map((r) => (r.id === updated.id ? updated : r)) : list));
  }

  const drafts = reminders?.filter((r) => r.status === "draft") ?? [];
  const history = reminders?.filter((r) => r.status !== "draft") ?? [];

  return (
    <div className="stack">
      <div className="page-head">
        <div className="stack-tight">
          <h1>Reminders</h1>
          <p className="muted">The agent checks PayPal for late payments and drafts reminders. You approve each one before it's sent.</p>
        </div>
        <button className="button button-primary" onClick={runAgent} disabled={running}>
          {running ? "Checking invoices…" : "Check for late payments"}
        </button>
      </div>

      {error && <p className="error-text" role="alert">{error}</p>}

      {run && (
        <section className="agent-log" aria-label="What the agent did">
          <h2>What the agent did</h2>
          <ol>
            {run.steps.map((step, i) => (
              <li key={i} className={step.ok ? "" : "step-warn"}>
                <span className="step-tool">{TOOL_LABELS[step.tool] ?? step.tool}</span>
                <span>{step.summary}</span>
              </li>
            ))}
          </ol>
          <p className="agent-summary">{run.summary}</p>
        </section>
      )}

      {reminders === null && !error && <p className="muted">Loading reminders…</p>}

      {reminders && drafts.length === 0 && !run && (
        <div className="empty">
          <h2>No reminders yet</h2>
          <p>Click "Check for late payments" and the agent will look for invoices that are past their due date.</p>
        </div>
      )}

      {drafts.length > 0 && (
        <section className="stack">
          <h2>Waiting for your approval</h2>
          {drafts.map((r) => (
            <DraftCard key={r.id} reminder={r} onChange={replace} onError={setError} />
          ))}
        </section>
      )}

      {history.length > 0 && (
        <section className="stack">
          <h2>Sent and skipped</h2>
          <ul className="history">
            {history.map((r) => (
              <li key={r.id}>
                <span className={`badge ${r.status === "sent" ? "badge-paid" : "badge-muted"}`}>
                  {r.status === "sent" ? "Sent with PayPal" : "Skipped"}
                </span>
                <span className="history-title">{r.milestone_title}</span>
                <span className="muted">{r.client_name}</span>
                <span className="muted">{r.sent_at ? niceDate(r.sent_at) : niceDate(r.created_at)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

type CardProps = { reminder: Reminder; onChange: (r: Reminder) => void; onError: (m: string | null) => void };

function DraftCard({ reminder: r, onChange, onError }: CardProps) {
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState(r.subject);
  const [body, setBody] = useState(r.body);
  const [busy, setBusy] = useState<"save" | "send" | "skip" | null>(null);

  async function act(kind: "save" | "send" | "skip", action: () => Promise<Reminder>) {
    setBusy(kind);
    onError(null);
    try {
      onChange(await action());
      if (kind === "save") setEditing(false);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <article className="draft">
      <header className="draft-head">
        <div>
          <h3>{r.milestone_title}</h3>
          <p className="muted">
            {r.client_name} owes {money(r.amount, r.currency)}. It was due {niceDate(r.due_date)}.
          </p>
        </div>
        <div className="draft-tags">
          <span className="badge badge-overdue">{r.days_overdue} days late</span>
          <span className={`badge tone-${r.tone}`}>{r.tone === "firm" ? "Firm" : "Friendly"}</span>
        </div>
      </header>

      {editing ? (
        <div className="draft-edit">
          <label>
            <span>Subject</span>
            <input value={subject} onChange={(e) => setSubject(e.target.value)} />
          </label>
          <label>
            <span>Message</span>
            <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={8} />
          </label>
        </div>
      ) : (
        <div className="draft-letter">
          <p className="draft-subject">{r.subject}</p>
          <p className="draft-body"><BodyWithQuote body={r.body} quote={r.contract_quote} /></p>
        </div>
      )}

      <p className={`fine-print ${r.quote_verified ? "" : "warn-text"}`}>
        {r.quote_verified
          ? "The highlighted quote was checked against the contract."
          : "The AI's quote couldn't be found in the contract. Edit the message before sending."}
      </p>

      <div className="row-actions">
        {editing ? (
          <>
            <button className="button button-primary" disabled={busy !== null}
              onClick={() => act("save", () => api.editReminder(r.id, { subject, body }))}>
              {busy === "save" ? "Saving…" : "Save changes"}
            </button>
            <button className="button" onClick={() => { setEditing(false); setSubject(r.subject); setBody(r.body); }}>
              Cancel
            </button>
          </>
        ) : (
          <>
            <button className="button button-primary" disabled={busy !== null}
              onClick={() => act("send", () => api.approveReminder(r.id))}>
              {busy === "send" ? "Sending with PayPal…" : "Approve and send with PayPal"}
            </button>
            <button className="button" disabled={busy !== null} onClick={() => setEditing(true)}>Edit</button>
            <button className="link-button" disabled={busy !== null}
              onClick={() => act("skip", () => api.skipReminder(r.id))}>
              Skip
            </button>
          </>
        )}
      </div>
    </article>
  );
}
