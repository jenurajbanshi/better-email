import type { ReactNode } from "react";

export function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").getTime();
  const diff = Date.now() - then;
  const mins = Math.round(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

export function Badge({ children, color }: { children: ReactNode; color: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    needs_reply: "bg-rose-100 text-rose-700",
    waiting: "bg-amber-100 text-amber-700",
    resolved: "bg-emerald-100 text-emerald-700",
  };
  const label: Record<string, string> = {
    needs_reply: "Needs reply",
    waiting: "Waiting",
    resolved: "Resolved",
  };
  return <Badge color={map[status] || "bg-slate-100 text-slate-600"}>{label[status] || status}</Badge>;
}

export function PriorityBadge({ priority }: { priority: string }) {
  const map: Record<string, string> = {
    urgent: "bg-red-600 text-white",
    high: "bg-orange-100 text-orange-700",
    normal: "bg-slate-100 text-slate-600",
    low: "bg-slate-50 text-slate-400",
  };
  if (priority === "normal" || priority === "low") return null;
  return <Badge color={map[priority]}>{priority}</Badge>;
}

export function channelIcon(channel: string | null): string {
  switch (channel) {
    case "gmail":
      return "✉️";
    case "webform":
      return "📝";
    default:
      return "💬";
  }
}
