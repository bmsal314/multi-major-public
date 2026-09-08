import type { AnalysisResponse, PlanState, PlanSummary } from "./api";
import type { Preferences, JobSummary } from "./api";
export type { Preferences } from "./api";
export const defaults: Preferences = {
  premed: false,
  start_term: "",
  graduation_term: "",
  credits_per_term: 15,
  min_credits: 0,
  include_summer: false,
  term_credit_limits: {},
  term_course_limits: {},
  mcat_terms: [],
  mcat_credit_ceiling: 12,
  mcat_course_ceiling: 4,
  course_ceiling: 0,
  personal_rules: {
    finance_sequence: false,
    finance_equivalence: false,
    dance: false,
  },
  recurring_commitment: {
    enabled: false,
    label: "Dance class",
    code: "DCE",
    credits: 2,
    include_summer: false,
  },
};
export interface User {
  id: string;
  email: string;
}
export interface Session {
  csrf: string;
  user: User | null;
  email_ready: boolean;
}
export interface SavedPlan {
  id: string;
  audit_id: string;
  name: string;
  revision: number;
  updated_at: string;
  preferences: Preferences;
  state: PlanState;
  result: AnalysisResponse;
  summary: PlanSummary;
}
export type Job = JobSummary;
let csrfToken = "";
export class RequestError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function readSession(): Promise<Session> {
  const s = await request<Session>("/api/auth/session");
  csrfToken = s.csrf;
  return s;
}
export async function request<T = Record<string, unknown>>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  if (method !== "GET" && !csrfToken) await readSession();
  const r = await fetch(path, {
    method,
    headers:
      method === "GET"
        ? {}
        : { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r
    .json()
    .catch(() => ({
      detail: "The service did not respond. Please try again.",
    }));
  if (!r.ok) {
    if (r.status === 401 && typeof window !== "undefined")
      window.dispatchEvent(new Event("session-ended"));
    throw new RequestError(
      r.status,
      typeof data.detail === "string"
        ? data.detail
        : "Check your input and try again.",
    );
  }
  return data as T;
}
export const api = <T = Record<string, unknown>>(
  path: string,
  method = "GET",
  body?: unknown,
) => request<T>("/api/v1/" + path, method, body);
export const auth = <T = Record<string, unknown>>(
  action: string,
  body?: unknown,
) => request<T>("/api/auth/" + action, "POST", body);
export async function upload(
  files: File[],
  preferences: Preferences,
  onProgress: (n: number) => void,
) {
  if (files.length < 1 || files.length > 8)
    throw new Error("Choose between one and eight PDF reports.");
  if (
    files.some((f) => f.size > 25 * 1024 * 1024) ||
    files.reduce((s, f) => s + f.size, 0) > 100 * 1024 * 1024
  )
    throw new Error(
      "Each PDF must be at most 25 MB, and the batch at most 100 MB.",
    );
  const ticket = await api<{
    job_id: string;
    uploads: { url: string; path: string }[];
  }>("uploads", "POST", {
    files: files.map((f) => ({ size: f.size })),
    preferences,
    consent: true,
  });
  // Only a failed *upload* may cancel the job. Starting the analysis is a
  // separate step, and cancelling on its failure was destroying healthy work:
  // the service parses inline for up to 40 s, so a slow-but-successful run that
  // tripped the proxy's timeout had its job cancelled out from under the worker
  // still processing it, and no map ever appeared.
  try {
    for (let i = 0; i < files.length; i++) {
      const r = await fetch(ticket.uploads[i].url, {
        method: "PUT",
        headers: { "Content-Type": "application/pdf", "x-upsert": "false" },
        body: files[i],
      });
      if (!r.ok)
        throw new Error(
          "Upload interrupted. Your previous saved plans are unchanged. Please try again.",
        );
      onProgress(Math.round(((i + 1) / files.length) * 100));
    }
  } catch (e) {
    await api(`analyses/${ticket.job_id}`, "DELETE").catch(() => undefined);
    throw e;
  }
  try {
    await api("analyses", "POST", { job_id: ticket.job_id });
  } catch {
    // The reports are uploaded and the job is queued. A timeout here says
    // nothing about whether the analysis is running, and the maintenance sweep
    // will pick it up regardless, so leave it alone and let the poller report.
  }
  return ticket.job_id;
}
