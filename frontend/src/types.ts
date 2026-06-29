export interface Identity {
  kind: string;
  value: string;
  source: string;
}

export interface RequestSummary {
  id: number;
  title: string;
  summary: string | null;
  ask: string | null;
  status: "needs_reply" | "waiting" | "resolved";
  priority: "low" | "normal" | "high" | "urgent";
  sentiment: string | null;
  channel: string | null;
  needs_response: boolean;
  forgotten: boolean;
  message_count: number;
  last_inbound_at: string | null;
  last_outbound_at: string | null;
}

export interface Message {
  id: number;
  direction: "inbound" | "outbound";
  platform: string;
  from_name: string | null;
  from_email: string | null;
  subject: string | null;
  body: string;
  snippet: string | null;
  received_at: string;
}

export interface RequestDetail extends RequestSummary {
  customer_id: number;
  customer_name: string;
  messages: Message[];
}

export interface CustomerInbox {
  id: number;
  display_name: string;
  company: string | null;
  identities: Identity[];
  requests: RequestSummary[];
  open_requests: number;
  forgotten_requests: number;
  needs_response: boolean;
  highest_priority: "low" | "normal" | "high" | "urgent";
  last_activity_at: string | null;
}

export interface Stats {
  customers: number;
  open_requests: number;
  needs_response: number;
  forgotten: number;
  pending_suggestions: number;
}

export interface MergeSuggestion {
  id: number;
  customer_a: { id: number; name: string };
  customer_b: { id: number; name: string };
  reason: string;
  confidence: number;
  status: string;
}

export interface ConnectorStatus {
  active: string;
  gmail_configured: boolean;
  gmail_connected: boolean;
  gmail_address: string | null;
  last_sync_at: string | null;
}
