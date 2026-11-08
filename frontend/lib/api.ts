import type { ApiErrorBody } from "./types";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

let csrfToken = "";
let onUnauthorized: (() => void) | null = null;

// Pages render before the visitor's identity is known. Requests (other than /api/auth/*)
// wait here until the app shell has called /api/auth/me and stored the session.
let markReady: () => void = () => {};
const identityReady = new Promise<void>((resolve) => {
  markReady = resolve;
});

const PUBLIC_PATHS = ["/api/auth/", "/api/site", "/api/health"];

export function setIdentityReady() {
  markReady();
}

export function setCsrfToken(token: string) {
  csrfToken = token;
}

export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}

type Options = { method?: string; body?: unknown; form?: FormData; signal?: AbortSignal };

export async function api<T>(path: string, opts: Options = {}): Promise<T> {
  if (!PUBLIC_PATHS.some((p) => path.startsWith(p))) await identityReady;
  const method = opts.method ?? (opts.body !== undefined || opts.form ? "POST" : "GET");
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(path, { method, headers, body, credentials: "same-origin", signal: opts.signal, cache: "no-store" });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network", "Can't reach the server. Check your connection.");
  }
  if (res.status === 401 && onUnauthorized && !path.startsWith("/api/auth/login")) onUnauthorized();
  const type = res.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await res.json().catch(() => null) : null;
  if (!res.ok) {
    const detail = (data?.detail ?? null) as ApiErrorBody | string | null;
    if (detail && typeof detail === "object") throw new ApiError(res.status, detail.code, detail.message);
    const fallback =
      res.status === 413 ? "The upload is too large." :
      res.status === 502 || res.status === 504 ? "The server isn't responding. Try again shortly." :
      `Request failed (HTTP ${res.status}).`;
    throw new ApiError(res.status, "http_" + res.status, typeof detail === "string" ? detail : fallback);
  }
  return data as T;
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "Something went wrong.";
}

export const fileUrl = (id: string, download = false) => `/api/media/${id}/file${download ? "?download=1" : ""}`;
