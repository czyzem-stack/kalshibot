import { useMemo } from "react";
import { balanceHiveMessagesForTicker, type LabHiveRow } from "../labHiveChat";

function toneClassForLab(lab: string): string {
  if (lab === "lab_b") return "lab-ticker__item--b";
  if (lab === "lab_c") return "lab-ticker__item--c";
  if (lab === "lab_d") return "lab-ticker__item--d";
  return "lab-ticker__item--u";
}

function emojiForLab(lab: string): string {
  if (lab === "lab_b") return "🟡";
  if (lab === "lab_c") return "🔥";
  if (lab === "lab_d") return "🧪";
  return "⚪";
}

/** Compact chat line: speaker + optional confidence + body (matches marquee examples). */
function formatChatLine(row: LabHiveRow): string {
  const label = String(row.label || "Lab").replace(/^Lab\s+/i, "");
  const conf =
    row.confidence != null && Number.isFinite(Number(row.confidence))
      ? `${Math.round(Number(row.confidence) * 100)}%`
      : null;
  const msg = String(row.message || "").trim();
  const head = conf ? `${label} → ${conf}` : label;
  return `${head} — ${msg}`;
}

/** Two stacked lines per column: alternating labs after balance step. */
function chunkPairs(rows: LabHiveRow[]): LabHiveRow[][] {
  const pairs: LabHiveRow[][] = [];
  for (let i = 0; i < rows.length; i += 2) {
    pairs.push(rows.slice(i, i + 2));
  }
  return pairs.length ? pairs : [];
}

export default function LabTicker({ messages, enabled }: { messages: LabHiveRow[]; enabled: boolean }) {
  const rows = useMemo(() => {
    const balanced = balanceHiveMessagesForTicker(messages, 32);
    return balanced.filter((r) => String(r.message || "").trim().length > 0);
  }, [messages]);

  const pairs = useMemo(() => chunkPairs(rows), [rows]);

  if (!enabled || pairs.length === 0) return null;

  const cycle = [...pairs, ...pairs];

  return (
    <div className="lab-ticker-wrap" aria-label="Lab team chat ticker">
      <div className="lab-ticker-meta" aria-hidden="true">
        <span className="lab-ticker-meta__label">Labs B · C · D</span>
      </div>
      <div className="lab-ticker-track">
        {cycle.map((pair, i) => (
          <div key={`pair-${String(pair[0]?.id || i)}-${i}`} className="lab-ticker__pair">
            {pair.map((row, j) => {
              const lab = String(row.lab || "");
              return (
                <div
                  key={`${String(row.id || `${i}-${j}`)}`}
                  className={`lab-ticker__bubble lab-ticker__item ${toneClassForLab(lab)}`}
                >
                  <span className="lab-ticker__emoji" aria-hidden>
                    {emojiForLab(lab)}
                  </span>
                  <span className="lab-ticker__text">{formatChatLine(row)}</span>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
