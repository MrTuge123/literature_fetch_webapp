// Calls to the Literature Fetch API (api/http.py). Every call carries the Cognito ID token;
// API Gateway checks it, and the API reads the user id from it.
import { fetchAuthSession } from "aws-amplify/auth";
import { API_URL } from "./config";
import type { ApiSettings } from "./settings";

export class ApiError extends Error {
  status: number;
  code: string;
  fields: string[];
  constructor(status: number, code: string, message: string, fields: string[] = []) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

export async function idToken(forceRefresh = false): Promise<string | undefined> {
  const session = await fetchAuthSession({ forceRefresh });
  return session.tokens?.idToken?.toString();
}

export async function api<T>(method: "GET" | "PUT" | "POST" | "DELETE", path: string, body?: unknown): Promise<T> {
  const token = await idToken();
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(API_URL + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network", "Couldn't reach the API (offline, or blocked by CORS).");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const message =
      data.message ??
      (res.status === 503 || res.status === 504 ? "The API took too long; try again." : res.statusText);
    throw new ApiError(res.status, data.error ?? `http_${res.status}`, message, data.fields ?? []);
  }
  return data as T;
}

export function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

// ----- response shapes (mirror api/http.py) -----

export type Me = {
  id: string;
  email: string;
  admin: boolean;
  settings: ApiSettings | null;
  has_webhook: boolean;
  paused: boolean;
};

export type PreviewResult = {
  found: Record<string, number | string>;
  count: number;
  examples: { title: string; journal: string | null; link: string | null }[];
};

export type TestResult = { sent: string[]; failed: Record<string, string> };

export type DigestPaper = {
  title: string;
  link: string | null;
  journal: string | null;
  summary: string | null;
  relevance: number | null;
  rank: number | null;
};
export type Digest = { date: string; papers: DigestPaper[] };

export type Invite = {
  code: string;
  note: string | null;
  created_by: string | null;
  expires_at: string;
  used_by: string | null;
  used_at: string | null;
};
