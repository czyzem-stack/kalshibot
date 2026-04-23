import { useEffect, useMemo, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import {
  DevSimHighYesControl,
  EMPTY_RULES_LIST,
  NoBandsSliders,
  NoBetWhenYesBelowControl,
  PaperFeeBpsControl,
  RuleExperimentHints,
  RulesBandsSliders,
  RulesEditor,
  SwingExitImpliedDropControl,
} from "./settingsRules";

type AnyObj = Record<string, any>;
type SettingsTab = "live" | "lab_a" | "lab_b" | "lab_c" | "lab_ab_optimizer" | "all";
type LabBranchKey = "a" | "b" | "c";

function LabSizingInputs({ which, lab, cfg, busy }: { which: LabBranchKey; lab: AnyObj; cfg: AnyObj; busy: boolean }) {
  const p = `lab_${which}`;
  const defFrac = which === "a" ? 0.055 : which === "b" ? 0.06 : 0.1;
  const defWin = which === "a" ? 15 : which === "b" ? 12 : 10;
  const labTitle = which === "a" ? "A (staging)" : which === "b" ? "B (conservative)" : "C (aggressive)";
  return (
    <div>
      <strong style={{ fontSize: 12 }} title={`Branch lab_${which}`}>
        Lab {labTitle}
      </strong>
      <div className="field" style={{ marginTop: 6 }}>
        <label htmlFor={`${p}_paper`} className="section-tip">
          Paper balance (cents)
        </label>
        <input
          id={`${p}_paper`}
          type="number"
          defaultValue={String(lab.paper_balance_cents ?? cfg.paper_balance_cents ?? 500000)}
          disabled={busy}
        />
      </div>
      <div className="field">
        <label htmlFor={`${p}_frac`} className="section-tip">
          Balance fraction per window
        </label>
        <input id={`${p}_frac`} type="text" defaultValue={String(lab.balance_fraction_per_window ?? defFrac)} disabled={busy} />
      </div>
      <div className="field">
        <label htmlFor={`${p}_win`} className="section-tip">
          Window (minutes)
        </label>
        <input id={`${p}_win`} type="number" defaultValue={String(lab.window_minutes ?? defWin)} disabled={busy} />
      </div>
    </div>
  );
}

function LabBranchPanel({
  branch,
  lab,
  cfg,
  busy,
  onResetTradingData,
  onSaveLabRules,
  onSaveLabFromSliders,
  style,
}: {
  branch: LabBranchKey;
  lab: AnyObj;
  cfg: AnyObj;
  busy: boolean;
  onResetTradingData: (branch: "lab_a" | "lab_b" | "lab_c", backup: boolean) => void;
  onSaveLabRules: (rules: AnyObj[]) => void;
  onSaveLabFromSliders: () => void;
  style?: CSSProperties;
}) {
  const p = `lab_${branch}`;
  const resetKey = branch === "a" ? "lab_a" : branch === "b" ? "lab_b" : "lab_c";
  const title = branch === "a" ? "Lab A (staging)" : branch === "b" ? "Lab B (conservative)" : "Lab C (aggressive)";
  const autoResetTitle =
    "When enabled, wipe this lab’s SQLite trades/signals/equity once per bad streak if a tick ends with an error OR derived paper equity (seed + settled PnL − open commit) is ≤ 0—then the next tick starts from Paper balance (cents) in the sizing row above.";
  const note: ReactNode =
    branch === "a" ? (
      <>
        Clears <code>lab_a</code> / legacy <code>sim_lab</code> rows only, once per bad streak, so the next tick starts from
        your configured bankroll seed.
      </>
    ) : branch === "b" ? (
      <>Clears <code>lab_b</code> rows only, once per bad streak (tick error or equity ≤ 0).</>
    ) : (
      <>Clears <code>lab_c</code> rows only, once per bad streak (tick error or equity ≤ 0).</>
    );
  const resetConfirm =
    branch === "a"
      ? "Reset Lab A data only? Removes SQLite signals, trades, and equity snapshots for Lab A (including legacy sim_lab). Live and other labs are kept."
      : branch === "b"
        ? "Reset Lab B data only? Removes SQLite signals, trades, and equity snapshots for Lab B. Live and other labs are kept."
        : "Reset Lab C data only? Removes SQLite signals, trades, and equity snapshots for Lab C. Live and other labs are kept.";
  const resetBtnTitle =
    branch === "a"
      ? "Deletes Lab A branch rows only (lab_a and legacy sim_lab)."
      : branch === "b"
        ? "Deletes Lab B branch rows only."
        : "Deletes Lab C branch rows only.";

  return (
    <div
      key={`lab-${branch}-fields-${String(lab.paper_balance_cents ?? "")}-${String(lab.window_minutes ?? "")}-${String(lab.balance_fraction_per_window ?? "")}-${lab.auto_optimize ? 1 : 0}-${lab.auto_reset_paper_on_tick_failure ? 1 : 0}`}
      className="panel settings-nested-panel"
      style={{ padding: "12px 14px", ...style }}
    >
      <h3 style={{ margin: 0 }} title={`Branch lab_${branch} configuration.`}>
        {title}
      </h3>
      <p className="sub" style={{ marginTop: 8, marginBottom: 0, fontSize: 12, lineHeight: 1.45 }}>
        Bankroll, fraction, and window are in the <strong>Simulation labs</strong> row above. Here: auto-optimize (per-lab fraction nudger), auto-reset,
        rule bands, and save. Scheduled optimizer persists adaptive tuning to <strong>Lab A only</strong>; B/C stay reference arms.
      </p>
      <label className="checkbox section-tip" style={{ border: "none", marginTop: 12 }} title="Legacy per-lab fraction nudger when the scheduled Claude optimizer is off.">
        <input id={`${p}_opt`} type="checkbox" defaultChecked={Boolean(lab.auto_optimize)} disabled={busy} />
        <span>Auto-optimize</span>
      </label>
      <label className="checkbox section-tip" style={{ border: "none", marginTop: 6 }} title={autoResetTitle}>
        <input id={`${p}_auto_reset_failure`} type="checkbox" defaultChecked={Boolean(lab.auto_reset_paper_on_tick_failure)} disabled={busy} />
        <span>Auto-reset paper data on tick failure (loop testing)</span>
      </label>
      <p className="sub" style={{ marginTop: 6, fontSize: 11, lineHeight: 1.45 }}>
        {note}
      </p>
      <label className="checkbox section-tip" style={{ border: "none", marginTop: 10 }}>
        <input id={`reset_backup_${p}`} type="checkbox" defaultChecked disabled={busy} />
        <span>Before {title} reset: copy SQLite + JSONL exports</span>
      </label>
      <button
        type="button"
        className="primary"
        style={{ marginTop: 8, borderColor: "#6b2a2a", background: "linear-gradient(180deg,#2a1520,#1a0f18)" }}
        disabled={busy}
        title={resetBtnTitle}
        onClick={() => {
          const el = document.getElementById(`reset_backup_${p}`) as HTMLInputElement | null;
          const backup = el ? el.checked : true;
          if (!window.confirm(resetConfirm)) return;
          void onResetTradingData(resetKey, backup);
        }}
      >
        Reset {title} trading data
      </button>
      <RulesBandsSliders
        key={`lab-${branch}-yes-${Array.isArray(lab.rules) ? lab.rules.length : 0}-${(cfg.rules || []).length}`}
        rules={Array.isArray(lab.rules) && lab.rules.length ? lab.rules : (cfg.rules ?? EMPTY_RULES_LIST)}
        disabled={busy}
        onSave={(r) => void onSaveLabRules(r)}
      />
      <NoBandsSliders
        key={`lab-${branch}-no-${Array.isArray(lab.rules) ? lab.rules.length : 0}-${(cfg.rules || []).length}`}
        rules={Array.isArray(lab.rules) && lab.rules.length ? lab.rules : (cfg.rules ?? EMPTY_RULES_LIST)}
        disabled={busy}
        onSave={(r) => void onSaveLabRules(r)}
      />
      <button
        className="primary"
        style={{ marginTop: 10 }}
        disabled={busy}
        title={`Save ${title} optimizer toggles and auto-reset (sizing uses values in the row above).`}
        onClick={() => void onSaveLabFromSliders()}
      >
        Save {title} options
      </button>
    </div>
  );
}

export type SettingsOverlayProps = {
  open: boolean;
  onClose: () => void;
  dash: AnyObj;
  cfg: AnyObj;
  labA: AnyObj;
  labB: AnyObj;
  labC: AnyObj;
  busy: boolean;
  onSaveRules: (rules: AnyObj[]) => void | Promise<void>;
  onSaveYesSubtitleFilter: () => void | Promise<void>;
  onSaveExcludeSubtitleFilter: () => void | Promise<void>;
  onSaveSizing: () => void | Promise<void>;
  onSaveLabAFromSliders: () => void | Promise<void>;
  onSaveLabBFromSliders: () => void | Promise<void>;
  onSaveLabCFromSliders: () => void | Promise<void>;
  onSaveLabARules: (rules: AnyObj[]) => void | Promise<void>;
  onSaveLabBRules: (rules: AnyObj[]) => void | Promise<void>;
  onSaveLabCRules: (rules: AnyObj[]) => void | Promise<void>;
  onSaveDevSimHighYesPct: (pct: number | null) => void | Promise<void>;
  onSaveNoBetWhenYesBelow: (pct: number | null) => void | Promise<void>;
  onSaveSwingExitImpliedDropPct: (pct: number | null) => void | Promise<void>;
  onSavePaperFees: (patch: AnyObj) => void | Promise<void>;
  optimizerCfg: AnyObj;
  onSaveOptimizerConfig: (patch: AnyObj) => void | Promise<void>;
  optimizerSaving?: boolean;
  onResetTradingData: (branch: "all" | "live" | "lab_a" | "lab_b" | "lab_c", backup: boolean) => void | Promise<void>;
  /** Direct ``PUT /api/config/lab-branches`` (merge + optional branch data reset); independent of optimizer. */
  onApplyLabBranches: (body: AnyObj) => void | Promise<void>;
};

export default function SettingsOverlay({
  open,
  onClose,
  dash,
  cfg,
  labA,
  labB,
  labC,
  busy,
  onSaveRules,
  onSaveYesSubtitleFilter,
  onSaveExcludeSubtitleFilter,
  onSaveSizing,
  onSaveLabAFromSliders,
  onSaveLabBFromSliders,
  onSaveLabCFromSliders,
  onSaveLabARules,
  onSaveLabBRules,
  onSaveLabCRules,
  onSaveDevSimHighYesPct,
  onSaveNoBetWhenYesBelow,
  onSaveSwingExitImpliedDropPct,
  onSavePaperFees,
  optimizerCfg,
  onSaveOptimizerConfig,
  optimizerSaving = false,
  onResetTradingData,
  onApplyLabBranches,
}: SettingsOverlayProps) {
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("all");
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  useEffect(() => {
    if (open) setSettingsTab("all");
  }, [open]);

  const showLive = settingsTab === "live" || settingsTab === "all";
  const showLabA = settingsTab === "lab_a" || settingsTab === "all";
  const showLabB = settingsTab === "lab_b" || settingsTab === "all";
  const showLabC = settingsTab === "lab_c" || settingsTab === "all";
  /** Shared bankroll row: any tab except Live-only (includes optimizer tab). */
  const showLabSizingGrid = settingsTab !== "live";
  const showLabAColumn = settingsTab === "all" || settingsTab === "lab_a" || settingsTab === "lab_ab_optimizer";
  const showLabBColumn = settingsTab === "all" || settingsTab === "lab_b" || settingsTab === "lab_ab_optimizer";
  const showLabCColumn = settingsTab === "all" || settingsTab === "lab_c" || settingsTab === "lab_ab_optimizer";
  const showCombinedLabReset =
    settingsTab === "all" || settingsTab === "lab_ab_optimizer" || settingsTab === "lab_a" || settingsTab === "lab_b" || settingsTab === "lab_c";
  const nLabSizingCols = [showLabAColumn, showLabBColumn, showLabCColumn].filter(Boolean).length;
  const labSizingGridTemplate =
    nLabSizingCols <= 1 ? "1fr" : nLabSizingCols === 2 ? "1fr 1fr" : "repeat(3, minmax(0, 1fr))";
  // Optimizer controls + save button: dedicated tab, All, or any lab tab.
  const showOpt =
    settingsTab === "lab_ab_optimizer" ||
    settingsTab === "all" ||
    settingsTab === "lab_a" ||
    settingsTab === "lab_b" ||
    settingsTab === "lab_c";
  const showData = settingsTab === "all";
  const historyRows = useMemo(
    () => (Array.isArray(optimizerCfg?.change_history) ? (optimizerCfg.change_history as AnyObj[]) : []),
    [optimizerCfg?.change_history],
  );

  if (!open) return null;

  return (
    <div className="settings-overlay-root" role="dialog" aria-modal="true" aria-labelledby="settings-overlay-title">
      <div className="settings-overlay-backdrop" onClick={onClose} aria-hidden="true" />
      <div className="settings-overlay-panel">
        <div className="settings-overlay-header">
          <h2
            id="settings-overlay-title"
            className="section-tip"
            style={{ margin: 0 }}
            title="Filters, sizing, rule bands, JSON rules, sim lab. Close: ✕, Escape, or click outside."
          >
            Settings
          </h2>
          <button type="button" className="settings-overlay-close" onClick={onClose} aria-label="Close settings">
            ✕
          </button>
        </div>
        <div className="chart-tabs" role="tablist" aria-label="Settings sections" style={{ marginTop: 12 }}>
          {(
            [
              ["live", "Live"],
              ["lab_a", "Lab A"],
              ["lab_b", "Lab B"],
              ["lab_c", "Lab C"],
              ["lab_ab_optimizer", "Optimizer"],
              ["all", "All"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={settingsTab === id}
              className={`chart-tab ${settingsTab === id ? "chart-tab--active" : ""}`}
              onClick={() => setSettingsTab(id)}
            >
              {label}
            </button>
          ))}
        </div>
        {showLive ? (
          <>
        <h2 className="section-tip" style={{ marginTop: 12 }} title="Limit or skip YES rows by title substring before rules run.">
          Who we trade (filters)
        </h2>
        <div className="field" key={`ysf-${String(cfg.only_yes_subtitle_contains ?? "")}`}>
          <label
            htmlFor="yes_sub_filter"
            className="section-tip"
            title="Leave blank to allow both Up and Down. Type up or down (substring match) to limit direction."
          >
            Only if YES title contains
          </label>
          <input
            id="yes_sub_filter"
            type="text"
            placeholder="blank = up and down"
            defaultValue={String(cfg.only_yes_subtitle_contains ?? "")}
          />
        </div>
        <button
          className="primary"
          disabled={busy}
          title="Persist the “only if” subtitle filter to the server."
          onClick={() => void onSaveYesSubtitleFilter()}
        >
          Save “only if” filter
        </button>

        <div className="field" style={{ marginTop: 14 }} key={`excl-${String(cfg.exclude_yes_subtitle_contains ?? "default")}`}>
          <label
            htmlFor="exclude_sub_filter"
            className="section-tip"
            title="Comma-separated substrings (case-insensitive). Matched rows are skipped for trading (not just display). Leave empty on Kalshi demo where subtitles often contain TBD. On prod, add tokens like tbd only if you want to skip unpriced lines."
          >
            Skip if YES title contains (comma-separated)
          </label>
          <input
            id="exclude_sub_filter"
            type="text"
            placeholder="(empty)"
            defaultValue={String(cfg.exclude_yes_subtitle_contains ?? "")}
          />
        </div>
        <button
          className="primary"
          disabled={busy}
          title="Persist skip-list substrings."
          onClick={() => void onSaveExcludeSubtitleFilter()}
        >
          Save skip list
        </button>

        <h2 className="section-tip" style={{ marginTop: 16 }} title="Stake = ceil(available $ × fraction), min $1. Available = bankroll minus spend in the current window bucket. Window resets dedupe/spend accounting only (not contract expiry).">
          Sizing
        </h2>
        <div className="row" style={{ marginTop: 10 }}>
          <span className="pill section-tip" title="Per-trade fraction of cash still available in the window.">
            fraction <strong>{String(cfg.balance_fraction_per_window ?? "")}</strong>
          </span>
          <span className="pill section-tip" title="Minutes per spend / dedupe bucket.">
            window <strong>{String(cfg.window_minutes ?? "")}m</strong>
          </span>
          <span className="pill section-tip" title="Seconds between engine loop iterations (Kalshi rate limits apply).">
            poll <strong>{String(cfg.poll_seconds ?? "")}s</strong>
          </span>
        </div>

        <div
          key={`sizing-${String(cfg.balance_fraction_per_window)}-${String(cfg.window_minutes)}-${String(cfg.poll_seconds)}-${String(cfg.paper_balance_cents)}`}
        >
          <div className="field">
            <label htmlFor="frac" className="section-tip" title="e.g. 0.03 → each buy ≈ ceil(3% of cash left in the window), minimum $1.">
              Balance fraction per trade
            </label>
            <input id="frac" type="text" defaultValue={String(cfg.balance_fraction_per_window ?? 0.03)} />
          </div>
          <div className="field">
            <label htmlFor="winmin" className="section-tip" title="Spend cap and dedupe keys roll by this many minutes.">
              Window length (minutes)
            </label>
            <input id="winmin" type="number" defaultValue={String(cfg.window_minutes ?? 15)} />
          </div>
          <div className="field">
            <label htmlFor="poll" className="section-tip" title="Engine sleep between ticks; keep within 2–120s for Kalshi.">
              Poll seconds (2–120)
            </label>
            <input id="poll" type="number" defaultValue={String(cfg.poll_seconds ?? 8)} />
          </div>
          <div className="field">
            <label htmlFor="paper" className="section-tip" title="Paper bankroll in cents when Live is in simulate mode or balance API fails.">
              Paper balance (cents)
            </label>
            <input id="paper" type="number" defaultValue={String(cfg.paper_balance_cents ?? 500000)} />
          </div>
          <button className="primary" disabled={busy} title="Save sizing fields above." onClick={() => void onSaveSizing()}>
            Save sizing
          </button>
        </div>

        <RuleExperimentHints dash={dash} busy={busy} onApply={(r) => void onSaveRules(r)} />
        <RulesBandsSliders rules={cfg.rules ?? EMPTY_RULES_LIST} disabled={busy} onSave={(r) => void onSaveRules(r)} />
        <NoBandsSliders rules={cfg.rules ?? EMPTY_RULES_LIST} disabled={busy} onSave={(r) => void onSaveRules(r)} />
        <NoBetWhenYesBelowControl cfg={cfg} busy={busy} onSave={(v) => void onSaveNoBetWhenYesBelow(v)} />
        <DevSimHighYesControl cfg={cfg} busy={busy} onSave={(v) => void onSaveDevSimHighYesPct(v)} />
        <SwingExitImpliedDropControl cfg={cfg} busy={busy} onSave={(v) => void onSaveSwingExitImpliedDropPct(v)} />
          <PaperFeeBpsControl cfg={cfg} busy={busy} onSave={(patch) => void onSavePaperFees(patch)} />

        <div className="panel settings-nested-panel" style={{ marginTop: 16, padding: "12px 14px" }}>
          <h3 className="section-tip" style={{ margin: 0 }} title="Clears SQLite signals, trades, and equity snapshots for branch live only.">
            Live branch data (temporary)
          </h3>
          <p className="sub" style={{ marginTop: 8, fontSize: 12, lineHeight: 1.45 }}>
            Until Kalshi is wired for real fills: use this to wipe <strong>Live</strong> rows in the local DB (paper sim on Live, logged signals/trades).{" "}
            <strong>Remove this block from Settings when going fully live.</strong>
          </p>
          <label className="checkbox section-tip" style={{ border: "none", marginTop: 8 }}>
            <input id="reset_backup_live" type="checkbox" defaultChecked disabled={busy} />
            <span>Before reset: copy SQLite + table JSONL exports</span>
          </label>
          <button
            type="button"
            className="primary"
            style={{ marginTop: 10, borderColor: "#6b2a2a", background: "linear-gradient(180deg,#2a1520,#1a0f18)" }}
            disabled={busy}
            title="Deletes signals, trades, and equity snapshots where branch is live only."
            onClick={() => {
              const el = document.getElementById("reset_backup_live") as HTMLInputElement | null;
              const backup = el ? el.checked : true;
              if (
                !window.confirm(
                  "Reset Live branch data only? This removes SQLite signals, trades, and equity snapshots for branch=live. Lab A/B/C rows are kept.",
                )
              ) {
                return;
              }
              void onResetTradingData("live", backup);
            }}
          >
            Reset Live branch data (SQLite)
          </button>
        </div>

        <details style={{ marginTop: 12 }}>
          <summary
            className="sub section-tip"
            style={{ cursor: "pointer" }}
            title="Edit the raw rules array. Invalid JSON is rejected on save."
          >
            Advanced: edit rules as JSON
          </summary>
          <p className="sub" style={{ marginTop: 8, fontSize: 12, lineHeight: 1.45 }}>
            Optional <code>&quot;side&quot;: &quot;no&quot;</code> on a rule: <code>min_prob</code>/<code>max_prob</code> then apply to{" "}
            <strong>implied NO</strong> (1 − implied YES from the book). The engine buys <strong>NO</strong> at the NO ask
            (or 1 − YES bid). Omit <code>side</code> or use <code>&quot;yes&quot;</code> for YES buys (default).
          </p>
          <RulesEditor rules={cfg.rules ?? EMPTY_RULES_LIST} disabled={busy} onSave={(r) => void onSaveRules(r)} />
        </details>
          </>
        ) : null}

        {showLabSizingGrid ? (
          <div
            key={`lab-sizing-${String(labA.paper_balance_cents ?? "")}-${String(labB.paper_balance_cents ?? "")}-${String(labC.paper_balance_cents ?? "")}-${String(labA.balance_fraction_per_window ?? "")}-${String(labB.balance_fraction_per_window ?? "")}-${String(labC.balance_fraction_per_window ?? "")}`}
            className="panel settings-nested-panel"
            style={{ marginTop: showLive ? 20 : 12, padding: "12px 14px" }}
          >
            <h2 className="section-tip" style={{ marginTop: 0 }} title="Parallel paper labs with separate sizing, rules, and bankroll.">
              Simulation labs
            </h2>
            <p className="sub" style={{ marginTop: 6, fontSize: 12, lineHeight: 1.45 }}>
              <strong>Lab A</strong> = staging (scheduled optimizer persists adaptive tuning here). <strong>Lab B</strong> = conservative and{" "}
              <strong>Lab C</strong> = aggressive reference arms (same data to Claude for context; no auto-applied rule changes on B/C). Bankroll
              row values are used by per-lab <strong>Save … options</strong> and <code>PUT /api/config/lab-branches</code>. Per-lab YES/NO bands override Live until cleared in JSON;
              sliders fall back to the Live rule list when a lab has no saved <code>rules</code>.
            </p>
            <div
              className="row"
              style={{
                display: "grid",
                gridTemplateColumns: labSizingGridTemplate,
                gap: 12,
                marginTop: 12,
              }}
            >
              {showLabAColumn ? <LabSizingInputs which="a" lab={labA} cfg={cfg} busy={busy} /> : null}
              {showLabBColumn ? <LabSizingInputs which="b" lab={labB} cfg={cfg} busy={busy} /> : null}
              {showLabCColumn ? <LabSizingInputs which="c" lab={labC} cfg={cfg} busy={busy} /> : null}
            </div>
            {showCombinedLabReset ? (
              <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
                <h3 className="section-tip" style={{ margin: "0 0 6px 0", fontSize: 13 }} title="Optional SQLite wipe, then merge the bankroll/sizing numbers above in one request.">
                  Reset lab data + apply sizing (A / B / C)
                </h3>
                <p className="sub" style={{ marginBottom: 10, fontSize: 12, lineHeight: 1.45 }}>
                  Same scope as the per-lab reset buttons below, but you can wipe selected branches and push the sizing row above in one step.
                </p>
                <div className="field">
                  <label htmlFor="bulk_lab_reset" className="section-tip" title="Runs before applying lab_* patches from the sizing row.">
                    Reset lab trading data first
                  </label>
                  <select id="bulk_lab_reset" defaultValue="none" disabled={busy}>
                    <option value="none">No reset (config only)</option>
                    <option value="lab_a">Lab A only</option>
                    <option value="lab_b">Lab B only</option>
                    <option value="lab_c">Lab C only</option>
                    <option value="both">Lab A + Lab B</option>
                    <option value="all_labs">Lab A + B + C</option>
                  </select>
                </div>
                <label className="checkbox section-tip" style={{ border: "none", marginBottom: 10 }}>
                  <input id="bulk_lab_backup" type="checkbox" defaultChecked disabled={busy} />
                  <span>SQLite + JSONL backup when reset runs (first branch only if both)</span>
                </label>
                <button
                  type="button"
                  className="primary"
                  disabled={busy || optimizerSaving}
                  title="PUT /api/config/lab-branches — reads lab_a_* / lab_b_* / lab_c_* from the sizing row."
                  onClick={() => {
                    const parseC = (id: string) =>
                      Math.round(Number(String((document.getElementById(id) as HTMLInputElement | null)?.value ?? "").replace(/,/g, "").trim()));
                    const parseF = (id: string) =>
                      Number(String((document.getElementById(id) as HTMLInputElement | null)?.value ?? "").replace(/,/g, "").trim());
                    const resetVal = String((document.getElementById("bulk_lab_reset") as HTMLSelectElement | null)?.value || "none");
                    const backupEl = document.getElementById("bulk_lab_backup") as HTMLInputElement | null;
                    const backup = backupEl ? backupEl.checked : true;
                    const laPaper = parseC("lab_a_paper");
                    const laFrac = parseF("lab_a_frac");
                    const laWin = parseC("lab_a_win");
                    const lbPaper = parseC("lab_b_paper");
                    const lbFrac = parseF("lab_b_frac");
                    const lbWin = parseC("lab_b_win");
                    const lcPaper = parseC("lab_c_paper");
                    const lcFrac = parseF("lab_c_frac");
                    const lcWin = parseC("lab_c_win");
                    if (!Number.isFinite(laFrac) || laFrac < 0.0001 || laFrac > 1) {
                      window.alert("Lab A balance fraction must be between 0.0001 and 1.");
                      return;
                    }
                    if (!Number.isFinite(lbFrac) || lbFrac < 0.0001 || lbFrac > 1) {
                      window.alert("Lab B balance fraction must be between 0.0001 and 1.");
                      return;
                    }
                    if (!Number.isFinite(lcFrac) || lcFrac < 0.0001 || lcFrac > 1) {
                      window.alert("Lab C balance fraction must be between 0.0001 and 1.");
                      return;
                    }
                    if (!Number.isFinite(laWin) || laWin < 1 || laWin > 1440 || !Number.isInteger(laWin)) {
                      window.alert("Lab A window must be an integer 1–1440 minutes.");
                      return;
                    }
                    if (!Number.isFinite(lbWin) || lbWin < 1 || lbWin > 1440 || !Number.isInteger(lbWin)) {
                      window.alert("Lab B window must be an integer 1–1440 minutes.");
                      return;
                    }
                    if (!Number.isFinite(lcWin) || lcWin < 1 || lcWin > 1440 || !Number.isInteger(lcWin)) {
                      window.alert("Lab C window must be an integer 1–1440 minutes.");
                      return;
                    }
                    if (!Number.isFinite(laPaper) || laPaper < 0 || !Number.isInteger(laPaper)) {
                      window.alert("Lab A paper balance must be a non-negative integer (cents).");
                      return;
                    }
                    if (!Number.isFinite(lbPaper) || lbPaper < 0 || !Number.isInteger(lbPaper)) {
                      window.alert("Lab B paper balance must be a non-negative integer (cents).");
                      return;
                    }
                    if (!Number.isFinite(lcPaper) || lcPaper < 0 || !Number.isInteger(lcPaper)) {
                      window.alert("Lab C paper balance must be a non-negative integer (cents).");
                      return;
                    }
                    if (resetVal !== "none") {
                      const scope =
                        resetVal === "both"
                          ? "Lab A and Lab B"
                          : resetVal === "all_labs"
                            ? "Lab A, Lab B, and Lab C"
                            : resetVal;
                      const ok = window.confirm(
                        `Reset SQLite trading data for ${scope} before saving new bankroll/sizing? This cannot be undone (backups may run).`,
                      );
                      if (!ok) return;
                    }
                    void onApplyLabBranches({
                      reset_data: resetVal,
                      backup,
                      lab_a: {
                        paper_balance_cents: laPaper,
                        balance_fraction_per_window: laFrac,
                        window_minutes: laWin,
                      },
                      lab_b: {
                        paper_balance_cents: lbPaper,
                        balance_fraction_per_window: lbFrac,
                        window_minutes: lbWin,
                      },
                      lab_c: {
                        paper_balance_cents: lcPaper,
                        balance_fraction_per_window: lcFrac,
                        window_minutes: lcWin,
                      },
                    });
                  }}
                >
                  Apply reset (if any) + bankroll / sizing
                </button>
              </div>
            ) : null}
          </div>
        ) : null}

        {showLabA ? (
          <LabBranchPanel
            branch="a"
            lab={labA}
            cfg={cfg}
            busy={busy}
            onResetTradingData={onResetTradingData}
            onSaveLabRules={onSaveLabARules}
            onSaveLabFromSliders={onSaveLabAFromSliders}
            style={{ marginTop: showLabSizingGrid ? 12 : 20 }}
          />
        ) : null}

        {showLabB ? (
          <LabBranchPanel
            branch="b"
            lab={labB}
            cfg={cfg}
            busy={busy}
            onResetTradingData={onResetTradingData}
            onSaveLabRules={onSaveLabBRules}
            onSaveLabFromSliders={onSaveLabBFromSliders}
            style={{ marginTop: showLabA ? 12 : showLabSizingGrid ? 12 : 20 }}
          />
        ) : null}

        {showLabC ? (
          <LabBranchPanel
            branch="c"
            lab={labC}
            cfg={cfg}
            busy={busy}
            onResetTradingData={onResetTradingData}
            onSaveLabRules={onSaveLabCRules}
            onSaveLabFromSliders={onSaveLabCFromSliders}
            style={{ marginTop: showLabB || showLabA ? 12 : showLabSizingGrid ? 12 : 20 }}
          />
        ) : null}

        {showOpt ? (
          <div className="panel settings-nested-panel" style={{ marginTop: 16, padding: "12px 14px" }}>
            <h2 className="section-tip" style={{ marginTop: 0 }} title="Scheduled Claude + adaptive loop; persists rule/threshold and bet-fraction changes to Lab A only.">
              Optimizer (labs)
            </h2>
            <p className="sub" style={{ marginTop: 6, fontSize: 12, lineHeight: 1.45 }}>
              In <strong>duel</strong> mode, Lab B is conservative, Lab C aggressive, and Lab A uses a <strong>blend</strong> staging style for adaptive
              guardrails. In <strong>independent</strong> mode, each lab’s style fields below apply to how the model reasons about that arm (B/C stay
              read-only for persisted tuning). Lab bankroll and sizing live in <strong>Simulation labs</strong> above.
            </p>
            <div className="field">
              <label>Mode</label>
              <select id="opt_mode" defaultValue={String(optimizerCfg?.mode || "duel")}>
                <option value="duel">Duel (B conservative · C aggressive · A blend)</option>
                <option value="independent">Independent (use per-lab styles)</option>
              </select>
            </div>
            <label className="checkbox" style={{ border: "none" }}>
              <input id="opt_enabled" type="checkbox" defaultChecked={Boolean(optimizerCfg?.enabled)} disabled={busy} />
              <span>Enable scheduled optimizer loop</span>
            </label>
            <label className="checkbox" style={{ border: "none" }}>
              <input id="opt_adaptive_enabled" type="checkbox" defaultChecked={Boolean(optimizerCfg?.adaptive_enabled ?? true)} disabled={busy} />
              <span>Enable adaptive threshold/time auto-correction</span>
            </label>
            <label className="checkbox" style={{ border: "none" }}>
              <input id="opt_lab_a_enabled" type="checkbox" defaultChecked={Boolean(optimizerCfg?.lab_a_enabled ?? true)} disabled={busy} />
              <span>Lab A staging (adaptive + bet applies here)</span>
            </label>
            <label className="checkbox" style={{ border: "none" }}>
              <input id="opt_lab_b_enabled" type="checkbox" defaultChecked={Boolean(optimizerCfg?.lab_b_enabled ?? true)} disabled={busy} />
              <span>Include Lab B in optimizer context</span>
            </label>
            <label className="checkbox" style={{ border: "none" }}>
              <input id="opt_lab_c_enabled" type="checkbox" defaultChecked={Boolean(optimizerCfg?.lab_c_enabled ?? true)} disabled={busy} />
              <span>Include Lab C in optimizer context</span>
            </label>
            <div className="field">
              <label>Lab A style</label>
              <select id="opt_lab_a_style" defaultValue={String(optimizerCfg?.lab_a_style || "blend")}>
                <option value="blend">Blend (staging)</option>
                <option value="conservative">Conservative</option>
                <option value="aggressive">Aggressive</option>
              </select>
            </div>
            <div className="field">
              <label>Lab B style</label>
              <select id="opt_lab_b_style" defaultValue={String(optimizerCfg?.lab_b_style || "conservative")}>
                <option value="conservative">Conservative</option>
                <option value="aggressive">Aggressive</option>
                <option value="blend">Blend</option>
              </select>
            </div>
            <div className="field">
              <label>Lab C style</label>
              <select id="opt_lab_c_style" defaultValue={String(optimizerCfg?.lab_c_style || "aggressive")}>
                <option value="aggressive">Aggressive</option>
                <option value="conservative">Conservative</option>
                <option value="blend">Blend</option>
              </select>
            </div>
            <div className="field">
              <label>Loss streak trigger before adjustment</label>
              <input id="opt_loss_streak_trigger" type="number" min={2} max={12} defaultValue={String(optimizerCfg?.loss_streak_trigger ?? 3)} />
            </div>
            <div className="field">
              <label>YES threshold step (% points)</label>
              <input id="opt_threshold_step_pct" type="number" min={1} max={5} defaultValue={String(optimizerCfg?.threshold_step_pct ?? 1)} />
            </div>
            <div className="field">
              <label>Time step (minutes)</label>
              <input id="opt_minute_step" type="number" min={1} max={5} defaultValue={String(optimizerCfg?.minute_step ?? 1)} />
            </div>
            <div className="field">
              <label>Lab A YES floor (%)</label>
              <input id="opt_lab_a_yes_floor_pct" type="number" min={45} max={95} defaultValue={String(optimizerCfg?.lab_a_yes_floor_pct ?? 57)} />
            </div>
            <div className="field">
              <label>Lab B YES floor (%)</label>
              <input id="opt_lab_b_yes_floor_pct" type="number" min={45} max={95} defaultValue={String(optimizerCfg?.lab_b_yes_floor_pct ?? 55)} />
            </div>
            <div className="field">
              <label>Lab A min minutes-left floor</label>
              <input id="opt_lab_a_min_minutes_left" type="number" min={0} max={30} defaultValue={String(optimizerCfg?.lab_a_min_minutes_left ?? 5)} />
            </div>
            <div className="field">
              <label>Lab B min minutes-left floor</label>
              <input id="opt_lab_b_min_minutes_left" type="number" min={0} max={30} defaultValue={String(optimizerCfg?.lab_b_min_minutes_left ?? 3)} />
            </div>
            <div className="field">
              <label>Lab C YES floor (%)</label>
              <input id="opt_lab_c_yes_floor_pct" type="number" min={45} max={95} defaultValue={String(optimizerCfg?.lab_c_yes_floor_pct ?? 52)} />
            </div>
            <div className="field">
              <label>Lab C min minutes-left floor</label>
              <input id="opt_lab_c_min_minutes_left" type="number" min={0} max={30} defaultValue={String(optimizerCfg?.lab_c_min_minutes_left ?? 3)} />
            </div>
            <div className="field">
              <label>Min settled trades before optimize</label>
              <input id="opt_min_trades_for_optimize" type="number" min={5} max={500} defaultValue={String(optimizerCfg?.min_trades_for_optimize ?? 25)} />
            </div>
            <div className="field">
              <label>Min profitable trades before optimize</label>
              <input id="opt_min_profitable_trades" type="number" min={0} max={200} defaultValue={String(optimizerCfg?.min_profitable_trades ?? 8)} />
            </div>
            <div className="field">
              <label>Regime lookback (hours)</label>
              <input id="opt_regime_lookback_hours" type="number" min={1} max={168} defaultValue={String(optimizerCfg?.regime_lookback_hours ?? 6)} />
            </div>
            <label className="checkbox" style={{ border: "none" }}>
              <input id="opt_optimize_bet_size" type="checkbox" defaultChecked={Boolean(optimizerCfg?.optimize_bet_size ?? true)} disabled={busy} />
              <span>Let optimizer suggest Lab A bet fraction (only lab_a is auto-applied)</span>
            </label>
            <label className="checkbox" style={{ border: "none" }}>
              <input id="opt_include_fees_in_score" type="checkbox" defaultChecked={Boolean(optimizerCfg?.include_fees_in_score ?? true)} disabled={busy} />
              <span>Include fees in adaptive replay score</span>
            </label>
            <label className="checkbox" style={{ border: "none" }}>
              <input id="opt_backtest_proposals" type="checkbox" defaultChecked={Boolean(optimizerCfg?.backtest_proposals ?? true)} disabled={busy} />
              <span>Backtest adaptive rule proposals before applying</span>
            </label>
            <button
              className="primary"
              disabled={busy || optimizerSaving}
              title="Persist optimizer / adaptive tuning fields to the backend."
              onClick={() =>
                void onSaveOptimizerConfig({
                  enabled: Boolean((document.getElementById("opt_enabled") as HTMLInputElement | null)?.checked),
                  adaptive_enabled: Boolean((document.getElementById("opt_adaptive_enabled") as HTMLInputElement | null)?.checked),
                  mode: String((document.getElementById("opt_mode") as HTMLSelectElement | null)?.value || "duel"),
                  lab_a_enabled: Boolean((document.getElementById("opt_lab_a_enabled") as HTMLInputElement | null)?.checked),
                  lab_b_enabled: Boolean((document.getElementById("opt_lab_b_enabled") as HTMLInputElement | null)?.checked),
                  lab_c_enabled: Boolean((document.getElementById("opt_lab_c_enabled") as HTMLInputElement | null)?.checked),
                  lab_a_style: String((document.getElementById("opt_lab_a_style") as HTMLSelectElement | null)?.value || "blend"),
                  lab_b_style: String((document.getElementById("opt_lab_b_style") as HTMLSelectElement | null)?.value || "conservative"),
                  lab_c_style: String((document.getElementById("opt_lab_c_style") as HTMLSelectElement | null)?.value || "aggressive"),
                  loss_streak_trigger: Number((document.getElementById("opt_loss_streak_trigger") as HTMLInputElement | null)?.value || 3),
                  threshold_step_pct: Number((document.getElementById("opt_threshold_step_pct") as HTMLInputElement | null)?.value || 1),
                  minute_step: Number((document.getElementById("opt_minute_step") as HTMLInputElement | null)?.value || 1),
                  lab_a_yes_floor_pct: Number((document.getElementById("opt_lab_a_yes_floor_pct") as HTMLInputElement | null)?.value || 57),
                  lab_b_yes_floor_pct: Number((document.getElementById("opt_lab_b_yes_floor_pct") as HTMLInputElement | null)?.value || 55),
                  lab_a_min_minutes_left: Number((document.getElementById("opt_lab_a_min_minutes_left") as HTMLInputElement | null)?.value || 5),
                  lab_b_min_minutes_left: Number((document.getElementById("opt_lab_b_min_minutes_left") as HTMLInputElement | null)?.value || 3),
                  lab_c_yes_floor_pct: Number((document.getElementById("opt_lab_c_yes_floor_pct") as HTMLInputElement | null)?.value || 52),
                  lab_c_min_minutes_left: Number((document.getElementById("opt_lab_c_min_minutes_left") as HTMLInputElement | null)?.value || 3),
                  min_trades_for_optimize: Number((document.getElementById("opt_min_trades_for_optimize") as HTMLInputElement | null)?.value || 25),
                  min_profitable_trades: Number((document.getElementById("opt_min_profitable_trades") as HTMLInputElement | null)?.value || 8),
                  regime_lookback_hours: Number((document.getElementById("opt_regime_lookback_hours") as HTMLInputElement | null)?.value || 6),
                  optimize_bet_size: Boolean((document.getElementById("opt_optimize_bet_size") as HTMLInputElement | null)?.checked),
                  include_fees_in_score: Boolean((document.getElementById("opt_include_fees_in_score") as HTMLInputElement | null)?.checked),
                  backtest_proposals: Boolean((document.getElementById("opt_backtest_proposals") as HTMLInputElement | null)?.checked),
                })
              }
            >
              Save optimizer settings
            </button>
            <div style={{ marginTop: 12 }}>
              <h3 style={{ margin: "0 0 6px 0", fontSize: 13, color: "var(--text)" }}>Change history</h3>
              {(historyRows || []).slice(0, 12).map((h, i) => (
                <div key={String(h.id || i)} className="sub" style={{ marginTop: 6, fontSize: 12 }}>
                  <strong>{String(h.lab_label || h.branch || "Lab")}</strong> · {String(h.summary || "")}
                  {h.reason ? <div style={{ marginTop: 2 }}>Reason: {String(h.reason)}</div> : null}
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {showData ? (
          <>
        <h2 className="section-tip" style={{ marginTop: 28 }} title="On-disk logs and wiping the local trade database.">
          Data & backups
        </h2>
        <p className="sub" style={{ marginTop: 6, fontSize: 12, lineHeight: 1.45 }} title="Paths from the backend /api/dashboard storage field.">
          <strong>SQLite</strong>:{" "}
          <code style={{ wordBreak: "break-all" }} title="Main bot database.">
            {String(dash?.storage?.sqlite_path ?? "—")}
          </code>
          <br />
          <strong>JSONL logs</strong>:{" "}
          <code style={{ wordBreak: "break-all" }} title="Daily files under streams signals/, trades/, system/.">
            {String(dash?.storage?.data_log_dir ?? "—")}
          </code>
          {dash?.storage?.data_reset_token_configured ? (
            <>
              <br />
              <span className="sub" title="Reset API requires X-Reset-Token header matching .env.">
                <strong>Reset token</strong> is set in <code>.env</code> — enter it below (sent only to your backend) or clear{" "}
                <code>DATA_RESET_TOKEN</code> for open reset.
              </span>
              <div className="field" style={{ marginTop: 10 }}>
                <label htmlFor="reset_token_field" className="section-tip" title="Matches DATA_RESET_TOKEN in backend .env.">
                  Reset token
                </label>
                <input
                  id="reset_token_field"
                  type="password"
                  autoComplete="off"
                  disabled={busy}
                  placeholder="DATA_RESET_TOKEN"
                />
              </div>
            </>
          ) : null}
        </p>
        <label className="checkbox section-tip" style={{ border: "none", marginTop: 8 }} title="Writes backups under data/logs/exports before deleting rows.">
          <input id="reset_backup" type="checkbox" defaultChecked disabled={busy} />
          <span>Before reset: copy SQLite + table JSONL exports</span>
        </label>
        <button
          type="button"
          className="primary"
          style={{ marginTop: 10, borderColor: "#6b2a2a", background: "linear-gradient(180deg,#2a1520,#1a0f18)" }}
          disabled={busy}
          title="Deletes all signals, trades, and equity snapshots on every branch. Keeps bot settings (rules, assets, etc.)."
          onClick={() => {
            const el = document.getElementById("reset_backup") as HTMLInputElement | null;
            const backup = el ? el.checked : true;
            if (
              !window.confirm(
                "Reset ALL branch trading data? This removes every signal, trade, and equity snapshot row from SQLite (live, lab_a, lab_b, lab_c). Bot settings are kept. Prefer per-branch resets on Live / Lab tabs when possible.",
              )
            ) {
              return;
            }
            void onResetTradingData("all", backup);
          }}
        >
          Reset all branches (SQLite)
        </button>
          </>
        ) : null}
      </div>
    </div>
  );
}
