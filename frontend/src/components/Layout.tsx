import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api/client";
import type { SystemStatus } from "../api/types";
import { fmtDate } from "../lib/format";
import { Badge, Button, ErrorBanner, Modal, useAsync } from "./ui";

const NAV = [
  ["/organization", "Organization"],
  ["/customers", "Customers"],
  ["/invoices", "Invoices"],
  ["/collections", "Collections"],
  ["/reconciliation", "Bank Reconciliation"],
  ["/audit", "Audit log"],
] as const;

export default function Layout({ onLogout }: { onLogout: () => void }) {
  const status = useAsync(() => api.get<SystemStatus>("/system/status"), []);
  const [resetOpen, setResetOpen] = useState(false);
  const s = status.data;
  return (
    <div className="flex min-h-screen">
      <aside className="w-56 shrink-0 border-r border-slate-200 bg-white">
        <div className="px-5 py-4">
          <div className="text-base font-semibold text-slate-900">AcmeCorp</div>
          <div className="text-xs text-slate-500">Accounts Team</div>
        </div>
        <nav className="flex flex-col gap-0.5 px-2">
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to} className={({ isActive }) => `rounded-md px-3 py-2 text-sm ${isActive ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-100"}`}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-6 space-y-2 px-5 text-xs text-slate-500">
          {s && (
            <>
              <div>Today: <span className="font-medium text-slate-700">{fmtDate(s.today)}</span>{s.as_of_date_pinned && <Badge tone="violet" title="APP_AS_OF_DATE is set">pinned</Badge>}</div>
              <div>Mail: <Badge tone={s.smtp_configured && s.imap_configured ? "green" : "amber"}>{s.smtp_configured && s.imap_configured ? "configured" : "not configured"}</Badge></div>
              <div>LLM: <Badge tone={s.llm_provider === "none" ? "amber" : "green"}>{s.llm_provider}</Badge></div>
            </>
          )}
        </div>
        <div className="mt-6 flex flex-col gap-2 px-5 pb-6">
          <Button variant="secondary" onClick={() => setResetOpen(true)}>Reset demo data</Button>
          <Button variant="ghost" onClick={onLogout}>Log out</Button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-8 py-6">
        <Outlet />
      </main>
      <ResetDialog open={resetOpen} onClose={() => setResetOpen(false)} />
    </div>
  );
}

function ResetDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post("/admin/reset", { confirm: text });
      window.location.reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} title="Reset demo data" onClose={onClose}>
      <ErrorBanner error={error} />
      <p className="text-sm text-slate-700">
        This restores organization, customers and invoices from <code>data/</code> and deletes all conversations, messages, payments,
        bank statements and suggestions. Customer emails return to the seed values (plus any <code>SEED_CUSTOMER_EMAILS</code> overrides).
      </p>
      <label className="mt-4 block text-sm text-slate-700">
        Type <span className="font-mono font-semibold">RESET</span> to confirm
        <input value={text} onChange={(e) => setText(e.target.value)} className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 font-mono" autoFocus />
      </label>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="danger" disabled={text !== "RESET"} busy={busy} onClick={submit}>Reset everything</Button>
      </div>
    </Modal>
  );
}
