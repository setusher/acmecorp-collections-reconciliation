import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { AttentionItem, ConversationDetail, ConversationSummary } from "../api/types";
import { Badge, Button, Card, EmptyState, ErrorBanner, Notice, PageHeader, PlainText, Spinner, statusTone, useAsync } from "../components/ui";
import { fmtDateTime, titleCase } from "../lib/format";

interface ReminderResult { sent: { customer: string; to: string; invoices: string[]; reminder_number: number }[]; skipped: { customer?: string; reason: string }[] }
interface InboxResult { fetched: number; results: { status: string; category?: string; reason?: string }[] }

export default function Collections() {
  const [tab, setTab] = useState<"attention" | "conversations">("attention");
  const [busy, setBusy] = useState<"rem" | "inbox" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<React.ReactNode>(null);
  const [refresh, setRefresh] = useState(0);
  const [force, setForce] = useState(false);

  const sendReminders = async () => {
    setBusy("rem"); setError(null); setSummary(null);
    try {
      const r = await api.post<ReminderResult>("/collections/send-reminders", { force });
      setSummary(<div>
        <div className="font-medium">Reminders: {r.sent.length} sent, {r.skipped.length} skipped</div>
        <ul className="mt-1 list-disc pl-5">
          {r.sent.map((s, i) => <li key={i}>Sent to {s.customer} ({s.to}): {s.invoices.join(", ")} (reminder #{s.reminder_number})</li>)}
          {r.skipped.map((s, i) => <li key={`s${i}`} className="text-slate-600">Skipped {s.customer ?? ""}: {s.reason}</li>)}
        </ul></div>);
      setRefresh((x) => x + 1);
    } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  };
  const checkInbox = async () => {
    setBusy("inbox"); setError(null); setSummary(null);
    try {
      const r = await api.post<InboxResult>("/collections/check-inbox");
      const counts = r.results.reduce<Record<string, number>>((acc, x) => ({ ...acc, [x.status]: (acc[x.status] ?? 0) + 1 }), {});
      setSummary(<div className="font-medium">Inbox: {r.fetched} new message(s){r.fetched > 0 && ": " + Object.entries(counts).map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`).join(", ")}</div>);
      setRefresh((x) => x + 1);
    } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  };

  return (
    <div>
      <PageHeader title="Collections" subtitle="Reminders go out once per customer per interval; replies are answered automatically only when routine and validated"
        actions={<>
          <label className="flex items-center gap-1 text-xs text-slate-600" title="Send now even if this customer was reminded within REMINDER_INTERVAL_DAYS (audit-logged)">
            <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> Ignore reminder interval
          </label>
          <Button variant="primary" busy={busy === "rem"} onClick={sendReminders}>Send reminders</Button>
          <Button busy={busy === "inbox"} onClick={checkInbox}>Check inbox now</Button>
        </>} />
      <ErrorBanner error={error} onClose={() => setError(null)} />
      {summary && <Notice>{summary}</Notice>}
      <div className="mb-4 flex gap-1 border-b border-slate-200">
        {(["attention", "conversations"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === t ? "border-slate-900 font-medium text-slate-900" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
            {t === "attention" ? "Needs attention" : "Conversations"}
          </button>
        ))}
      </div>
      {tab === "attention" ? <AttentionQueue refresh={refresh} /> : <Conversations refresh={refresh} />}
    </div>
  );
}

function AttentionQueue({ refresh }: { refresh: number }) {
  const { data, error, loading, reload } = useAsync(() => api.get<AttentionItem[]>("/collections/needs-attention"), [refresh]);
  if (loading && !data) return <Spinner />;
  return (
    <div className="space-y-4">
      <ErrorBanner error={error} />
      {data?.length === 0 && <Card><EmptyState>Nothing needs attention.</EmptyState></Card>}
      {data?.map((item) => <AttentionCard key={item.conversation_id} item={item} onDone={reload} />)}
    </div>
  );
}

function AttentionCard({ item, onDone }: { item: AttentionItem; onDone: () => void }) {
  const m = item.message;
  const [draft, setDraft] = useState(m?.draft ?? "");
  const [busy, setBusy] = useState<"send" | "resolve" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const act = async (kind: "send" | "resolve") => {
    setBusy(kind); setError(null);
    try {
      if (kind === "send") await api.post(`/conversations/${item.conversation_id}/reply`, { body: draft });
      else await api.post(`/conversations/${item.conversation_id}/resolve`, { note: "Dismissed without reply" });
      onDone();
    } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  };
  return (
    <Card className="p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="font-medium text-slate-900">{item.customer_name ?? "Unknown sender"}</span>
        {m?.from_addr && <span className="font-mono text-xs text-slate-500">{m.from_addr}</span>}
        {m?.category && <Badge tone="violet">{titleCase(m.category)}</Badge>}
        {typeof m?.confidence === "number" && m.confidence > 0 && <Badge>confidence {m.confidence.toFixed(2)}</Badge>}
        <span className="ml-auto text-xs text-slate-500">{fmtDateTime(item.updated_at)}</span>
      </div>
      <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900"><span className="font-medium">Why flagged:</span> {item.reason}</div>
      <ErrorBanner error={error} />
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">Customer message · {m?.subject}</div>
          <div className="max-h-72 overflow-y-auto rounded-md border border-slate-200 bg-slate-50 p-3"><PlainText text={m?.clean_text || m?.body_text} /></div>
        </div>
        <div>
          <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">Draft reply (edit before sending)</div>
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={12} maxLength={10000} className="w-full rounded-md border border-slate-300 p-2 font-mono text-xs" />
          <div className="mt-2 flex justify-end gap-2">
            <Button busy={busy === "resolve"} onClick={() => act("resolve")}>Dismiss / resolve</Button>
            <Button variant="primary" busy={busy === "send"} disabled={!draft.trim()} onClick={() => act("send")}>Send reply</Button>
          </div>
        </div>
      </div>
    </Card>
  );
}

function Conversations({ refresh }: { refresh: number }) {
  const [status, setStatus] = useState("");
  const { data, error, loading } = useAsync(() => api.get<ConversationSummary[]>(`/conversations${status ? `?status=${status}` : ""}`), [refresh, status]);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => { if (!selected && data?.length) setSelected(data[0].id); }, [data, selected]);
  return (
    <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
      <Card className="overflow-hidden">
        <div className="border-b border-slate-200 p-2">
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm">
            <option value="">All statuses</option><option value="open">Open</option><option value="needs_attention">Needs attention</option><option value="resolved">Resolved</option>
          </select>
        </div>
        <ErrorBanner error={error} />
        {loading && !data && <div className="p-4"><Spinner /></div>}
        {data?.length === 0 && <EmptyState>No conversations yet. Send reminders or check the inbox.</EmptyState>}
        <ul className="max-h-[70vh] divide-y divide-slate-100 overflow-y-auto">
          {data?.map((c) => (
            <li key={c.id}>
              <button onClick={() => setSelected(c.id)} className={`w-full px-3 py-2 text-left text-sm hover:bg-slate-50 ${selected === c.id ? "bg-slate-100" : ""}`}>
                <div className="flex items-center justify-between gap-2"><span className="truncate font-medium">{c.customer_name ?? "Unknown sender"}</span><Badge tone={statusTone(c.status)}>{titleCase(c.status)}</Badge></div>
                <div className="truncate text-xs text-slate-500">{c.subject}</div>
                <div className="text-xs text-slate-400">{c.message_count} messages · {fmtDateTime(c.updated_at)}</div>
              </button>
            </li>
          ))}
        </ul>
      </Card>
      {selected ? <Thread id={selected} refresh={refresh} /> : <Card><EmptyState>Select a conversation</EmptyState></Card>}
    </div>
  );
}

const KIND_LABEL: Record<string, string> = { reminder: "Reminder", reply: "Auto reply", human_reply: "Human reply", inbound: "Customer", auto_reply: "Auto-reply / bounce" };

function Thread({ id, refresh }: { id: string; refresh: number }) {
  const { data: c, error } = useAsync(() => api.get<ConversationDetail>(`/conversations/${id}`), [id, refresh]);
  if (error) return <ErrorBanner error={error} />;
  if (!c) return <Spinner />;
  return (
    <Card className="p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="font-semibold">{c.customer_name ?? "Unknown sender"}</h2>
        {c.customer_email && <span className="font-mono text-xs text-slate-500">{c.customer_email}</span>}
        <Badge tone={statusTone(c.status)}>{titleCase(c.status)}</Badge>
        {c.reminder_count > 0 && <Badge>{c.reminder_count} reminder(s)</Badge>}
      </div>
      {c.attention_reason && <Notice tone="amber">{c.attention_reason}</Notice>}
      {c.notes?.length > 0 && (
        <div className="mb-3 rounded-md border border-violet-200 bg-violet-50 p-2 text-sm text-violet-900">
          {c.notes.map((n, i) => <div key={i}><span className="font-medium">{titleCase(n.kind)}:</span> {n.text}</div>)}
        </div>
      )}
      <div className="space-y-3">
        {c.messages.map((m) => (
          <div key={m.id} className={`rounded-md border p-3 ${m.direction === "in" ? "border-slate-200 bg-white" : "border-sky-100 bg-sky-50/60"}`}>
            <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <Badge tone={m.direction === "in" ? "slate" : "blue"}>{m.direction === "in" ? "Inbound" : "Outbound"}</Badge>
              <span className="font-medium text-slate-700">{KIND_LABEL[m.kind] ?? m.kind}</span>
              {m.category && <Badge tone="violet">{titleCase(m.category)}</Badge>}
              {m.direction === "out" && <Badge tone={m.auto_sent ? "green" : "amber"}>{m.auto_sent ? "auto-sent" : `sent by ${m.sent_by ?? "human"}`}</Badge>}
              {m.needs_attention && <Badge tone="amber">needs attention</Badge>}
              <span>{m.direction === "in" ? `from ${m.from_addr}` : `to ${m.to_addr}`}</span>
              <span className="ml-auto">{fmtDateTime(m.created_at)}</span>
            </div>
            <div className="mb-1 text-sm font-medium text-slate-800">{m.subject}</div>
            {m.reason && m.direction === "in" && <div className="mb-1 text-xs text-slate-500">Agent: {m.reason}</div>}
            <PlainText text={m.body_text} className="max-h-80 overflow-y-auto" />
          </div>
        ))}
      </div>
    </Card>
  );
}
