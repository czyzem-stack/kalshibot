import { useMemo, useState } from "react";
import type { LabHiveRow } from "../labHiveChat";

function labToneClass(lab: string): string {
  if (lab === "lab_b") return "lab-think-tank__line--b";
  if (lab === "lab_c") return "lab-think-tank__line--c";
  if (lab === "lab_d") return "lab-think-tank__line--d";
  if (lab === "lab_e") return "lab-think-tank__line--e";
  return "lab-think-tank__line--u";
}

function labLetter(lab: string): string {
  if (lab === "lab_b") return "B";
  if (lab === "lab_c") return "C";
  if (lab === "lab_d") return "D";
  if (lab === "lab_e") return "E";
  return "?";
}

const ACTION_DETAIL: Record<string, string> = {
  council_reply: "Reply to another breeder, threaded by reply_to. Share caps rotate who speaks next.",
  strategic_pulse: "Proactive line (not tied to a sim fill). Pulses on a staggered timer per lab.",
  strategic_pulse_break: "Break-glass line when share math kept this lab quiet too long.",
  council_intro: "Boot line when this engine first joined the in-memory bus.",
  breeding_whisper: "Rare breeding-context nudge when GA breeding is enabled (still flavor only).",
  team_dialogue_sim: "Anchored reply after a peer line; triggered on sim fills, not ranked scans.",
  council_diversity_pulse:
    "Self-correct council: Diversify Labs set a ~45m window; server steers ~40–50% of Think Tank lines to adversarial (counter) pool for B–E only.",
};

type Props = {
  messages: LabHiveRow[];
  enabled: boolean;
  dashReady: boolean;
  /** ISO UTC from config / status; when set and in the future, council diversity window is active. */
  councilDiversityUntil?: string;
};

const SHOW_MAX = 5;

function formatDiversityBanner(until: string): string | null {
  const t = String(until || "").trim();
  if (!t) return null;
  const ms = Date.parse(t);
  if (!Number.isFinite(ms)) return null;
  if (ms <= Date.now()) return null;
  return `Council diversity window active until ${t.slice(0, 16).replace("T", " ")}Z — Think Tank favors dissent.`;
}

/** Dense live log — latest five lines, zero fixed height, minimal chrome. */
export default function LabThinkTank({ messages, enabled, dashReady, councilDiversityUntil }: Props) {
  const [expanded, setExpanded] = useState(true);
  const [openDetailId, setOpenDetailId] = useState<string | null>(null);

  const lines = useMemo(() => {
    return [...messages].slice(-SHOW_MAX).filter((r) => String(r.message || "").trim().length > 0);
  }, [messages]);

  const diversityBanner = useMemo(() => formatDiversityBanner(councilDiversityUntil || ""), [councilDiversityUntil]);

  const parentSnippet = (id: string | undefined) => {
    if (!id) return "";
    const hit = messages.find((r) => String(r.id || "") === id);
    const raw = String(hit?.message || "").trim().replace(/\s+/g, " ");
    return raw.length > 120 ? `${raw.slice(0, 117)}…` : raw;
  };

  if (!dashReady) return null;

  return (
    <section className="lab-think-tank" aria-label="Lab Think Tank">
      <button type="button" className="lab-think-tank__expand-btn" aria-expanded={expanded} onClick={() => setExpanded((v) => !v)}>
        <span className="lab-think-tank__expand-title">Lab Think Tank</span>
        <span className="lab-think-tank__chevron" aria-hidden>
          {expanded ? "\u2212" : "+"}
        </span>
      </button>

      {!expanded ? (
        <p className="sub lab-think-tank__hint">{enabled ? "Collapsed." : "Off — enable Agent Collaboration in Settings."}</p>
      ) : !enabled ? (
        <p className="sub lab-think-tank__hint">Enable Agent Collaboration under Settings → Global.</p>
      ) : (
        <div className="lab-think-tank__viewport" role="log" aria-live="polite">
          {diversityBanner ? <p className="sub lab-think-tank__diversity-banner">{diversityBanner}</p> : null}
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
                const mid = String(m.id || `${m.ts_iso}-${lab}`);
                const action = String(m.action || "").trim();
                const detail =
                  ACTION_DETAIL[action] ||
                  (action ? `Server action tag: ${action}.` : "Cosmetic council line (no trade link).");
                const conf =
                  m.confidence != null && Number.isFinite(Number(m.confidence))
                    ? `Confidence ${Number(m.confidence).toFixed(2)} (synthetic).`
                    : "";
                const thread = m.reply_to ? `Threads message id ${String(m.reply_to).slice(0, 8)}…` : "";
                const parentLine = m.reply_to ? parentSnippet(String(m.reply_to)) : "";
                const open = openDetailId === mid;
                return (
                  <li key={mid} className={`lab-think-tank__line ${labToneClass(lab)}${replyToPrev ? " lab-think-tank__line--reply" : ""}`}>
                    <div className="lab-think-tank__line-main">
                      {replyToPrev ? (
                        <span className="lab-think-tank__replymark" title="Reply to previous line in this list" aria-hidden>
                          {">"}
                        </span>
                      ) : null}
                      <span className="lab-think-tank__ico" title={String(m.label || lab)}>
                        <span className="lab-think-tank__letter">{labLetter(lab)}</span>
                      </span>
                      <span className="lab-think-tank__msg">{String(m.message || "").trim()}</span>
                      <button
                        type="button"
                        className="lab-think-tank__detail-btn"
                        aria-expanded={open}
                        aria-label={open ? "Hide line context" : "Explain this line"}
                        onClick={() => setOpenDetailId(open ? null : mid)}
                      >
                        {open ? "hide" : "why?"}
                      </button>
                    </div>
                    {open ? (
                      <div className="lab-think-tank__detail">
                        <p className="sub" style={{ margin: 0 }}>
                          {detail} {conf} {thread}
                        </p>
                        {parentLine ? (
                          <p className="sub" style={{ margin: "6px 0 0" }}>
                            Upstream text: {parentLine}
                          </p>
                        ) : null}
                      </div>
                    ) : null}
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
