// Amounts arrive pre-formatted from the backend (single source of truth, incl. Indian grouping).
// These helpers only handle dates and small client-side money maths in integer minor units.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${String(d).padStart(2, "0")} ${MONTHS[m - 1]} ${y}`;
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return iso;
  return dt.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

const SYMBOLS: Record<string, string> = { INR: "₹", USD: "$", EUR: "€", GBP: "£" };

function groupIndian(int: string): string {
  if (int.length <= 3) return int;
  let head = int.slice(0, -3);
  const tail = int.slice(-3);
  const groups: string[] = [];
  while (head.length > 2) {
    groups.unshift(head.slice(-2));
    head = head.slice(0, -2);
  }
  if (head) groups.unshift(head);
  return [...groups, tail].join(",");
}

/** Mirror of backend money.format_amount, used only for values computed in the browser. */
export function fmtMinor(minor: number, currency: string): string {
  const neg = minor < 0;
  const abs = Math.abs(minor);
  const int = Math.floor(abs / 100).toString();
  const frac = (abs % 100).toString().padStart(2, "0");
  const grouped = currency === "INR" ? groupIndian(int) : int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const s = `${SYMBOLS[currency] ?? currency + " "}${grouped}.${frac}`;
  return neg ? `-${s}` : s;
}

export const TDS_TOLERANCE_MINOR = 100;

export function expectedTds(subtotalMinor: number): number {
  return Math.round(subtotalMinor / 10);
}

export function titleCase(s: string | null | undefined): string {
  return (s ?? "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
