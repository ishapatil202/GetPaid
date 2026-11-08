// Talks to the FastAPI backend.
const API_URL =
  ((import.meta.env.VITE_API_URL as string | undefined) || "http://localhost:8000").replace(/\/$/, "");

const TOKEN_KEY = "getpaid_token";
const NAME_KEY = "getpaid_name";

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function writeStorage(key: string, value: string | null) {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: keep the session in memory only */
  }
}

let token: string | null = readStorage(TOKEN_KEY);
let userName: string | null = readStorage(NAME_KEY);

export function getSession() {
  return token ? { token, name: userName || "" } : null;
}
export function setSession(t: string | null, name: string | null) {
  token = t;
  userName = name;
  writeStorage(TOKEN_KEY, t);
  writeStorage(NAME_KEY, name);
}

// ---------- types (match backend/app/api_schemas.py) ----------

export type Issue = { code: string; severity: "high" | "medium" | "low"; message: string };
export type Highlight = { field: string; quote: string; start: number | null; end: number | null; found: boolean };

export type Invoice = {
  id: number;
  paypal_invoice_id: string;
  invoice_number: string | null;
  status: string;
  amount: number;
  currency: string;
  due_date: string | null;
  pay_link: string | null;
  sent_to: string | null;
  sent_at: string;
  paid_at: string | null;
  milestone_title: string | null;
  contract_id: number | null;
  contract_title: string | null;
  client_name: string | null;
};

export type Milestone = {
  id: number;
  position: number;
  title: string;
  amount: number;
  due_date: string | null;
  due_rule: string | null;
  source_quote: string;
  span_start: number | null;
  span_end: number | null;
  invoice: Invoice | null;
};

export type Contract = {
  id: number;
  title: string;
  raw_text: string;
  client_name: string | null;
  client_email: string | null;
  freelancer_name: string | null;
  currency: string;
  contract_total: number | null;
  payment_terms: string | null;
  late_fee: string | null;
  status: string;
  created_at: string;
  milestones: Milestone[];
  highlights: Highlight[];
  issues: Issue[];
  can_send: boolean;
  ai_model: string | null;
  ai_latency_ms: number | null;
};

export type ContractSummary = {
  id: number;
  title: string;
  client_name: string | null;
  contract_total: number | null;
  currency: string;
  status: string;
  created_at: string;
  milestone_count: number;
  paid_count: number;
};

export type Dashboard = {
  currency: string;
  invoiced: number;
  paid: number;
  outstanding: number;
  overdue: number;
  invoice_count: number;
  paid_count: number;
  overdue_count: number;
};

export type RefreshResult = {
  changed: { invoice: string; from: string; to: string }[];
  invoices: Invoice[];
};

export type AgentStep = { tool: string; summary: string; ok: boolean };
export type AgentRun = {
  id: number;
  started_at: string;
  finished_at: string | null;
  steps: AgentStep[];
  summary: string;
  invoices_checked: number;
  late_found: number;
  drafts_created: number;
};
export type Reminder = {
  id: number;
  invoice_id: number;
  paypal_invoice_id: string;
  pay_link: string | null;
  milestone_title: string;
  client_name: string | null;
  contract_id: number;
  amount: number;
  currency: string;
  due_date: string | null;
  days_overdue: number;
  tone: "friendly" | "firm";
  subject: string;
  body: string;
  contract_quote: string | null;
  quote_verified: boolean;
  status: "draft" | "sent" | "skipped";
  created_at: string;
  sent_at: string | null;
};

export type AskResult = {
  status: "all" | "unpaid" | "waiting" | "overdue" | "paid";
  client_contains: string | null;
  payment_contains: string | null;
  amount_min: number | null;
  amount_max: number | null;
  days_late_min: number | null;
  sort_by: "amount" | "due_date" | "days_late" | "sent_at" | null;
  sort_direction: "asc" | "desc" | null;
  explanation: string;
  model: string;
  latency_ms: number;
};

// ---------- requests ----------

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(API_URL + path, {
      method,
      headers: {
        // FormData (file uploads) sets its own content type.
        ...(body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
    });
  } catch {
    throw new Error("Can't reach the GetPaid server. Make sure the backend is running.");
  }
  const data = await response.json().catch(() => null);
  if (response.status === 401) {
    setSession(null, null);
    window.dispatchEvent(new Event("getpaid:logout"));
  }
  if (!response.ok) {
    const detail = data?.detail;
    let message = `Request failed (${response.status}).`;
    if (typeof detail === "string") message = detail;
    else if (detail?.message) message = [detail.message, ...(detail.issues || [])].join(" ");
    else if (Array.isArray(detail)) message = detail.map((d: { msg: string }) => d.msg).join(" ");
    throw new Error(message);
  }
  return data as T;
}

export const api = {
  demoLogin: () => request<{ token: string; name: string; email: string }>("POST", "/auth/demo"),
  contracts: () => request<ContractSummary[]>("GET", "/contracts"),
  contract: (id: number) => request<Contract>("GET", `/contracts/${id}`),
  createContract: (text: string) => request<Contract>("POST", "/contracts", { text }),
  uploadContract: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Contract>("POST", "/contracts/upload", form);
  },
  updateContract: (id: number, body: Partial<Pick<Contract, "client_name" | "client_email" | "contract_total">>) =>
    request<Contract>("PATCH", `/contracts/${id}`, body),
  updateMilestone: (id: number, body: { title?: string; amount?: number; due_date?: string }) =>
    request<Contract>("PATCH", `/milestones/${id}`, body),
  sendInvoices: (id: number) => request<Contract>("POST", `/contracts/${id}/send`),
  invoices: () => request<Invoice[]>("GET", "/invoices"),
  refresh: () => request<RefreshResult>("POST", "/invoices/refresh"),
  dashboard: () => request<Dashboard>("GET", "/dashboard"),
  askInvoices: (question: string) => request<AskResult>("POST", "/invoices/ask", { question }),
  runAgent: () => request<{ run: AgentRun; reminders: Reminder[] }>("POST", "/agent/run"),
  latestRun: () => request<AgentRun | null>("GET", "/agent/runs/latest"),
  reminders: () => request<Reminder[]>("GET", "/reminders"),
  editReminder: (id: number, body: { subject?: string; body?: string }) =>
    request<Reminder>("PATCH", `/reminders/${id}`, body),
  approveReminder: (id: number) => request<Reminder>("POST", `/reminders/${id}/approve`),
  skipReminder: (id: number) => request<Reminder>("POST", `/reminders/${id}/skip`),
};
