import { useCallback, useEffect, useMemo, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import { AllCommunityModule, ColDef, ICellRendererParams, ModuleRegistry, themeQuartz } from "ag-grid-community";
import { api, Dashboard, Invoice } from "../api";
import { invoiceState, money, niceDate } from "../format";

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

function StatusCell(params: ICellRendererParams<Invoice>) {
  if (!params.data) return null;
  const state = invoiceState(params.data.status, params.data.due_date);
  return <span className={`badge badge-${state.tone}`}>{state.label}</span>;
}

function LinkCell(params: ICellRendererParams<Invoice>) {
  const link = params.data?.pay_link;
  return link ? <a href={link} target="_blank" rel="noreferrer">Open in PayPal</a> : null;
}

function ContractCell(params: ICellRendererParams<Invoice>) {
  const d = params.data;
  if (!d) return null;
  return d.contract_id ? <a href={`#/contracts/${d.contract_id}`}>{d.client_name || d.contract_title}</a> : <>{d.client_name}</>;
}

export default function Invoices() {
  const [invoices, setInvoices] = useState<Invoice[] | null>(null);
  const [summary, setSummary] = useState<Dashboard | null>(null);
  const [checking, setChecking] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [justPaid, setJustPaid] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    const [list, dash] = await Promise.all([api.invoices(), api.dashboard()]);
    setInvoices(list);
    setSummary(dash);
  }, []);

  useEffect(() => {
    load().catch((e: Error) => setError(e.message));
  }, [load]);

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

  const columns = useMemo<ColDef<Invoice>[]>(
    () => [
      { headerName: "Payment", field: "milestone_title", flex: 2, minWidth: 220 },
      { headerName: "Client", field: "client_name", flex: 1, minWidth: 160, cellRenderer: ContractCell },
      {
        headerName: "Amount", field: "amount", width: 130, type: "rightAligned",
        valueFormatter: (p) => money(p.value, p.data?.currency),
      },
      { headerName: "Due", field: "due_date", width: 140, valueFormatter: (p) => niceDate(p.value) },
      {
        headerName: "Status", colId: "state", width: 190, cellRenderer: StatusCell,
        valueGetter: (p) => (p.data ? invoiceState(p.data.status, p.data.due_date).label : ""),
      },
      { headerName: "Sent", field: "sent_at", width: 140, valueFormatter: (p) => niceDate(p.value) },
      { headerName: "", colId: "link", width: 150, sortable: false, cellRenderer: LinkCell },
    ],
    []
  );

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
        <div className="grid-wrap">
          <AgGridReact<Invoice>
            theme={gridTheme}
            rowData={invoices}
            columnDefs={columns}
            domLayout="autoHeight"
            getRowId={(p) => p.data.paypal_invoice_id}
            rowClassRules={{ "row-just-paid": (p) => !!p.data && justPaid.has(p.data.paypal_invoice_id) }}
          />
        </div>
      )}
    </div>
  );
}
