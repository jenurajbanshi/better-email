import type {
  ConnectorStatus,
  CustomerInbox,
  MergeSuggestion,
  RequestDetail,
  RequestSummary,
  Stats,
} from "./types";

const KEY_STORAGE = "better-email-api-key";

export function getApiKey(): string {
  return localStorage.getItem(KEY_STORAGE) || "";
}

export function setApiKey(key: string) {
  localStorage.setItem(KEY_STORAGE, key);
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": getApiKey(),
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; llm_provider: string; connector: string }>("/health"),
  sync: () => request<{ fetched: number; ingested: number; skipped: number }>("/sync", { method: "POST" }),
  inbox: () => request<CustomerInbox[]>("/inbox"),
  stats: () => request<Stats>("/stats"),
  requestDetail: (id: number) => request<RequestDetail>(`/requests/${id}`),
  draft: (id: number) => request<{ draft: string }>(`/requests/${id}/draft`, { method: "POST" }),
  reply: (id: number, body: string) =>
    request<RequestDetail>(`/requests/${id}/reply`, { method: "POST", body: JSON.stringify({ body }) }),
  resolve: (id: number) => request<RequestSummary>(`/requests/${id}/resolve`, { method: "POST" }),
  reopen: (id: number) => request<RequestSummary>(`/requests/${id}/reopen`, { method: "POST" }),
  suggestions: () => request<MergeSuggestion[]>("/suggestions"),
  acceptSuggestion: (id: number) => request(`/suggestions/${id}/accept`, { method: "POST" }),
  rejectSuggestion: (id: number) => request(`/suggestions/${id}/reject`, { method: "POST" }),
  connectorStatus: () => request<ConnectorStatus>("/connectors"),
  gmailAuthorize: () => request<{ authorization_url: string }>("/connectors/gmail/authorize"),
  gmailDisconnect: () => request<ConnectorStatus>("/connectors/gmail/disconnect", { method: "POST" }),
};
