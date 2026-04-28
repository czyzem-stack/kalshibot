import { useMemo } from "react";
import type { LabHiveRow } from "../labHiveChat";

function toneClassForLab(lab: string): string {
  if (lab === "lab_b") return "lab-ticker__item--b";
  if (lab === "lab_c") return "lab-ticker__item--c";
  if (lab === "lab_d") return "lab-ticker__item--d";
  return "lab-ticker__item--u";
}

function emojiForLab(lab: string): string {
  if (lab === "lab_b") return "🟡";
  if (lab === "lab_c") return "🩷";
  if (lab === "lab_d") return "🟣";
  return "⚪";
}

function formatLine(row: LabHiveRow): string {
  const lab = String(row.lab || "");
  const label = String(row.label || "Lab");
  const conf =
    row.confidence != null && Number.isFinite(Number(row.confidence))
      ? `${Math.round(Number(row.confidence) * 100)}%`
      : null;
  const msg = String(row.message || "").trim();
  const left = conf ? `${emojiForLab(lab)} ${label} → ${conf}` : `${emojiForLab(lab)} ${label}`;
  return `${left} — ${msg}`;
}

export default function LabTicker({ messages, enabled }: { messages: LabHiveRow[]; enabled: boolean }) {
  const rows = useMemo(() => {
    const base = [...messages].slice(-8);
    return base.filter((r) => String(r.message || "").trim().length > 0);
  }, [messages]);

  if (!enabled || rows.length === 0) return null;

  const cycle = [...rows, ...rows];
  return (
    <div className="lab-ticker-wrap" aria-label="Lab chatter ticker">
      <div className="lab-ticker-track">
        {cycle.map((row, i) => (
          <div key={`${String(row.id || i)}-${i}`} className={`lab-ticker__item ${toneClassForLab(String(row.lab || ""))}`}>
            {formatLine(row)}
          </div>
        ))}
      </div>
    </div>
  );
}

