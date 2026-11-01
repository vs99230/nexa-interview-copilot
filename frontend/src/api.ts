import type { StatusInfo } from "./types";

// The custom header forces a CORS preflight, so other websites cannot call these endpoints.
const GUARD = { "X-Nexa-Client": "1" };

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText || `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export const getStatus = async (): Promise<StatusInfo> => parse(await fetch("/api/status"));

export async function submitContext(input: {
  resumeFile: File | null;
  resumeText: string;
  jobDescription: string;
}): Promise<StatusInfo> {
  const form = new FormData();
  if (input.resumeFile) form.append("resume", input.resumeFile);
  form.append("resume_text", input.resumeText);
  form.append("job_description", input.jobDescription);
  return parse(await fetch("/api/context", { method: "POST", headers: GUARD, body: form }));
}

export const startListening = async (): Promise<StatusInfo> =>
  parse(await fetch("/api/start", { method: "POST", headers: GUARD }));

export const stopListening = async (): Promise<StatusInfo> =>
  parse(await fetch("/api/stop", { method: "POST", headers: GUARD }));

export function wsUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws`;
}
