/**
 * Labs B/C/D hive chat: poll ``GET /labs/chat``, optional bottom-right toasts, transcript panel.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import toast from "react-hot-toast";
import { LAB_CHAT_POLL_MS, subscribeDashboardCatchUp } from "./dashboardPolling";

export const LAB_CHAT_STORAGE_KEY = "kalshibot_lab_chat_enabled_v1";

export function readLabChatEnabled(): boolean {
  try {
    const v = localStorage.getItem(LAB_CHAT_STORAGE_KEY);
    if (v === null) return true;
    return v !== "0" && v !== "false";
  } catch {
    return true;
  }
}

export type LabHiveRow = {
  id?: string;
  ts_iso?: string;
  lab?: string;
  label?: string;
  message?: string;
  confidence?: number;
  action?: string;
  kind?: string;
};

function hiveToastPalette(lab: string): { bg: string; border: string; color: string } {
  if (lab === "lab_b") {
    return { bg: "rgba(234, 179, 8, 0.14)", border: "rgba(251, 191, 36, 0.55)", color: "#fde68a" };
  }
  if (lab === "lab_c") {
    return { bg: "rgba(236, 72, 153, 0.16)", border: "rgba(244, 114, 182, 0.55)", color: "#fbcfe8" };
  }
  return { bg: "rgba(168, 85, 247, 0.15)", border: "rgba(192, 132, 252, 0.52)", color: "#e9d5ff" };
}

export function pushLabHiveToast(row: LabHiveRow): void {
  const lab = String(row.lab || "");
  const msg = String(row.message || "").trim();
  if (!msg) return;
  const label = String(row.label || lab || "Lab");
  const conf =
    row.confidence != null && Number.isFinite(Number(row.confidence))
      ? ` · ${Math.round(Number(row.confidence) * 100)}% conf`
      : "";
  const pal = hiveToastPalette(lab);
  toast.custom(
    () => (
      <div
        style={{
          background: pal.bg,
          border: `1px solid ${pal.border}`,
          color: pal.color,
          borderRadius: 10,
          padding: "10px 12px",
          maxWidth: 400,
          fontSize: 12,
          lineHeight: 1.45,
          boxShadow: "0 10px 28px rgba(0,0,0,0.38)",
        }}
      >
        <div style={{ fontWeight: 800, letterSpacing: "0.03em", marginBottom: 4 }}>{label}</div>
        <div style={{ opacity: 0.96 }}>
          {msg}
          {conf}
        </div>
      </div>
    ),
    { duration: 4000, position: "bottom-right" },
  );
}

export function useLabHiveChat(dashReady: boolean): {
  messages: LabHiveRow[];
  labChatEnabled: boolean;
  setLabChatEnabled: (v: boolean | ((p: boolean) => boolean)) => void;
  hivePanelOpen: boolean;
  setHivePanelOpen: (v: boolean | ((p: boolean) => boolean)) => void;
} {
  const [messages, setMessages] = useState<LabHiveRow[]>([]);
  const [labChatEnabled, setLabChatEnabledState] = useState<boolean>(() => readLabChatEnabled());
  const [hivePanelOpen, setHivePanelOpen] = useState(false);
  const bootstrappedRef = useRef(false);
  const seenIdsRef = useRef<Set<string>>(new Set());

  const setLabChatEnabled = useCallback((v: boolean | ((p: boolean) => boolean)) => {
    setLabChatEnabledState((prev) => {
      const next = typeof v === "function" ? (v as (p: boolean) => boolean)(prev) : v;
      try {
        localStorage.setItem(LAB_CHAT_STORAGE_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  useEffect(() => {
    if (!labChatEnabled) {
      bootstrappedRef.current = false;
    }
  }, [labChatEnabled]);

  useEffect(() => {
    if (!dashReady || !labChatEnabled) return;
    let cancelled = false;

    const poll = async () => {
      try {
        const r = await fetch("/labs/chat", { cache: "no-store" });
        if (!r.ok || cancelled) return;
        const j = (await r.json()) as { messages?: LabHiveRow[] };
        const rows = Array.isArray(j.messages) ? j.messages : [];
        setMessages(rows);
        if (!bootstrappedRef.current) {
          rows.forEach((m) => {
            const id = String(m.id || "").trim();
            if (id) seenIdsRef.current.add(id);
          });
          bootstrappedRef.current = true;
          return;
        }
        for (const row of rows) {
          const id = String(row.id || "").trim();
          if (!id || seenIdsRef.current.has(id)) continue;
          seenIdsRef.current.add(id);
          pushLabHiveToast(row);
        }
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
  }, [dashReady, labChatEnabled]);

  return { messages, labChatEnabled, setLabChatEnabled, hivePanelOpen, setHivePanelOpen };
}

export function LabHiveChatPanel(props: {
  messages: LabHiveRow[];
  enabled: boolean;
  onToggleEnabled: (next: boolean) => void;
  open: boolean;
  onToggleOpen: () => void;
}) {
  const { messages, enabled, onToggleEnabled, open, onToggleOpen } = props;
  return (
    <div className={`lab-hive-chat${open ? " lab-hive-chat--open" : ""}`}>
      <div className="lab-hive-chat__head">
        <button type="button" className="lab-hive-chat__title-btn" onClick={onToggleOpen} title="Labs B/C/D analyst chatter">
          Lab Hive Chat
          <span className="lab-hive-chat__chev" aria-hidden>
            {open ? "▾" : "▸"}
          </span>
        </button>
        <label className="lab-hive-chat__toggle">
          <input type="checkbox" checked={enabled} onChange={(e) => onToggleEnabled(e.target.checked)} />
          Enable Agent Chatter
        </label>
      </div>
      {open ? (
        <div className="lab-hive-chat__body" role="log" aria-live="polite">
          {messages.length === 0 ? (
            <div className="sub lab-hive-chat__empty">Waiting for Labs B, C, and D to publish thoughts…</div>
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
      ) : null}
    </div>
  );
}
