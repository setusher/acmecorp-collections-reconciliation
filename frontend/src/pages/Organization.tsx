import { api } from "../api/client";
import type { Organization as Org } from "../api/types";
import { Card, ErrorBanner, PageHeader, useAsync } from "../components/ui";
import { titleCase } from "../lib/format";

export default function Organization() {
  const { data: org, error } = useAsync(() => api.get<Org>("/organization"));
  return (
    <div>
      <PageHeader title="Organization" subtitle="Details customers see in reminders and replies" />
      <ErrorBanner error={error} />
      {org && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="p-5">
            <h2 className="mb-3 font-semibold text-slate-900">{org.name}</h2>
            <dl className="grid grid-cols-[9rem_1fr] gap-y-2 text-sm">
              <dt className="text-slate-500">Address</dt><dd>{org.address}</dd>
              <dt className="text-slate-500">Accounts contact</dt><dd>{org.accounts_contact_name}</dd>
              <dt className="text-slate-500">Accounts email</dt><dd className="font-mono text-xs">{org.accounts_email}</dd>
              <dt className="text-slate-500">Phone</dt><dd>{org.phone}</dd>
              <dt className="text-slate-500">Currencies</dt><dd>{org.accepted_currencies.join(", ")} (reports in {org.default_currency})</dd>
              <dt className="text-slate-500">Payment terms</dt><dd>{org.payment_terms}</dd>
              <dt className="text-slate-500">Methods</dt><dd>{org.payment_methods.join(", ")}</dd>
            </dl>
          </Card>
          <Card className="p-5">
            <h2 className="mb-3 font-semibold text-slate-900">Bank details</h2>
            <dl className="grid grid-cols-[9rem_1fr] gap-y-2 text-sm">
              <dt className="text-slate-500">Account name</dt><dd>{org.bank_details.account_name}</dd>
              <dt className="text-slate-500">Account number</dt><dd className="font-mono">{org.bank_details.account_number}</dd>
              <dt className="text-slate-500">Bank</dt><dd>{org.bank_details.bank}</dd>
              <dt className="text-slate-500">IFSC</dt><dd className="font-mono">{org.bank_details.ifsc}</dd>
              <dt className="text-slate-500">SWIFT</dt><dd className="font-mono">{org.bank_details.swift_code}</dd>
            </dl>
          </Card>
          <Card className="p-5 lg:col-span-2">
            <h2 className="mb-3 font-semibold text-slate-900">Policies</h2>
            <dl className="grid grid-cols-[9rem_1fr] gap-y-2 text-sm">
              {Object.entries(org.policies).map(([k, v]) => (
                <div key={k} className="contents"><dt className="text-slate-500">{titleCase(k)}</dt><dd>{v}</dd></div>
              ))}
            </dl>
          </Card>
        </div>
      )}
    </div>
  );
}
