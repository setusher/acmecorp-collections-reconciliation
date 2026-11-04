import { useState } from "react";
import { api, auth } from "../api/client";
import { Button, ErrorBanner } from "../components/ui";

export default function Login({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ token: string }>("/auth/login", { username, password });
      auth.set(r.token);
      onLogin();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex min-h-screen items-center justify-center">
      <form onSubmit={submit} className="w-80 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-lg font-semibold text-slate-900">AcmeCorp Accounts</h1>
        <p className="mb-4 text-sm text-slate-500">Sign in to continue</p>
        <ErrorBanner error={error} />
        <label className="block text-sm text-slate-700">Username
          <input className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
        </label>
        <label className="mt-3 block text-sm text-slate-700">Password
          <input type="password" className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" autoFocus />
        </label>
        <Button type="submit" variant="primary" busy={busy} className="mt-5 w-full">Sign in</Button>
      </form>
    </div>
  );
}
