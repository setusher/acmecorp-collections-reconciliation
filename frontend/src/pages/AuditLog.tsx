import { api } from "../api/client";
import type { AuditEntry } from "../api/types";
import { Badge, Card, ErrorBanner, PageHeader, Spinner, useAsync } from "../components/ui";
import { fmtDateTime, titleCase } from "../lib/format";

export default function AuditLog() {
  const { data, error, loading } = useAsync(() => api.get<AuditEntry[]>("/audit-log?limit=300"));
  return (
    <div>
      <PageHeader title="Audit log" subtitle="Approvals, rejections, emails sent, customer edits and resets" />
      <ErrorBanner error={error} />
      {loading && !data && <Spinner />}
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-3 py-2">When</th><th className="px-3 py-2">Actor</th><th className="px-3 py-2">Action</th><th className="px-3 py-2">Entity</th><th className="px-3 py-2">Details</th></tr></thead>
          <tbody className="divide-y divide-slate-100 align-top">
            {data?.map((a) => (
              <tr key={a.id}>
                <td className="px-3 py-2 whitespace-nowrap text-xs">{fmtDateTime(a.at)}</td>
                <td className="px-3 py-2">{a.actor}</td>
                <td className="px-3 py-2"><Badge>{titleCase(a.action)}</Badge></td>
                <td className="px-3 py-2 font-mono text-xs">{a.entity}</td>
                <td className="px-3 py-2"><pre className="max-w-xl whitespace-pre-wrap break-words text-xs text-slate-600">{JSON.stringify(a.details, null, 1)}</pre></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
