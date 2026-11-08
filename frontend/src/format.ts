export function money(value: number | null | undefined, currency = "USD") {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(value);
}

export function niceDate(iso: string | null | undefined) {
  if (!iso) return "—";
  const date = iso.length === 10 ? new Date(iso + "T00:00:00") : new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function todayIso() {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const PAID = new Set(["PAID", "MARKED_AS_PAID"]);
const CLOSED = new Set(["PAID", "MARKED_AS_PAID", "CANCELLED", "REFUNDED", "MARKED_AS_REFUNDED"]);

// Friendly status shown to the user, including "Overdue", which PayPal doesn't report itself.
export function invoiceState(status: string, dueDate: string | null): { label: string; tone: string } {
  if (PAID.has(status)) return { label: "Paid", tone: "paid" };
  if (status === "PARTIALLY_PAID") return { label: "Partly paid", tone: "waiting" };
  if (status === "CANCELLED") return { label: "Cancelled", tone: "muted" };
  if (CLOSED.has(status)) return { label: "Refunded", tone: "muted" };
  if (dueDate && dueDate < todayIso()) return { label: "Overdue", tone: "overdue" };
  return { label: "Waiting for payment", tone: "waiting" };
}
