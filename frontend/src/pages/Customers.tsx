import { useState } from "react";
import { api } from "../api/client";
import type { Customer } from "../api/types";
import { Badge, Button, Card, ErrorBanner, Modal, PageHeader, Spinner, useAsync } from "../components/ui";

export default function Customers() {
  const { data, error, loading, reload } = useAsync(() => api.get<Customer[]>("/customers"));
  const [editing, setEditing] = useState<Customer | null>(null);
  return (
    <div>
      <PageHeader title="Customers" subtitle="Edit a contact email to point reminders and inbound-mail matching at a test inbox" />
      <ErrorBanner error={error} />
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr><th className="px-4 py-2">ID</th><th className="px-4 py-2">Customer</th><th className="px-4 py-2">Contact</th><th className="px-4 py-2">Email</th><th className="px-4 py-2">Currency</th><th className="px-4 py-2 text-right">Outstanding</th><th className="px-4 py-2">Invoices</th><th /></tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && !data && <tr><td colSpan={8} className="p-6 text-center"><Spinner /></td></tr>}
            {data?.map((c) => (
              <tr key={c.customer_id} className="hover:bg-slate-50">
                <td className="px-4 py-2 font-mono text-xs text-slate-500">{c.customer_id}</td>
                <td className="px-4 py-2"><div className="font-medium text-slate-900">{c.name}</div><div className="text-xs text-slate-500">{c.city}, {c.country}</div></td>
                <td className="px-4 py-2">{c.contact_name}</td>
                <td className="px-4 py-2 font-mono text-xs">{c.contact_email}{c.contact_email.endsWith("@example.com") && <span className="ml-1"><Badge tone="amber" title="example.com cannot receive mail; reminders skip it">placeholder</Badge></span>}</td>
                <td className="px-4 py-2">{c.currency}</td>
                <td className="num px-4 py-2 text-right">{c.outstanding_display}</td>
                <td className="px-4 py-2 text-xs text-slate-600">{c.open_count} open{c.overdue_count > 0 && <> · <span className="text-rose-600">{c.overdue_count} overdue</span></>}</td>
                <td className="px-4 py-2 text-right"><Button onClick={() => setEditing(c)}>Edit</Button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      {editing && <EditCustomer customer={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload(); }} />}
    </div>
  );
}

function EditCustomer({ customer, onClose, onSaved }: { customer: Customer; onClose: () => void; onSaved: () => void }) {
  const [email, setEmail] = useState(customer.contact_email);
  const [aliases, setAliases] = useState(customer.aliases.join("\n"));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/customers/${customer.customer_id}`, {
        contact_email: email,
        aliases: aliases.split("\n").map((a) => a.trim()).filter(Boolean),
      });
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open title={`Edit ${customer.name}`} onClose={onClose}>
      <ErrorBanner error={error} />
      <label className="block text-sm text-slate-700">Contact email
        <input type="email" className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 font-mono text-sm" value={email} onChange={(e) => setEmail(e.target.value)} maxLength={254} />
      </label>
      <p className="mt-1 text-xs text-slate-500">Saved lowercased. Incoming mail from this address is matched to {customer.name}.</p>
      <label className="mt-4 block text-sm text-slate-700">Payer aliases (one per line, optional)
        <textarea rows={3} className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" value={aliases} onChange={(e) => setAliases(e.target.value)} placeholder="e.g. trading name used on bank transfers" />
      </label>
      <p className="mt-1 text-xs text-slate-500">Aliases are extra names the bank-matching algorithm compares narrations against.</p>
      <div className="mt-4 flex justify-end gap-2"><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} onClick={save}>Save</Button></div>
    </Modal>
  );
}
