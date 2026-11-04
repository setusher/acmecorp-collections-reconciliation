import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { Invoice, InvoiceDetail } from "../api/types";
import { Badge, Card, ErrorBanner, Modal, PageHeader, Spinner, statusTone, useAsync } from "../components/ui";
import { fmtDate, fmtDateTime } from "../lib/format";

export default function Invoices() {
  const { data, error, loading } = useAsync(() => api.get<Invoice[]>("/invoices"));
  const [filter, setFilter] = useState<"all" | "overdue" | "sent" | "paid" | "draft">("all");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const rows = useMemo(() => (data ?? []).filter((i) =>
    (filter === "all" || (filter === "overdue" ? i.overdue : i.status === filter)) &&
    (!q || `${i.invoice_number} ${i.customer_name} ${i.po_number ?? ""}`.toLowerCase().includes(q.toLowerCase()))), [data, filter, q]);
  return (
    <div>
      <PageHeader title="Invoices" subtitle="Overdue = sent, balance unpaid and past the due date (computed, not stored)" actions={
        <>
          <input placeholder="Search number, customer, PO" value={q} onChange={(e) => setQ(e.target.value)} className="w-60 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
          <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)} className="rounded-md border border-slate-300 px-2 py-1.5 text-sm">
            <option value="all">All</option><option value="overdue">Overdue</option><option value="sent">Sent</option><option value="paid">Paid</option><option value="draft">Draft</option>
          </select>
        </>
      } />
      <ErrorBanner error={error} />
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr><th className="px-3 py-2">Invoice</th><th className="px-3 py-2">Customer</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Due</th><th className="px-3 py-2">Cur</th><th className="px-3 py-2 text-right">Subtotal</th><th className="px-3 py-2 text-right">Total</th><th className="px-3 py-2 text-right">Paid</th><th className="px-3 py-2 text-right">Balance</th></tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && !data && <tr><td colSpan={9} className="p-6 text-center"><Spinner /></td></tr>}
            {rows.map((i) => (
              <tr key={i.invoice_number} className="cursor-pointer hover:bg-slate-50" onClick={() => setOpen(i.invoice_number)}>
                <td className="px-3 py-2 font-medium text-slate-900">{i.invoice_number}</td>
                <td className="px-3 py-2">{i.customer_name}</td>
                <td className="px-3 py-2"><span className="flex gap-1"><Badge tone={statusTone(i.status)}>{i.status}</Badge>{i.overdue && <Badge tone="red">Overdue {i.days_overdue}d</Badge>}</span></td>
                <td className="px-3 py-2 whitespace-nowrap">{fmtDate(i.due_date)}</td>
                <td className="px-3 py-2">{i.currency}</td>
                <td className="num px-3 py-2 text-right">{i.display.subtotal}</td>
                <td className="num px-3 py-2 text-right">{i.display.total}</td>
                <td className="num px-3 py-2 text-right text-slate-600">{i.display.amount_paid}{i.tds_minor > 0 && <div className="text-xs text-violet-600">+ TDS {i.display.tds}</div>}</td>
                <td className={`num px-3 py-2 text-right font-medium ${i.balance_minor > 0 ? "text-slate-900" : "text-slate-400"}`}>{i.display.balance}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      {open && <InvoiceModal number={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

export function InvoiceModal({ number, onClose }: { number: string; onClose: () => void }) {
  const { data: inv, error } = useAsync(() => api.get<InvoiceDetail>(`/invoices/${number}`), [number]);
  return (
    <Modal open title={number} onClose={onClose} wide>
      <ErrorBanner error={error} />
      {!inv ? <Spinner /> : (
        <div className="space-y-4 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{inv.customer_name}</span><Badge tone={statusTone(inv.status)}>{inv.status}</Badge>{inv.overdue && <Badge tone="red">Overdue {inv.days_overdue} days</Badge>}
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 md:grid-cols-4">
            <div><div className="text-xs text-slate-500">Invoice date</div>{fmtDate(inv.invoice_date)}</div>
            <div><div className="text-xs text-slate-500">Due date</div>{fmtDate(inv.due_date)} ({inv.payment_terms})</div>
            <div><div className="text-xs text-slate-500">PO</div>{inv.po_number ?? "-"}</div>
            <div><div className="text-xs text-slate-500">Tax</div>{inv.tax_name}</div>
          </div>
          <table className="w-full">
            <thead className="text-left text-xs text-slate-500"><tr><th className="py-1">Item</th><th>Qty</th><th className="text-right">Unit price</th><th className="text-right">Amount</th></tr></thead>
            <tbody>{inv.line_items.map((li, idx) => (<tr key={idx} className="border-t border-slate-100"><td className="py-1">{li.description}</td><td>{li.quantity}</td><td className="num text-right">{li.unit_price_display}</td><td className="num text-right">{li.amount_display}</td></tr>))}</tbody>
          </table>
          <dl className="ml-auto grid w-72 grid-cols-2 gap-y-1">
            <dt className="text-slate-500">Subtotal</dt><dd className="num text-right">{inv.display.subtotal}</dd>
            <dt className="text-slate-500">Discount</dt><dd className="num text-right">{inv.display.discount}</dd>
            <dt className="text-slate-500">Tax</dt><dd className="num text-right">{inv.display.tax}</dd>
            <dt className="font-medium">Total</dt><dd className="num text-right font-medium">{inv.display.total}</dd>
            <dt className="text-slate-500">Amount paid</dt><dd className="num text-right">{inv.display.amount_paid}</dd>
            <dt className="text-slate-500">TDS settled</dt><dd className="num text-right">{inv.display.tds}</dd>
            <dt className="font-semibold">Balance unpaid</dt><dd className="num text-right font-semibold">{inv.display.balance}</dd>
          </dl>
          {inv.payments.length > 0 && (
            <div><h3 className="mb-1 font-medium">Payments (approved)</h3>
              <ul className="space-y-1">{inv.payments.map((p, idx) => <li key={idx} className="text-slate-700">{fmtDate(p.txn_date)}: {p.amount_display}{p.tds_display && p.tds_display !== "₹0.00" && <> + TDS {p.tds_display}</>} · ref {p.reference || "-"} · approved by {p.approved_by} {fmtDateTime(p.approved_at)}</li>)}</ul>
            </div>
          )}
          {inv.notes.length > 0 && (
            <div><h3 className="mb-1 font-medium">Notes</h3>
              <ul className="space-y-1">{inv.notes.map((n, idx) => <li key={idx} className="text-slate-700"><Badge>{n.kind}</Badge> <span className="text-xs text-slate-500">{fmtDateTime(n.at)}</span> {n.text}</li>)}</ul>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
