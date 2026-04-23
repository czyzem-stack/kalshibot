import { useEffect, useState } from "react";

type AnyObj = Record<string, any>;

export default function HistoricalExplorerOverlay({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [table, setTable] = useState<"trades" | "signals" | "equity">("trades");
  const [branch, setBranch] = useState("live");
  const [rows, setRows] = useState<AnyObj[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    const run = async () => {
      setLoading(true);
      try {
        const q = new URLSearchParams({ branch, limit: "300" });
        const r = await fetch(`/api/history/${table}?${q.toString()}`);
        if (!r.ok) {
          setRows([]);
          return;
        }
        const j = await r.json();
        setRows(Array.isArray(j?.rows) ? j.rows : []);
      } finally {
        setLoading(false);
      }
    };
    void run();
  }, [open, table, branch]);

  if (!open) return null;

  const cols = rows.length ? Object.keys(rows[0]) : [];
  const exportHref = `/api/history/export.csv?${new URLSearchParams({ table, branch, limit: "10000" }).toString()}`;
  return (
    <div className="settings-overlay-root" role="dialog" aria-modal="true" aria-labelledby="history-overlay-title">
      <div className="settings-overlay-backdrop" onClick={onClose} aria-hidden="true" />
      <div className="settings-overlay-panel">
        <div className="settings-overlay-header">
          <h2 id="history-overlay-title" style={{ margin: 0 }}>
            Historical data explorer
          </h2>
          <button type="button" className="settings-overlay-close" onClick={onClose} aria-label="Close history explorer">
            ✕
          </button>
        </div>
        <div className="row" style={{ marginTop: 10, alignItems: "center" }}>
          <select value={table} onChange={(e) => setTable(e.target.value as "trades" | "signals" | "equity")}>
            <option value="trades">Trades</option>
            <option value="signals">Signals</option>
            <option value="equity">Equity snapshots</option>
          </select>
          <select value={branch} onChange={(e) => setBranch(e.target.value)}>
            <option value="live">live</option>
            <option value="lab_a">lab_a</option>
            <option value="lab_b">lab_b</option>
            <option value="lab_c">lab_c</option>
          </select>
          <a href={exportHref} style={{ marginLeft: 10 }}>
            Export CSV
          </a>
        </div>
        {loading ? <div className="sub">Loading…</div> : null}
        <div className="table-scroll" style={{ marginTop: 10, maxHeight: "65vh" }}>
          <table className="table">
            <thead>
              <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  {cols.map((c) => (
                    <td key={c}>{String(r[c] ?? "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

