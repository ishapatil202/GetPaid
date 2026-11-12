import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import {
  AllCommunityModule,
  ColDef,
  GridApi,
  ICellRendererParams,
  IRowNode,
  ModuleRegistry,
  themeQuartz,
} from "ag-grid-community";
import { api, AskResult, Dashboard, Invoice } from "../api";
import { invoiceState, money, niceDate, todayIso } from "../format";

ModuleRegistry.registerModules([AllCommunityModule]);

const gridTheme = themeQuartz.withParams({
  fontFamily: "'Bricolage Grotesque', system-ui, sans-serif",
  fontSize: 14,
  foregroundColor: "#1A2238",
  headerBackgroundColor: "#F4F6FA",
  headerTextColor: "#5B6578",
  borderColor: "#DCE1EA",
  accentColor: "#1A2238",
  rowHoverColor: "#FFF8D1",
  wrapperBorderRadius: 10,
});

type View = "all" | "unpaid" | "waiting" | "overdue" | "paid";
const VIEWS: { key: View; label: string }[] = [
  { key: "all", label: "All" },
  { key: "unpaid", label: "Unpaid" },
  { key: "waiting", label: "Waiting" },
  { key: "overdue", label: "Overdue" },
  { key: "paid", label: "Paid" },
];

const EXAMPLES = ["overdue invoices from Northwind", "unpaid invoices over $1,000, biggest first", "logo payments"];
const SORT_COLUMN: Record<string, string> = { amount: "amount", due_date: "due_date", days_late: "daysLate", sent_at: "sent_at" };

// Turn the AI's answer into AG Grid's own filter model, so the column filters show exactly what was applied.
function toFilterModel(a: AskResult) {
  const model: Record<string, unknown> = {};
  if (a.client_contains) model.client_name = { filterType: "text", type: "contains", filter: a.client_contains };
  if (a.payment_contains) model.milestone_title = { filterType: "text", type: "contains", filter: a.payment_contains };
  const amount = [
    a.amount_min !== null ? { filterType: "number", type: "greaterThanOrEqual", filter: a.amount_min } : null,
    a.amount_max !== null ? { filterType: "number", type: "lessThanOrEqual", filter: a.amount_max } : null,
  ].filter(Boolean);
  if (amount.length === 1) model.amount = amount[0];
  if (amount.length === 2) model.amount = { filterType: "number", operator: "AND", conditions: amount };
  if (a.days_late_min !== null) model.daysLate = { filterType: "number", type: "greaterThanOrEqual", filter: a.days_late_min };
  return model;
}

function toneOf(inv: Invoice) {
  return invoiceState(inv.status, inv.due_date).tone; // paid | waiting | overdue | muted
}

function inView(inv: Invoice, view: View) {
  const tone = toneOf(inv);
  if (view === "unpaid") return tone === "waiting" || tone === "overdue";
  return view === "all" || tone === view;
}

function daysLate(inv: Invoice): number | null {
  if (toneOf(inv) !== "overdue" || !inv.due_date) return null;
  const due = new Date(inv.due_date + "T00:00:00").getTime();
  const today = new Date(todayIso() + "T00:00:00").getTime();
  return Math.round((today - due) / 86_400_000);
}

// ---------- cell renderers ----------

function StatusCell(params: ICellRendererParams<Invoice>) {
  if (!params.data || params.node.rowPinned) return null;
  const state = invoiceState(params.data.status, params.data.due_date);
  return <span className={`badge badge-${state.tone}`}>{state.label}</span>;
}

function ContractCell(params: ICellRendererParams<Invoice>) {
  const d = params.data;
  if (!d || params.node.rowPinned) return null;
  return d.contract_id ? <a href={`#/contracts/${d.contract_id}`}>{d.client_name || d.contract_title}</a> : <>{d.client_name}</>;
}

function ActionsCell(params: ICellRendererParams<Invoice>) {
  const d = params.data;
  if (!d || params.node.rowPinned) return null;
  return (
    <span className="grid-actions">
      {toneOf(d) === "overdue" && <a href="#/reminders">Remind</a>}
      {d.pay_link && <a href={d.pay_link} target="_blank" rel="noreferrer">PayPal</a>}
    </span>
  );
}

// ---------- page ----------

export default function Invoices() {
  const gridRef = useRef<AgGridReact<Invoice>>(null);
  const [invoices, setInvoices] = useState<Invoice[] | null>(null);
  const [summary, setSummary] = useState<Dashboard | null>(null);
  const [checking, setChecking] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [justPaid, setJustPaid] = useState<Set<string>>(new Set());
  const [view, setView] = useState<View>("all");
  const [search, setSearch] = useState("");
  const [totalRow, setTotalRow] = useState<Invoice[]>([]);
  const [shown, setShown] = useState(0);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<AskResult | null>(null);

  // The status buttons use AG Grid's external filter. A ref keeps the callback stable.
  const viewRef = useRef<View>("all");
  useEffect(() => {
    viewRef.current = view;
    gridRef.current?.api?.onFilterChanged();
  }, [view]);
  const isExternalFilterPresent = useCallback(() => viewRef.current !== "all", []);
  const doesExternalFilterPass = useCallback(
    (node: IRowNode<Invoice>) => !node.data || inView(node.data, viewRef.current),
    []
  );

  const load = useCallback(async () => {
    const [list, dash] = await Promise.all([api.invoices(), api.dashboard()]);
    setInvoices(list);
    setSummary(dash);
  }, []);

  useEffect(() => {
    load().catch((e: Error) => setError(e.message));
  }, [load]);

  // Live updates: PayPal webhooks change statuses on the server, so poll quietly while the page is open.
  const knownStatus = useRef<Record<string, string>>({});
  useEffect(() => {
    for (const inv of invoices ?? []) {
      const before = knownStatus.current[inv.paypal_invoice_id];
      const paidNow = inv.status === "PAID" || inv.status === "MARKED_AS_PAID";
      if (before && before !== inv.status && paidNow) {
        setJustPaid((set) => new Set(set).add(inv.paypal_invoice_id));
        setMessage(`${inv.milestone_title} was just paid. PayPal notified GetPaid automatically.`);
      }
      knownStatus.current[inv.paypal_invoice_id] = inv.status;
    }
  }, [invoices]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") load().catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [load]);

  // Totals row at the bottom: sums only the rows that are currently visible.
  const updateTotals = useCallback((event: { api: GridApi<Invoice> }) => {
    let sum = 0;
    let count = 0;
    let currency = "USD";
    event.api.forEachNodeAfterFilter((node) => {
      if (node.data) {
        sum += node.data.amount;
        count += 1;
        currency = node.data.currency;
      }
    });
    setShown(count);
    setTotalRow([
      {
        id: -1, paypal_invoice_id: "total-row", invoice_number: null, status: "", amount: sum, currency,
        due_date: null, pay_link: null, sent_to: null, sent_at: "", paid_at: null,
        milestone_title: `Total of ${count} ${count === 1 ? "invoice" : "invoices"}`,
        contract_id: null, contract_title: null, client_name: null,
      },
    ]);
  }, []);

  async function checkPayments() {
    setChecking(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.refresh();
      const paid = result.changed.filter((c) => c.to === "PAID" || c.to === "MARKED_AS_PAID");
      setJustPaid(new Set(paid.map((c) => c.invoice)));
      setMessage(
        paid.length > 0
          ? `${paid.length} ${paid.length === 1 ? "invoice was" : "invoices were"} paid.`
          : "No new payments yet."
      );
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setChecking(false);
    }
  }

  async function ask(text: string) {
    const q = text.trim();
    if (q.length < 2 || asking) return;
    setQuestion(q);
    setAsking(true);
    setError(null);
    try {
      const result = await api.askInvoices(q);
      const grid = gridRef.current?.api;
      setSearch("");
      setView(result.status);
      viewRef.current = result.status;
      grid?.setFilterModel(toFilterModel(result));
      grid?.applyColumnState({
        state: result.sort_by ? [{ colId: SORT_COLUMN[result.sort_by], sort: result.sort_direction ?? "desc" }] : [],
        defaultState: { sort: null },
      });
      grid?.onFilterChanged();
      setAnswer(result);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAsking(false);
    }
  }

  function clearAll() {
    const grid = gridRef.current?.api;
    grid?.setFilterModel(null);
    grid?.applyColumnState({ defaultState: { sort: null } });
    setView("all");
    setSearch("");
    setQuestion("");
    setAnswer(null);
  }

  function exportCsv() {
    gridRef.current?.api.exportDataAsCsv({
      fileName: `getpaid-invoices-${todayIso()}.csv`,
      columnKeys: ["milestone_title", "client_name", "amount", "due_date", "daysLate", "state", "sent_at"],
      skipPinnedBottom: true,
      // Plain numbers and dates are easier for accountants than formatted text.
      processCellCallback: (p) => {
        const id = p.column.getColId();
        if (id === "amount") return p.value?.toFixed(2) ?? "";
        if (id === "sent_at") return p.value ? String(p.value).slice(0, 10) : "";
        return p.value ?? "";
      },
    });
  }

  const columns = useMemo<ColDef<Invoice>[]>(
    () => [
      { headerName: "Payment", field: "milestone_title", flex: 2, minWidth: 160, filter: "agTextColumnFilter", tooltipField: "milestone_title" },
      {
        headerName: "Client", field: "client_name", flex: 1.3, minWidth: 140, cellRenderer: ContractCell, tooltipField: "client_name",
        filter: "agTextColumnFilter",
      },
      {
        headerName: "Amount", field: "amount", width: 140, type: "rightAligned", filter: "agNumberColumnFilter",
        valueFormatter: (p) => money(p.value, p.data?.currency),
      },
      {
        headerName: "Due", field: "due_date", width: 120,
        valueFormatter: (p) => (p.node?.rowPinned ? "" : niceDate(p.value)),
      },
      {
        headerName: "Days late", colId: "daysLate", width: 110, type: "rightAligned", filter: "agNumberColumnFilter",
        valueGetter: (p) => (p.data && !p.node?.rowPinned ? daysLate(p.data) : null),
        cellClassRules: { "cell-late": (p) => (p.value ?? 0) > 0 },
      },
      {
        headerName: "Status", colId: "state", width: 200, cellRenderer: StatusCell,
        valueGetter: (p) => (p.data && !p.node?.rowPinned ? invoiceState(p.data.status, p.data.due_date).label : ""),
      },
      {
        headerName: "Sent", field: "sent_at", width: 110,
        valueFormatter: (p) => (p.node?.rowPinned ? "" : niceDate(p.value)),
      },
      {
        headerName: "", colId: "actions", width: 145, sortable: false, filter: false, cellRenderer: ActionsCell,
        getQuickFilterText: () => "",
      },
    ],
    []
  );

  const counts = useMemo(() => {
    const result: Record<View, number> = { all: 0, unpaid: 0, waiting: 0, overdue: 0, paid: 0 };
    for (const inv of invoices ?? []) {
      result.all += 1;
      const tone = toneOf(inv);
      if (tone === "waiting" || tone === "overdue" || tone === "paid") result[tone] += 1;
      if (tone === "waiting" || tone === "overdue") result.unpaid += 1;
    }
    return result;
  }, [invoices]);

  const total = summary ? Math.max(summary.invoiced, 0.01) : 1;
  const waiting = summary ? summary.outstanding - summary.overdue : 0;

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Invoices</h1>
        <button className="button button-primary" onClick={checkPayments} disabled={checking}>
          {checking ? "Checking PayPal…" : "Check for payments"}
        </button>
      </div>

      {message && <p className="notice" role="status">{message}</p>}
      {error && <p className="error-text" role="alert">{error}</p>}

      {summary && summary.invoice_count > 0 && (
        <section className="ledger" aria-label="Payment summary">
          <div className="ledger-bar" aria-hidden="true">
            <span className="ledger-paid" style={{ width: `${(summary.paid / total) * 100}%` }} />
            <span className="ledger-waiting" style={{ width: `${(waiting / total) * 100}%` }} />
            <span className="ledger-overdue" style={{ width: `${(summary.overdue / total) * 100}%` }} />
          </div>
          <dl className="ledger-figures">
            <div><dt><i className="dot dot-paid" />Paid</dt><dd>{money(summary.paid, summary.currency)}</dd></div>
            <div><dt><i className="dot dot-waiting" />Waiting</dt><dd>{money(waiting, summary.currency)}</dd></div>
            <div><dt><i className="dot dot-overdue" />Overdue</dt><dd>{money(summary.overdue, summary.currency)}</dd></div>
            <div><dt>Invoiced in total</dt><dd>{money(summary.invoiced, summary.currency)}</dd></div>
          </dl>
        </section>
      )}

      {invoices === null && !error && <p className="muted">Loading invoices…</p>}

      {invoices && invoices.length === 0 && (
        <div className="empty">
          <h2>No invoices yet</h2>
          <p>Review a contract and send its invoices. They'll show up here.</p>
          <a className="button button-primary" href="#/">Go to contracts</a>
        </div>
      )}

      {invoices && invoices.length > 0 && (
        <>
          <form className="ask" onSubmit={(e) => { e.preventDefault(); ask(question); }}>
            <label htmlFor="ask-input" className="ask-label">Ask your invoices</label>
            <div className="ask-row">
              <input
                id="ask-input"
                className="ask-input"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="e.g. overdue invoices from Northwind over $1,000"
                disabled={asking}
              />
              <button className="button button-primary" type="submit" disabled={asking || question.trim().length < 2}>
                {asking ? "Filtering…" : "Ask"}
              </button>
            </div>
            {answer ? (
              <p className="ask-answer" role="status">
                <span className="ask-badge">AI filter</span>
                {answer.explanation}
                <button type="button" className="link-button" onClick={clearAll}>Clear</button>
              </p>
            ) : (
              <p className="ask-examples">
                Try:
                {EXAMPLES.map((example) => (
                  <button key={example} type="button" className="chip" onClick={() => ask(example)} disabled={asking}>
                    {example}
                  </button>
                ))}
              </p>
            )}
          </form>

          <div className="grid-toolbar">
            <div className="segmented" role="group" aria-label="Show invoices">
              {VIEWS.map((v) => (
                <button
                  key={v.key}
                  className={view === v.key ? "is-on" : ""}
                  aria-pressed={view === v.key}
                  onClick={() => setView(v.key)}
                >
                  {v.label} <span className="count">{counts[v.key]}</span>
                </button>
              ))}
            </div>
            <input
              className="grid-search"
              type="search"
              placeholder="Search client or payment"
              aria-label="Search invoices"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <span className="spacer" />
            <span className="muted grid-count">Showing {shown} of {invoices.length}</span>
            <button className="button" onClick={exportCsv}>Export CSV</button>
          </div>

          <div className="grid-wrap">
            <AgGridReact<Invoice>
              ref={gridRef}
              theme={gridTheme}
              rowData={invoices}
              columnDefs={columns}
              defaultColDef={{ sortable: true, resizable: true, filter: false }}
              domLayout="autoHeight"
              getRowId={(p) => p.data.paypal_invoice_id}
              quickFilterText={search}
              isExternalFilterPresent={isExternalFilterPresent}
              doesExternalFilterPass={doesExternalFilterPass}
              pinnedBottomRowData={totalRow}
              onFilterChanged={updateTotals}
              onRowDataUpdated={updateTotals}
              onFirstDataRendered={updateTotals}
              rowClassRules={{ "row-just-paid": (p) => !!p.data && justPaid.has(p.data.paypal_invoice_id) }}
              overlayNoRowsTemplate="<span>No invoices match this view.</span>"
            />
          </div>
        </>
      )}
    </div>
  );
}
