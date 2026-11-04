// Thin fetch wrapper. The token lives in sessionStorage (cleared when the tab closes) and is sent as a
// bearer header; the frontend never talks to the DB, mail server or LLM directly.
const TOKEN_KEY = "acme.token";

export class ApiError extends Error {
  status: number;
  details?: unknown;
  constructor(status: number, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

export const auth = {
  get token() {
    return sessionStorage.getItem(TOKEN_KEY);
  },
  set(token: string) {
    sessionStorage.setItem(TOKEN_KEY, token);
  },
  clear() {
    sessionStorage.removeItem(TOKEN_KEY);
  },
};

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

async function request<T>(method: string, path: string, body?: unknown, isForm = false): Promise<T> {
  const headers: Record<string, string> = {};
  if (auth.token) headers["Authorization"] = `Bearer ${auth.token}`;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
  });
  if (res.status === 401 && path !== "/auth/login") {
    auth.clear();
    onUnauthorized();
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const err = (data as { error?: { message?: string; details?: unknown } })?.error;
    let message = err?.message ?? `Request failed (${res.status})`;
    if (Array.isArray(err?.details)) {
      message += ": " + (err!.details as { loc: string[]; msg: string }[]).map((d) => `${d.loc.slice(1).join(".")} ${d.msg}`).join("; ");
    }
    throw new ApiError(res.status, message, err?.details);
  }
  return data as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, b?: unknown) => request<T>("POST", p, b ?? {}),
  patch: <T>(p: string, b: unknown) => request<T>("PATCH", p, b),
  upload: <T>(p: string, form: FormData) => request<T>("POST", p, form, true),
};

export async function downloadFile(path: string, filename: string) {
  const res = await fetch(`/api${path}`, { headers: { Authorization: `Bearer ${auth.token ?? ""}` } });
  if (!res.ok) throw new ApiError(res.status, "Download failed");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
