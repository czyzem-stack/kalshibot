import { useMemo, useState } from "react";
import type { LabHiveRow } from "../labHiveChat";

function labToneClass(lab: string): string {
  if (lab === "lab_b") return "lab-think-tank__line--b";
  if (lab === "lab_c") return "lab-think-tank__line--c";
  if (lab === "lab_d") return "lab-think-tank__line--d";
  if (lab === "lab_e") return "lab-think-tank__line--e";
  return "lab-think-tank__line--u";
}

function emojiForLab(lab: string): string {
  if (lab === "lab_b") return "🟡";
  if (lab === "lab_c") return "🔥";
  if (lab === "lab_d") return "🧪";
  if (lab === "lab_e") return "⚖️";
  return "💬";
}

function labLetter(lab: string): string {
  if (lab === "lab_b") return "B";
  if (lab === "lab_c") return "C";
  if (lab === "lab_d") return "D";
  if (lab === "lab_e") return "E";
  return "?";
}

type Props = {
  messages: LabHiveRow[];
  enabled: boolean;
  dashReady: boolean;
};

const SHOW_MAX = 5;

/** Dense live log — latest five lines, zero fixed height, minimal chrome. */
export default function LabThinkTank({ messages, enabled, dashReady }: Props) {
  const [expanded, setExpanded] = useState(true);

  const lines = useMemo(() => {
    return [...messages].slice(-SHOW_MAX).filter((r) => String(r.message || "").trim().length > 0);
  }, [messages]);

  if (!dashReady) return null;

  return (
    <section className="lab-think-tank" aria-label="Lab Think Tank">
      <button type="button" className="lab-think-tank__expand-btn" aria-expanded={expanded} onClick={() => setExpanded((v) => !v)}>
        <span className="lab-think-tank__expand-title">Lab Think Tank</span>
        <span className="lab-think-tank__chevron" aria-hidden>
          {expanded ? "▼" : "▶"}
        </span>
      </button>

      {!expanded ? (
        <p className="sub lab-think-tank__hint">{enabled ? "Collapsed." : "Off — enable Agent Collaboration in Settings."}</p>
      ) : !enabled ? (
        <p className="sub lab-think-tank__hint">Enable Agent Collaboration under Settings → Global.</p>
      ) : (
        <div className="lab-think-tank__viewport" role="log" aria-live="polite">
          {lines.length === 0 ? (
            <p className="sub lab-think-tank__empty">
              No lines yet — turn on Labs B, C, D, E engines (paper). Lines appear within a tick or two.
            </p>
          ) : (
            <ul className="lab-think-tank__log">
              {lines.map((m, i) => {
                const lab = String(m.lab || "");
                const prev = i > 0 ? lines[i - 1] : undefined;
                const replyToPrev = Boolean(m.reply_to && prev?.id && m.reply_to === prev.id);
                return (
                  <li
                    key={String(m.id || `${m.ts_iso}-${lab}`)}
                    className={`lab-think-tank__line ${labToneClass(lab)}${replyToPrev ? " lab-think-tank__line--reply" : ""}`}
                  >
                    {replyToPrev ? (
                      <span className="lab-think-tank__replymark" title="Reply to previous line" aria-hidden>
                        →
                      </span>
                    ) : null}
                    <span className="lab-think-tank__ico" title={String(m.label || lab)} aria-hidden>
                      {emojiForLab(lab)}
                      <span className="lab-think-tank__letter">{labLetter(lab)}</span>
                    </span>
                    <span className="lab-think-tank__msg">{String(m.message || "").trim()}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
