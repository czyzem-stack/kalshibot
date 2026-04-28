/** Labs B/C/D/E Breeding Council: poll ``GET /labs/chat`` for Optimizer Think Tank + Settings history. */
import { useCallback, useEffect, useRef, useState } from "react";
import { LAB_CHAT_POLL_MS, subscribeDashboardCatchUp } from "./dashboardPolling";

export const LAB_COLLABORATION_STORAGE_KEY = "kalshibot_lab_collaboration_enabled_v1";
/** @deprecated use LAB_COLLABORATION_STORAGE_KEY */
export const LAB_CHAT_STORAGE_KEY = LAB_COLLABORATION_STORAGE_KEY;

export function readLabCollaborationEnabled(): boolean {
  try {
    let v = localStorage.getItem(LAB_COLLABORATION_STORAGE_KEY);
    if (v === null) v = localStorage.getItem("kalshibot_lab_chat_enabled_v1");
    if (v === null) return true;
    return v !== "0" && v !== "false";
  } catch {
    return true;
  }
}

/** @deprecated use readLabCollaborationEnabled */
export const readLabChatEnabled = readLabCollaborationEnabled;

export type LabHiveRow = {
  id?: string;
  ts_iso?: string;
  lab?: string;
  label?: string;
  message?: string;
  confidence?: number;
  action?: string;
  kind?: string;
  /** When set, this line is explicitly threaded to another message id (Think Tank replies). */
  reply_to?: string;
};

const TICKER_LABS = ["lab_b", "lab_c", "lab_d", "lab_e"] as const;

/**
 * Interleave recent lines per lab (newest-first round-robin). API order is chronological; the deque tail
 * can be mostly one lab when that branch ticks last—this keeps B/C/D/E visible together on the ticker.
 */
export function balanceHiveMessagesForTicker(rows: LabHiveRow[], limit = 28): LabHiveRow[] {
  type LabId = (typeof TICKER_LABS)[number];
  const byLab: Record<LabId, LabHiveRow[]> = { lab_b: [], lab_c: [], lab_d: [], lab_e: [] };
  for (const r of rows) {
    const lab = String(r.lab || "") as LabId;
    if (lab in byLab) byLab[lab].push(r);
  }
  const idx: Record<LabId, number> = {
    lab_b: byLab.lab_b.length - 1,
    lab_c: byLab.lab_c.length - 1,
    lab_d: byLab.lab_d.length - 1,
    lab_e: byLab.lab_e.length - 1,
  };
  const out: LabHiveRow[] = [];
  while (out.length < limit) {
    let progressed = false;
    for (const lab of TICKER_LABS) {
      const i = idx[lab];
      if (i >= 0) {
        const row = byLab[lab][i];
        if (row) out.push(row);
        idx[lab] = i - 1;
        progressed = true;
        if (out.length >= limit) break;
      }
    }
    if (!progressed) break;
  }
  return out;
}

export function useLabHiveChat(dashReady: boolean): {
  messages: LabHiveRow[];
  labChatEnabled: boolean;
  setLabChatEnabled: (v: boolean | ((p: boolean) => boolean)) => void;
} {
  const [messages, setMessages] = useState<LabHiveRow[]>([]);
  const [labChatEnabled, setLabChatEnabledState] = useState<boolean>(() => readLabCollaborationEnabled());
  const bootstrappedRef = useRef(false);

  const setLabChatEnabled = useCallback((v: boolean | ((p: boolean) => boolean)) => {
    setLabChatEnabledState((prev) => {
      const next = typeof v === "function" ? (v as (p: boolean) => boolean)(prev) : v;
      try {
        localStorage.setItem(LAB_COLLABORATION_STORAGE_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  useEffect(() => {
    if (!dashReady) return;
    let cancelled = false;

    const poll = async () => {
      try {
        const r = await fetch("/labs/chat", { cache: "no-store" });
        if (!r.ok || cancelled) return;
        const j = (await r.json()) as { messages?: LabHiveRow[] };
        const rows = Array.isArray(j.messages) ? j.messages : [];
        setMessages(rows);
        bootstrappedRef.current = true;
      } catch {
        /* offline */
      }
    };

    void poll();
    const id = window.setInterval(() => void poll(), LAB_CHAT_POLL_MS);
    const unsub = subscribeDashboardCatchUp(() => void poll());
    return () => {
      cancelled = true;
      window.clearInterval(id);
      unsub();
    };
  }, [dashReady]);

  return { messages, labChatEnabled, setLabChatEnabled };
}

export function LabHiveChatSettingsPanel(props: {
  messages: LabHiveRow[];
  enabled: boolean;
  onToggleEnabled: (next: boolean) => void;
}) {
  const { messages, enabled, onToggleEnabled } = props;
  return (
    <div className="lab-hive-chat-settings">
      <div className="lab-hive-chat__head">
        <h3 style={{ margin: 0 }}>Breeding Council • Labs B + C + D + E working together</h3>
        <label className="lab-hive-chat__toggle">
          <input type="checkbox" checked={enabled} onChange={(e) => onToggleEnabled(e.target.checked)} />
          Enable Agent Collaboration
        </label>
      </div>
      <p className="sub" style={{ margin: "6px 0 10px" }}>
        Shows Labs B/C/D/E think tank in the Optimizer panel and this transcript. Trading logic is unchanged.
      </p>
      <div className="lab-hive-chat__body" role="log" aria-live="polite">
        {messages.length === 0 ? (
          <div className="sub lab-hive-chat__empty">Waiting for Labs B, C, D, and E to publish thoughts…</div>
        ) : (
          <ul className="lab-hive-chat__list">
            {[...messages].reverse().map((m) => (
              <li key={String(m.id || `${m.ts_iso}-${m.lab}-${m.message}`)} className={`lab-hive-chat__li lab-hive-chat__li--${String(m.lab || "").replace(/[^a-z0-9_]/gi, "_")}`}>
                <div className="lab-hive-chat__meta">
                  <strong>{String(m.label || m.lab || "?")}</strong>
                  {m.ts_iso ? (
                    <span className="lab-hive-chat__ts" title={String(m.ts_iso)}>
                      {String(m.ts_iso).slice(11, 19)}Z
                    </span>
                  ) : null}
                </div>
                <div className="lab-hive-chat__msg">{String(m.message || "")}</div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
