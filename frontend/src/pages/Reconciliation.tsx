import { useMemo, useRef, useState } from "react";
import { api, downloadFile } from "../api/client";
import type { Invoice, Statement, StatementDetail, Suggestion, Transaction } from "../api/types";
import { Badge, bandTone, Button, Card, EmptyState, ErrorBanner, Notice, PageHeader, Spinner, useAsync } from "../components/ui";
import { expectedTds, fmtDate, fmtDateTime, fmtMinor, TDS_TOLERANCE_MINOR } from "../lib/format";
import { InvoiceModal } from "./Invoices";

export default function Reconciliation() {
  const statements = useAsync(() => api.get<Statement[]>("/reconciliation/statements"));
  const [selected, setSelected] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const current = selected ?? statements.data?.[0]?.id ?? null;

  const upload = async (file: File) => {
    setBusy(true); setUploadError(null);
    try {
      if (!file.name.toLowerCase().endsWith(".csv")) throw new Error("Please choose a .csv file");
      if (file.size > 2 * 1024 * 1024) throw new Error("File is larger than 2 MB");
      const form = new FormData();
      form.append("file", file);
      const st = await api.upload<Statement>("/reconciliation/statements", form);
      statements.reload();
      setSelected(st.id);
    } catch (e) { setUploadError((e as Error).message); } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <div>
      <PageHeader title="Bank Reconciliation" subtitle="Suggestions are computed locally; nothing changes until you approve"
        actions={<>
          {statements.data && statements.data.length > 0 && (
            <select value={current ?? ""} onChange={(e) => setSelected(e.target.value)} className="rounded-md border border-slate-300 px-2 py-1.5 text-sm">
              {statements.data.map((s) => <option key={s.id} value={s.id}>{s.filename} · {fmtDateTime(s.uploaded_at)}</option>)}
            </select>
          )}
          <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          <Button variant="primary" busy={busy} onClick={() => fileRef.current?.click()}>Upload statement CSV</Button>
        </>} />
      <ErrorBanner error={uploadError ?? statements.error} onClose={() => setUploadError(null)} />
      {statements.loading && !statements.data && <Spinner />}
      {statements.data?.length === 0 && <Card><EmptyState>Upload a bank statement CSV (columns: txn_date, narration, reference, credit, debit, currency).</EmptyState></Card>}
      {current && <StatementView id={current} />}
    </div>
  );
}

function StatementView({ id }: { id: string }) {
  const detail = useAsync(() => api.get<StatementDetail>(`/reconciliation/statements/${id}`), [id]);
  const invoices = useAsync(() => api.get<Invoice[]>("/invoices?status=sent"), [id]);
  const [showAll, setShowAll] = useState(true);
  const [invoiceOpen, setInvoiceOpen] = useState<string | null>(null);
  const refresh = () => { detail.reload(); invoices.reload(); };
  if (detail.error) return <ErrorBanner error={detail.error} />;
  if (!detail.data) return <Spinner />;
  const { statement: st, rows } = detail.data;
  const visible = rows.filter((r) => showAll || r.transaction.direction === "credit");
  const pending = rows.filter((r) => r.suggestion?.status === "pending" && r.transaction.status !== "approved").length;
  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-3 text-sm text-slate-600">
        <span>{st.row_count} rows · {st.credit_count} receipts · {st.suggested_count} suggestions · {pending} awaiting review{st.duplicate_count ? ` · ${st.duplicate_count} duplicates` : ""}</span>
        <label className="ml-auto flex items-center gap-1"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> show debits</label>
        <Button onClick={() => downloadFile(`/reconciliation/statements/${id}/export.csv`, `reconciliation-${st.filename}`)}>Export CSV</Button>
      </div>
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr><th className="px-3 py-2">Date</th><th className="px-3 py-2">Narration</th><th className="px-3 py-2 text-right">Amount</th><th className="px-3 py-2">Suggestion</th><th className="px-3 py-2">Confidence</th><th className="px-3 py-2 w-[26rem]">Review</th></tr>
          </thead>
          <tbody className="divide-y divide-slate-100 align-top">
            {visible.map(({ transaction: t, suggestion: s }) => (
              <Row key={t.id} t={t} s={s} openInvoices={invoices.data ?? []} onChanged={refresh} onOpenInvoice={setInvoiceOpen} />
            ))}
          </tbody>
        </table>
      </Card>
      {invoiceOpen && <InvoiceModal number={invoiceOpen} onClose={() => setInvoiceOpen(null)} />}
    </>
  );
}

function Row({ t, s, openInvoices, onChanged, onOpenInvoice }: {
  t: Transaction; s: Suggestion | null; openInvoices: Invoice[]; onChanged: () => void; onOpenInvoice: (n: string) => void;
}) {
  return (
    <tr className={t.direction === "debit" ? "bg-slate-50/50 text-slate-400" : ""}>
      <td className="px-3 py-2 whitespace-nowrap">{fmtDate(t.txn_date)}</td>
      <td className="px-3 py-2"><div className="font-mono text-xs break-words text-slate-800">{t.narration}</div>{t.reference && <div className="font-mono text-xs text-slate-400">ref {t.reference}</div>}</td>
      <td className={`num px-3 py-2 text-right whitespace-nowrap ${t.direction === "credit" ? "font-medium text-emerald-700" : ""}`}>{t.direction === "debit" ? "-" : "+"}{t.amount_display}</td>
      <td className="px-3 py-2">
        {t.direction === "debit" ? <span className="text-xs">Debit: not reconciled</span>
          : t.status === "duplicate" ? <Badge tone="amber">Duplicate of an earlier upload</Badge>
          : s && s.allocations.length > 0 ? (
            <div className="space-y-0.5">
              {s.allocations.map((a) => (
                <div key={a.invoice_number}>
                  <button className="font-medium text-sky-700 hover:underline" onClick={() => onOpenInvoice(a.invoice_number)}>{a.invoice_number}</button>
                  <span className="text-xs text-slate-500"> {a.customer_name} · bal {a.balance_display}</span>
                </div>
              ))}
            </div>
          ) : <span className="text-slate-500">No match</span>}
        {s?.reason && <div className="mt-1 text-xs text-slate-600">{s.reason}</div>}
        {s?.signals?.email_hint && (
          <div className="mt-1 rounded border border-violet-200 bg-violet-50 px-2 py-1 text-xs text-violet-900">
            <span className="font-medium">Customer email{s.signals.email_hint.said_on ? ` (${fmtDate(s.signals.email_hint.said_on)})` : ""}:</span> “{s.signals.email_hint.excerpt}”
          </div>
        )}
      </td>
      <td className="px-3 py-2">{s && t.direction === "credit" && t.status !== "duplicate" && (<div className="flex flex-col items-start gap-1"><span className="num text-base font-semibold">{s.score}</span><Badge tone={bandTone(s.band)}>{s.band === "none" ? "no match" : s.band}</Badge></div>)}</td>
      <td className="px-3 py-2">{s && t.direction === "credit" && t.status !== "duplicate" && <Review t={t} s={s} openInvoices={openInvoices} onChanged={onChanged} />}</td>
    </tr>
  );
}

function Review({ t, s, openInvoices, onChanged }: { t: Transaction; s: Suggestion; openInvoices: Invoice[]; onChanged: () => void }) {
  const suggested = s.allocations.map((a) => a.invoice_number);
  const [choice, setChoice] = useState<string>(""); // "" = use suggestion
  const [closeTds, setCloseTds] = useState<boolean>(s.amount_kind === "tds" || s.amount_kind === "group_tds");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const sameCurrency = useMemo(() => openInvoices.filter((i) => i.currency === t.currency && i.balance_minor > 0), [openInvoices, t.currency]);
  const altNumbers = s.alternatives.filter((a) => a.invoice_numbers.length === 1).map((a) => a.invoice_numbers[0]);
  const target: string[] = choice ? [choice] : suggested;
  const targetInvoices = target.map((n) => openInvoices.find((i) => i.invoice_number === n)).filter(Boolean) as Invoice[];

  if (s.status === "approved" || t.status === "approved") {
    return (
      <div className="text-xs text-emerald-800">
        <Badge tone="green">Approved</Badge> by {s.approved_by}
        <ul className="mt-1">{s.applied?.map((a) => <li key={a.invoice_number}>{a.invoice_number}: {fmtMinor(a.amount_minor, t.currency)}{a.tds_minor > 0 && ` + TDS ${fmtMinor(a.tds_minor, t.currency)}`} → {a.new_status}</li>)}</ul>
      </div>
    );
  }

  // Shortfall handling for a single invoice: leave open, or close with TDS when plausible.
  let shortfall = 0;
  let tdsPlausible = false;
  let expected = 0;
  if (targetInvoices.length === 1) {
    const inv = targetInvoices[0];
    shortfall = inv.balance_minor - t.amount_minor;
    expected = expectedTds(inv.subtotal_minor);
    tdsPlausible = inv.currency === "INR" && inv.amount_paid_minor === 0 && inv.tds_minor === 0 && shortfall > 0 && Math.abs(shortfall - expected) <= TDS_TOLERANCE_MINOR;
  }
  const isGroupTds = !choice && s.amount_kind === "group_tds";
  const over = targetInvoices.length === 1 && shortfall < 0;

  const approve = async () => {
    setBusy("approve"); setError(null);
    try {
      await api.post(`/reconciliation/suggestions/${s.id}/approve`, { invoice_numbers: choice ? [choice] : null, close_with_tds: isGroupTds || (tdsPlausible && closeTds) });
      onChanged();
    } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  };
  const reject = async () => {
    setBusy("reject"); setError(null);
    try { await api.post(`/reconciliation/suggestions/${s.id}/reject`, { reason: null }); onChanged(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  };

  return (
    <div className="space-y-2">
      {error && <div className="rounded border border-rose-200 bg-rose-50 px-2 py-1 text-xs text-rose-700">{error}</div>}
      {s.status === "rejected" && <Badge tone="red">Suggestion rejected: choose an invoice or leave unmatched</Badge>}
      <select value={choice} onChange={(e) => setChoice(e.target.value)} className="w-full rounded-md border border-slate-300 px-2 py-1 text-xs">
        <option value="">{suggested.length ? `Suggested: ${suggested.join(" + ")}` : "Choose an invoice…"}</option>
        {altNumbers.length > 0 && <optgroup label="Alternatives">{altNumbers.map((n) => { const inv = sameCurrency.find((i) => i.invoice_number === n); return inv ? <option key={n} value={n}>{n} · {inv.customer_name} · bal {inv.display.balance}</option> : null; })}</optgroup>}
        <optgroup label={`All open ${t.currency} invoices`}>{sameCurrency.filter((i) => !altNumbers.includes(i.invoice_number)).map((i) => <option key={i.invoice_number} value={i.invoice_number}>{i.invoice_number} · {i.customer_name} · bal {i.display.balance}</option>)}</optgroup>
      </select>
      {over && <Notice tone="amber">Receipt exceeds this invoice's balance; over-payments are not applied.</Notice>}
      {targetInvoices.length === 1 && shortfall > 0 && (
        <div className="rounded-md border border-slate-200 bg-slate-50 p-2 text-xs">
          <div className="mb-1 text-slate-700">Receipt is {fmtMinor(shortfall, t.currency)} less than the balance.</div>
          <label className="flex items-center gap-1"><input type="radio" checked={!closeTds || !tdsPlausible} onChange={() => setCloseTds(false)} /> Leave balance open</label>
          <label className={`flex items-center gap-1 ${tdsPlausible ? "" : "text-slate-400"}`} title={tdsPlausible ? "" : "Only for INR invoices where the shortfall equals 10% of the subtotal"}>
            <input type="radio" disabled={!tdsPlausible} checked={closeTds && tdsPlausible} onChange={() => setCloseTds(true)} />
            Close invoice (TDS deducted{expected && t.currency === "INR" ? `: 10% of subtotal = ${fmtMinor(expected, t.currency)}` : ""})
          </label>
        </div>
      )}
      {isGroupTds && <div className="text-xs text-violet-700">Each invoice closes with 10% TDS deducted.</div>}
      <div className="flex gap-2">
        <Button variant="success" busy={busy === "approve"} disabled={target.length === 0 || over} onClick={approve}>{choice ? "Approve chosen" : "Approve"}</Button>
        {s.status !== "rejected" && suggested.length > 0 && <Button variant="secondary" busy={busy === "reject"} onClick={reject}>Reject</Button>}
      </div>
    </div>
  );
}
