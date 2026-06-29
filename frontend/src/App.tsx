import { useCallback, useEffect, useState } from "react";
import { api, getApiKey, setApiKey } from "./api";
import type {
  ConnectorStatus,
  CustomerInbox,
  MergeSuggestion,
  RequestDetail,
  Stats,
} from "./types";
import {
  Badge,
  PriorityBadge,
  StatusBadge,
  channelIcon,
  timeAgo,
} from "./ui";

export default function App() {
  const [key, setKey] = useState(getApiKey());
  const [connected, setConnected] = useState<boolean | null>(null);
  const [provider, setProvider] = useState<{ llm: string; connector: string } | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [customers, setCustomers] = useState<CustomerInbox[]>([]);
  const [suggestions, setSuggestions] = useState<MergeSuggestion[]>([]);
  const [connector, setConnector] = useState<ConnectorStatus | null>(null);
  const [selectedCustomer, setSelectedCustomer] = useState<number | null>(null);
  const [openRequest, setOpenRequest] = useState<RequestDetail | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const [s, inbox, sug, conn] = await Promise.all([
        api.stats(),
        api.inbox(),
        api.suggestions(),
        api.connectorStatus(),
      ]);
      setStats(s);
      setCustomers(inbox);
      setSuggestions(sug);
      setConnector(conn);
      setConnected(true);
    } catch (e) {
      setConnected(false);
      setError((e as Error).message);
    }
  }, []);

  async function connectGmail() {
    try {
      const { authorization_url } = await api.gmailAuthorize();
      window.location.href = authorization_url;
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function disconnectGmail() {
    try {
      setConnector(await api.gmailDisconnect());
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    api
      .health()
      .then((h) => setProvider({ llm: h.llm_provider, connector: h.connector }))
      .catch(() => {});
    if (getApiKey()) refresh();
  }, [refresh]);

  async function saveKey() {
    setApiKey(key);
    await refresh();
  }

  async function doSync() {
    setSyncing(true);
    try {
      await api.sync();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSyncing(false);
    }
  }

  async function showRequest(id: number) {
    setOpenRequest(await api.requestDetail(id));
  }

  const selected = customers.find((c) => c.id === selectedCustomer) || null;

  return (
    <div className="min-h-screen flex flex-col">
      <TopBar
        keyValue={key}
        onKeyChange={setKey}
        onSaveKey={saveKey}
        onSync={doSync}
        syncing={syncing}
        connected={connected}
        provider={provider}
        stats={stats}
        connector={connector}
        onConnectGmail={connectGmail}
        onDisconnectGmail={disconnectGmail}
      />

      {error && (
        <div className="bg-rose-50 text-rose-700 px-6 py-2 text-sm border-b border-rose-200">{error}</div>
      )}

      {suggestions.length > 0 && (
        <SuggestionsBar
          suggestions={suggestions}
          onAccept={async (id) => {
            await api.acceptSuggestion(id);
            await refresh();
          }}
          onReject={async (id) => {
            await api.rejectSuggestion(id);
            await refresh();
          }}
        />
      )}

      <div className="flex flex-1 overflow-hidden">
        <aside className="w-[380px] border-r border-slate-200 bg-white overflow-y-auto">
          <div className="px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-400 sticky top-0 bg-white border-b border-slate-100">
            Customers · accountability first
          </div>
          {customers.length === 0 && (
            <EmptyState connected={connected} onSync={doSync} />
          )}
          {customers.map((c) => (
            <CustomerRow
              key={c.id}
              c={c}
              active={c.id === selectedCustomer}
              onClick={() => {
                setSelectedCustomer(c.id);
                setOpenRequest(null);
              }}
            />
          ))}
        </aside>

        <main className="flex-1 overflow-y-auto bg-slate-50">
          {!selected && <Welcome />}
          {selected && !openRequest && (
            <CustomerPanel customer={selected} onOpenRequest={showRequest} />
          )}
          {openRequest && (
            <RequestPanel
              detail={openRequest}
              onBack={() => setOpenRequest(null)}
              onChanged={async () => {
                await showRequest(openRequest.id);
                await refresh();
              }}
            />
          )}
        </main>
      </div>
    </div>
  );
}

function TopBar(props: {
  keyValue: string;
  onKeyChange: (v: string) => void;
  onSaveKey: () => void;
  onSync: () => void;
  syncing: boolean;
  connected: boolean | null;
  provider: { llm: string; connector: string } | null;
  stats: Stats | null;
  connector: ConnectorStatus | null;
  onConnectGmail: () => void;
  onDisconnectGmail: () => void;
}) {
  return (
    <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center gap-6 flex-wrap">
      <div className="flex items-center gap-2">
        <span className="text-xl">📬</span>
        <h1 className="text-lg font-semibold">better-email</h1>
        {props.provider && (
          <span className="text-xs text-slate-400">
            {props.provider.connector} · {props.provider.llm}
          </span>
        )}
      </div>

      {props.stats && (
        <div className="flex items-center gap-4 text-sm">
          <Stat label="Customers" value={props.stats.customers} />
          <Stat label="Open" value={props.stats.open_requests} />
          <Stat label="Needs reply" value={props.stats.needs_response} tone="rose" />
          <Stat label="Forgotten" value={props.stats.forgotten} tone="red" />
        </div>
      )}

      <div className="ml-auto flex items-center gap-2">
        <GmailControl
          connector={props.connector}
          onConnect={props.onConnectGmail}
          onDisconnect={props.onDisconnectGmail}
        />
        <input
          type="password"
          placeholder="API key"
          value={props.keyValue}
          onChange={(e) => props.onKeyChange(e.target.value)}
          className="border border-slate-300 rounded px-2 py-1 text-sm w-40"
        />
        <button
          onClick={props.onSaveKey}
          className="text-sm px-3 py-1 rounded bg-slate-100 hover:bg-slate-200"
        >
          Connect
        </button>
        <button
          onClick={props.onSync}
          disabled={props.syncing}
          className="text-sm px-3 py-1 rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {props.syncing ? "Syncing…" : "Sync now"}
        </button>
        <span
          className={`h-2 w-2 rounded-full ${
            props.connected === null ? "bg-slate-300" : props.connected ? "bg-emerald-500" : "bg-rose-500"
          }`}
          title={props.connected ? "Connected" : "Not connected"}
        />
      </div>
    </header>
  );
}

function GmailControl({
  connector,
  onConnect,
  onDisconnect,
}: {
  connector: ConnectorStatus | null;
  onConnect: () => void;
  onDisconnect: () => void;
}) {
  if (!connector) return null;
  if (connector.gmail_connected) {
    return (
      <div className="flex items-center gap-1.5">
        <span
          className="text-xs px-2 py-1 rounded bg-emerald-50 text-emerald-700 border border-emerald-200"
          title={connector.gmail_address || "Gmail connected"}
        >
          ✉ {connector.gmail_address || "Gmail"}
        </span>
        <button
          onClick={onDisconnect}
          className="text-xs px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-600"
        >
          Disconnect
        </button>
      </div>
    );
  }
  return (
    <button
      onClick={onConnect}
      disabled={!connector.gmail_configured}
      title={connector.gmail_configured ? "Authorize Gmail access" : "Set GMAIL_CLIENT_ID/SECRET to enable"}
      className="text-sm px-3 py-1 rounded bg-red-500 text-white hover:bg-red-600 disabled:opacity-40 disabled:cursor-not-allowed"
    >
      Connect Gmail
    </button>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  const color = tone === "red" ? "text-red-600" : tone === "rose" ? "text-rose-600" : "text-slate-800";
  return (
    <div className="flex flex-col items-center leading-tight">
      <span className={`font-semibold ${value > 0 ? color : "text-slate-400"}`}>{value}</span>
      <span className="text-[10px] uppercase text-slate-400">{label}</span>
    </div>
  );
}

function SuggestionsBar(props: {
  suggestions: MergeSuggestion[];
  onAccept: (id: number) => void;
  onReject: (id: number) => void;
}) {
  return (
    <div className="bg-violet-50 border-b border-violet-200 px-6 py-2 text-sm">
      {props.suggestions.map((s) => (
        <div key={s.id} className="flex items-center gap-3 py-1">
          <span className="text-violet-700">
            Possible same customer: <b>{s.customer_a.name}</b> ↔ <b>{s.customer_b.name}</b>{" "}
            <span className="text-violet-400">({Math.round(s.confidence * 100)}% · {s.reason})</span>
          </span>
          <button onClick={() => props.onAccept(s.id)} className="px-2 py-0.5 rounded bg-violet-600 text-white text-xs">
            Merge
          </button>
          <button onClick={() => props.onReject(s.id)} className="px-2 py-0.5 rounded bg-white border text-xs">
            Keep separate
          </button>
        </div>
      ))}
    </div>
  );
}

function CustomerRow({ c, active, onClick }: { c: CustomerInbox; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-4 py-3 border-b border-slate-100 hover:bg-slate-50 ${
        active ? "bg-indigo-50" : ""
      }`}
    >
      <div className="flex items-center justify-between">
        <span className="font-medium text-slate-800">{c.display_name}</span>
        <span className="text-xs text-slate-400">{timeAgo(c.last_activity_at)}</span>
      </div>
      <div className="flex items-center gap-1.5 mt-1 flex-wrap">
        {c.forgotten_requests > 0 && <Badge color="bg-red-600 text-white">⚠ forgotten</Badge>}
        {c.needs_response && c.forgotten_requests === 0 && (
          <Badge color="bg-rose-100 text-rose-700">needs reply</Badge>
        )}
        <PriorityBadge priority={c.highest_priority} />
        <Badge color="bg-slate-100 text-slate-500">
          {c.open_requests} open
        </Badge>
        {c.identities.length > 1 && (
          <Badge color="bg-sky-100 text-sky-700">{c.identities.length} channels</Badge>
        )}
      </div>
    </button>
  );
}

function CustomerPanel({
  customer,
  onOpenRequest,
}: {
  customer: CustomerInbox;
  onOpenRequest: (id: number) => void;
}) {
  return (
    <div className="p-6 max-w-3xl">
      <h2 className="text-xl font-semibold">{customer.display_name}</h2>
      {customer.company && <p className="text-slate-500">{customer.company}</p>}
      <div className="flex flex-wrap gap-1.5 mt-3">
        {customer.identities.map((i, idx) => (
          <Badge key={idx} color="bg-slate-100 text-slate-600">
            {i.kind}: {i.value}
          </Badge>
        ))}
      </div>

      <h3 className="text-sm font-semibold uppercase text-slate-400 mt-6 mb-2">
        Requests ({customer.requests.length})
      </h3>
      <div className="space-y-2">
        {customer.requests.map((r) => (
          <button
            key={r.id}
            onClick={() => onOpenRequest(r.id)}
            className="block w-full text-left bg-white rounded-lg border border-slate-200 p-4 hover:border-indigo-300"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">
                {channelIcon(r.channel)} {r.title}
              </span>
              <div className="flex gap-1.5 items-center">
                {r.forgotten && <Badge color="bg-red-600 text-white">⚠ forgotten</Badge>}
                <PriorityBadge priority={r.priority} />
                <StatusBadge status={r.status} />
              </div>
            </div>
            {r.summary && <p className="text-sm text-slate-500 mt-1">{r.summary}</p>}
            <div className="text-xs text-slate-400 mt-2">
              {r.message_count} messages · last in {timeAgo(r.last_inbound_at)}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function RequestPanel({
  detail,
  onBack,
  onChanged,
}: {
  detail: RequestDetail;
  onBack: () => void;
  onChanged: () => void;
}) {
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);

  async function genDraft() {
    setBusy(true);
    try {
      const d = await api.draft(detail.id);
      setReply(d.draft);
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    setBusy(true);
    try {
      await api.reply(detail.id, reply);
      setReply("");
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="p-6 max-w-3xl">
      <button onClick={onBack} className="text-sm text-indigo-600 mb-3">
        ← Back to {detail.customer_name}
      </button>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-xl font-semibold">{detail.title}</h2>
        <div className="flex gap-1.5 items-center">
          {detail.forgotten && <Badge color="bg-red-600 text-white">⚠ forgotten</Badge>}
          <PriorityBadge priority={detail.priority} />
          <StatusBadge status={detail.status} />
        </div>
      </div>

      {detail.summary && (
        <div className="mt-3 bg-indigo-50 border border-indigo-100 rounded-lg p-3 text-sm">
          <div className="font-semibold text-indigo-700 text-xs uppercase mb-1">AI summary</div>
          <p className="text-slate-700">{detail.summary}</p>
          {detail.ask && (
            <p className="text-slate-600 mt-1">
              <b>The ask:</b> {detail.ask}
            </p>
          )}
        </div>
      )}

      <div className="mt-5 space-y-3">
        {detail.messages.map((m) => (
          <div
            key={m.id}
            className={`rounded-lg p-3 border ${
              m.direction === "outbound"
                ? "bg-emerald-50 border-emerald-100 ml-8"
                : "bg-white border-slate-200 mr-8"
            }`}
          >
            <div className="flex justify-between text-xs text-slate-400 mb-1">
              <span>
                {m.direction === "outbound" ? "You" : m.from_name || m.from_email} · {channelIcon(m.platform)} {m.platform}
              </span>
              <span>{timeAgo(m.received_at)}</span>
            </div>
            <div className="text-sm whitespace-pre-wrap text-slate-700">{m.body}</div>
          </div>
        ))}
      </div>

      <div className="mt-5 bg-white border border-slate-200 rounded-lg p-3">
        <textarea
          value={reply}
          onChange={(e) => setReply(e.target.value)}
          placeholder="Write a reply… (or generate an AI draft)"
          className="w-full h-28 border border-slate-200 rounded p-2 text-sm"
        />
        <div className="flex gap-2 mt-2">
          <button onClick={genDraft} disabled={busy} className="text-sm px-3 py-1 rounded bg-slate-100 hover:bg-slate-200 disabled:opacity-50">
            ✨ AI draft
          </button>
          <button
            onClick={send}
            disabled={busy || !reply.trim()}
            className="text-sm px-3 py-1 rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            Send reply
          </button>
          {detail.status !== "resolved" ? (
            <button
              onClick={async () => {
                await api.resolve(detail.id);
                await onChanged();
              }}
              className="text-sm px-3 py-1 rounded bg-emerald-100 text-emerald-700 ml-auto"
            >
              Mark resolved
            </button>
          ) : (
            <button
              onClick={async () => {
                await api.reopen(detail.id);
                await onChanged();
              }}
              className="text-sm px-3 py-1 rounded bg-slate-100 ml-auto"
            >
              Reopen
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function Welcome() {
  return (
    <div className="h-full flex items-center justify-center text-slate-400">
      <div className="text-center">
        <div className="text-5xl mb-3">📭</div>
        <p>Select a customer to see their grouped requests.</p>
      </div>
    </div>
  );
}

function EmptyState({ connected, onSync }: { connected: boolean | null; onSync: () => void }) {
  return (
    <div className="p-6 text-sm text-slate-500">
      {connected === false ? (
        <p>Enter your API key above and click Connect.</p>
      ) : (
        <>
          <p className="mb-2">No customers yet.</p>
          <button onClick={onSync} className="px-3 py-1 rounded bg-indigo-600 text-white text-sm">
            Sync the inbox
          </button>
        </>
      )}
    </div>
  );
}
