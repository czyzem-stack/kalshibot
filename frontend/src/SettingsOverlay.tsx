// SETTINGS STREAMLINE — cleaned information architecture per user request
// HELP CLEANUP — thorough & professional (tooltips, onboarding copy, Optimizer context).
import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  DevSimHighYesControl,
  EMPTY_RULES_LIST,
  NoBandsSliders,
  NoBetWhenYesBelowControl,
  PaperFeeBpsControl,
  PatientStopLossPanel,
  RuleExperimentHints,
  RulesBandsSliders,
  RulesEditor,
  SwingExitImpliedDropControl,
} from "./settingsRules";
import { KalshiSetupOrbRow } from "./KalshiSetupOrbRow";
import SettingsHelpPlaybook from "./settingsHelpPlaybook";
import { LabHiveChatSettingsPanel, type LabHiveRow } from "./labHiveChat";

type AnyObj = Record<string, any>;
type SettingsTab =
  | "global"
  | "labs"
  | "rules_bands"
  | "patient_stop"
  | "optimizer"
  | "fees_sim"
  | "data"
  | "help";
/** SQLite lab branches A–E (simulation). Breeding is backend-only — no extra UI tabs. */
type LabBranchKey = "a" | "b" | "c" | "d" | "e";

/** Local display for optimizer trace ``at`` ISO timestamps. */
function formatOptimizerTraceAt(iso: string): string {
  const s = String(iso || "").trim();
  if (!s) return "—";
  const ms = Date.parse(s);
  if (!Number.isFinite(ms)) return s;
  return new Date(ms).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function LabSizingInputs({ which, lab, cfg, busy }: { which: LabBranchKey; lab: AnyObj; cfg: AnyObj; busy: boolean }) {
  const p = `lab_${which}`;
  const defFrac =
    which === "a" ? 0.055 : which === "b" ? 0.06 : which === "c" ? 0.1 : which === "d" ? 0.13 : 0.115;
  const defWin = which === "a" ? 15 : which === "b" ? 12 : which === "c" ? 10 : which === "d" ? 10 : 10;
  const labTitle = which === "a" ? "A" : which === "b" ? "B" : which === "c" ? "C" : which === "d" ? "D" : "E";
  return (
    <div>
      <strong style={{ fontSize: 12 }}>Lab {labTitle}</strong>
      <div className="field" style={{ marginTop: 6 }}>
        <label htmlFor={`${p}_paper`}>Paper balance (cents)</label>
        <input
          id={`${p}_paper`}
          type="number"
          defaultValue={String(lab.paper_balance_cents ?? cfg.paper_balance_cents ?? 500000)}
          disabled={busy}
        />
      </div>
      <div className="field">
        <label htmlFor={`${p}_frac`}>Balance fraction per window</label>
        <input id={`${p}_frac`} type="text" defaultValue={String(lab.balance_fraction_per_window ?? defFrac)} disabled={busy} />
      </div>
      <div className="field">
        <label htmlFor={`${p}_win`}>Window (minutes)</label>
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
  onSavePatientStopLossLab,
  showPatientStop = true,
  style,
}: {
  branch: LabBranchKey;
  lab: AnyObj;
  cfg: AnyObj;
  busy: boolean;
  onResetTradingData: (branch: "lab_a" | "lab_b" | "lab_c" | "lab_d" | "lab_e", backup: boolean) => void;
  onSaveLabRules: (rules: AnyObj[]) => void;
  onSaveLabFromSliders: () => void;
  onSavePatientStopLossLab: (patch: AnyObj) => void | Promise<void>;
  showPatientStop?: boolean;
  style?: CSSProperties;
}) {
  const p = `lab_${branch}`;
  const resetKey =
    branch === "a" ? "lab_a" : branch === "b" ? "lab_b" : branch === "c" ? "lab_c" : branch === "d" ? "lab_d" : "lab_e";
  const title =
    branch === "a" ? "Lab A" : branch === "b" ? "Lab B" : branch === "c" ? "Lab C" : branch === "d" ? "Lab D" : "Lab E";
  const resetConfirm =
    branch === "a"
      ? "Reset Lab A data only? Removes SQLite signals, trades, and equity snapshots for Lab A (including legacy sim_lab). Live and other labs are kept."
      : branch === "b"
        ? "Reset Lab B data only? Removes SQLite signals, trades, and equity snapshots for Lab B. Live and other labs are kept."
        : branch === "c"
          ? "Reset Lab C data only? Removes SQLite signals, trades, and equity snapshots for Lab C. Live and other labs are kept."
          : branch === "d"
            ? "Reset Lab D data only? Removes SQLite signals, trades, and equity snapshots for Lab D. Live and other labs are kept."
            : "Reset Lab E data only? Removes SQLite signals, trades, and equity snapshots for Lab E. Live and other labs are kept.";
  return (
    <div
      key={`lab-${branch}-fields-${String(lab.paper_balance_cents ?? "")}-${String(lab.window_minutes ?? "")}-${String(lab.balance_fraction_per_window ?? "")}-${lab.auto_reset_paper_on_tick_failure ? 1 : 0}-${String(lab.enable_patient_stop_loss)}-${String(lab.stop_loss_trigger_pct)}-${String(lab.min_hold_minutes_before_stop)}`}
      className="panel settings-nested-panel"
      style={{ padding: "12px 14px", ...style }}
    >
      <h3 style={{ margin: 0 }}>{title}</h3>
      <p className="sub" style={{ marginTop: 6, marginBottom: 0, fontSize: 11 }}>
        Paper simulation branch. Rules and sizing apply only to this lab; Live is unchanged.
      </p>
      <label className="checkbox" style={{ border: "none", marginTop: 10 }}>
        <input id={`${p}_auto_reset_failure`} type="checkbox" defaultChecked={Boolean(lab.auto_reset_paper_on_tick_failure)} disabled={busy} />
        <span>Auto-reset paper on tick failure</span>
      </label>
      <label className="checkbox" style={{ border: "none", marginTop: 10 }}>
        <input id={`reset_backup_${p}`} type="checkbox" defaultChecked disabled={busy} />
        <span>Backup SQLite + JSONL before reset</span>
      </label>
      <button
        type="button"
        className="primary"
        style={{ marginTop: 8, borderColor: "#6b2a2a", background: "linear-gradient(180deg,#2a1520,#1a0f18)" }}
        disabled={busy}
        onClick={() => {
          const el = document.getElementById(`reset_backup_${p}`) as HTMLInputElement | null;
          const backup = el ? el.checked : true;
          if (!window.confirm(resetConfirm)) return;
          void onResetTradingData(resetKey, backup);
        }}
      >
        Reset {title} trading data
      </button>
      {showPatientStop ? (
        <PatientStopLossPanel
          title={title}
          busy={busy}
          enable={Boolean(lab.enable_patient_stop_loss ?? true)}
          triggerPct={Number(
            lab.stop_loss_trigger_pct ??
              (branch === "a" ? -6 : branch === "b" ? -8 : branch === "c" ? -12 : branch === "d" ? -7 : -7.5),
          )}
          minHold={Number(
            lab.min_hold_minutes_before_stop ??
              (branch === "a" ? 20 : branch === "b" ? 30 : branch === "c" ? 60 : branch === "d" ? 25 : 22),
          )}
          onSave={(patch) => void onSavePatientStopLossLab(patch)}
        />
      ) : null}
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
      <button className="primary" style={{ marginTop: 10 }} disabled={busy} onClick={() => void onSaveLabFromSliders()}>
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
  labD: AnyObj;
  labE: AnyObj;
  busy: boolean;
  onSaveRules: (rules: AnyObj[]) => void | Promise<void>;
  /** Server-side ``RuleCfg`` validation for the JSON rules editor (optional). */
  onValidateRulesJson?: (rules: AnyObj[]) => Promise<{ ok?: boolean; count?: number; detail?: string }>;
  onSaveYesSubtitleFilter: () => void | Promise<void>;
  onSaveExcludeSubtitleFilter: () => void | Promise<void>;
  onSaveSizing: () => void | Promise<void>;
  onSaveLabAFromSliders: () => void | Promise<void>;
  onSaveLabBFromSliders: () => void | Promise<void>;
  onSaveLabCFromSliders: () => void | Promise<void>;
  onSaveLabDFromSliders: () => void | Promise<void>;
  onSaveLabEFromSliders: () => void | Promise<void>;
  onSaveLabARules: (rules: AnyObj[]) => void | Promise<void>;
  onSaveLabBRules: (rules: AnyObj[]) => void | Promise<void>;
  onSaveLabCRules: (rules: AnyObj[]) => void | Promise<void>;
  onSaveLabDRules: (rules: AnyObj[]) => void | Promise<void>;
  onSaveLabERules: (rules: AnyObj[]) => void | Promise<void>;
  onSaveDevSimHighYesPct: (pct: number | null) => void | Promise<void>;
  onSaveNoBetWhenYesBelow: (pct: number | null) => void | Promise<void>;
  onSaveSwingExitImpliedDropPct: (pct: number | null) => void | Promise<void>;
  onSavePatientStopLossLive: (patch: AnyObj) => void | Promise<void>;
  onSavePatientStopLossLab: (lab: LabBranchKey, patch: AnyObj) => void | Promise<void>;
  onSavePaperFees: (patch: AnyObj) => void | Promise<void>;
  optimizerCfg: AnyObj;
  onSaveOptimizerConfig: (patch: AnyObj) => void | Promise<void>;
  optimizerSaving?: boolean;
  /** POST /api/optimizer/run (force); refreshes config when done. */
  onRunOptimizerNow?: () => void | Promise<void>;
  /** POST /api/optimizer/force-internal-mutation (force one internal mutant cycle). */
  onForceInternalMutationNow?: () => void | Promise<void>;
  onResetTradingData: (
    branch: "all" | "all_labs" | "live" | "lab_a" | "lab_b" | "lab_c" | "lab_d" | "lab_e",
    backup: boolean,
    uniformPaperBalanceCents?: number | null,
  ) => void | Promise<void>;
  /** Direct ``PUT /api/config/lab-branches`` (merge + optional branch data reset); independent of optimizer. */
  onApplyLabBranches: (body: AnyObj) => void | Promise<void>;
  /** Paper lab engine toggles + shared bankroll bump (same actions as the former hero rail). */
  liveEngineOn: boolean;
  onToggleLive: () => void | Promise<void>;
  labEngineAOn: boolean;
  labEngineBOn: boolean;
  labEngineCOn: boolean;
  labEngineDOn: boolean;
  labEngineEOn: boolean;
  onToggleLabA: () => void | Promise<void>;
  onToggleLabB: () => void | Promise<void>;
  onToggleLabC: () => void | Promise<void>;
  onToggleLabD: () => void | Promise<void>;
  onToggleLabE: () => void | Promise<void>;
  onAddAllLabsPaper: () => void | Promise<void>;
  onRefresh: () => void | Promise<void>;
  onOpenHistory: () => void | Promise<void>;
  kalshi: AnyObj;
  heroMarqueeSpeedMult: number;
  onHeroMarqueeSpeedMultChange: (mult: number) => void;
  tradePopupToastsEnabled: boolean;
  onTradePopupToastsEnabledChange: (on: boolean) => void;
  labHiveMessages: LabHiveRow[];
  labChatEnabled: boolean;
  onLabChatEnabledChange: (on: boolean) => void;
};

export default function SettingsOverlay({
  open,
  onClose,
  dash,
  cfg,
  labA,
  labB,
  labC,
  labD,
  labE,
  busy,
  onSaveRules,
  onValidateRulesJson,
  onSaveYesSubtitleFilter,
  onSaveExcludeSubtitleFilter,
  onSaveSizing,
  onSaveLabAFromSliders,
  onSaveLabBFromSliders,
  onSaveLabCFromSliders,
  onSaveLabDFromSliders,
  onSaveLabEFromSliders,
  onSaveLabARules,
  onSaveLabBRules,
  onSaveLabCRules,
  onSaveLabDRules,
  onSaveLabERules,
  onSaveDevSimHighYesPct,
  onSaveNoBetWhenYesBelow,
  onSaveSwingExitImpliedDropPct,
  onSavePatientStopLossLive,
  onSavePatientStopLossLab,
  onSavePaperFees,
  optimizerCfg,
  onSaveOptimizerConfig,
  optimizerSaving = false,
  onRunOptimizerNow,
  onForceInternalMutationNow,
  onResetTradingData,
  onApplyLabBranches,
  liveEngineOn,
  onToggleLive,
  labEngineAOn,
  labEngineBOn,
  labEngineCOn,
  labEngineDOn,
  labEngineEOn,
  onToggleLabA,
  onToggleLabB,
  onToggleLabC,
  onToggleLabD,
  onToggleLabE,
  onAddAllLabsPaper,
  onRefresh,
  onOpenHistory,
  kalshi,
  heroMarqueeSpeedMult,
  onHeroMarqueeSpeedMultChange,
  tradePopupToastsEnabled,
  onTradePopupToastsEnabledChange,
  labHiveMessages,
  labChatEnabled,
  onLabChatEnabledChange,
}: SettingsOverlayProps) {
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("global");
  const [activeLab, setActiveLab] = useState<LabBranchKey>("a");
  const [forcingMutation, setForcingMutation] = useState(false);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  useEffect(() => {
    if (open) {
      setSettingsTab("global");
      setActiveLab("a");
    }
  }, [open]);

  const showHelp = settingsTab === "help";
  const showGlobal = settingsTab === "global";
  const showRulesBands = settingsTab === "rules_bands";
  const showPatientStopTab = settingsTab === "patient_stop";
  const showFeesSim = settingsTab === "fees_sim";
  const showLabSizingGrid = settingsTab === "labs" || settingsTab === "optimizer";
  const showLabsBranchPanel = settingsTab === "labs";
  const showCombinedLabReset = showLabSizingGrid;
  const sizingTabs: Array<{ id: LabBranchKey; label: string }> = [
    { id: "a", label: "Lab A" },
    { id: "b", label: "Lab B" },
    { id: "c", label: "Lab C" },
    { id: "d", label: "Lab D" },
    { id: "e", label: "Lab E" },
  ];
  const showOpt = settingsTab === "optimizer";
  const showData = settingsTab === "data";
  const historyRows = useMemo(
    () => (Array.isArray(optimizerCfg?.change_history) ? (optimizerCfg.change_history as AnyObj[]) : []),
    [optimizerCfg?.change_history],
  );
  const optimizerTraceRows = useMemo(() => {
    const src = Array.isArray(optimizerCfg?.internal_optimizer_trace)
      ? (optimizerCfg.internal_optimizer_trace as AnyObj[])
      : [];
    return src.slice(0, 20);
  }, [optimizerCfg?.internal_optimizer_trace]);
  const optimizerTraceChartRows = useMemo(
    () =>
      optimizerTraceRows
        .slice()
        .reverse()
        .map((r, i) => {
          const sc = Number(r?.score_after ?? r?.score ?? r?.score_before);
          return {
            idx: i + 1,
            score: Number.isFinite(sc) ? sc : null,
            accepted: r?.accepted ? 1 : 0,
            rejected: r?.accepted ? 0 : 1,
            at: String(r?.at || ""),
            label: formatOptimizerTraceAt(String(r?.at || "")),
            stopN: Number(r?.stop_loss_exits_n ?? 0) || 0,
            stopRate: Number(r?.stop_loss_trigger_rate_pct ?? 0) || 0,
            stopPnl: Number(r?.total_pnl_from_stops_dollars ?? 0) || 0,
          };
        }),
    [optimizerTraceRows],
  );
  const optimizerTraceStats = useMemo(() => {
    const n = optimizerTraceRows.length;
    if (!n) return { cycles: 0, accepted: 0, rate: 0, lastScore: null as number | null, avgTrend: 0 };
    const accepted = optimizerTraceRows.filter((r) => Boolean(r?.accepted)).length;
    const scores = optimizerTraceRows
      .slice()
      .reverse()
      .map((r) => Number(r?.score_after ?? r?.score ?? r?.score_before))
      .filter((v) => Number.isFinite(v)) as number[];
    const lastScore = scores.length ? scores[scores.length - 1] : null;
    const avgTrend = scores.length >= 2 ? (scores[scores.length - 1] - scores[0]) / Math.max(1, scores.length - 1) : 0;
    return { cycles: n, accepted, rate: (accepted * 100) / n, lastScore, avgTrend };
  }, [optimizerTraceRows]);

  const activeLabObj =
    activeLab === "a" ? labA : activeLab === "b" ? labB : activeLab === "c" ? labC : activeLab === "d" ? labD : labE;
  const saveActiveLabRules =
    activeLab === "a"
      ? onSaveLabARules
      : activeLab === "b"
        ? onSaveLabBRules
        : activeLab === "c"
          ? onSaveLabCRules
          : activeLab === "d"
            ? onSaveLabDRules
            : onSaveLabERules;
  const saveActiveLabSliders =
    activeLab === "a"
      ? onSaveLabAFromSliders
      : activeLab === "b"
        ? onSaveLabBFromSliders
        : activeLab === "c"
          ? onSaveLabCFromSliders
          : activeLab === "d"
            ? onSaveLabDFromSliders
            : onSaveLabEFromSliders;

  if (!open) return null;

  return (
    <div className="settings-overlay-root" role="dialog" aria-modal="true" aria-labelledby="settings-overlay-title">
      <div className="settings-overlay-backdrop" onClick={onClose} aria-hidden="true" />
      <div className="settings-overlay-panel">
        <div className="settings-overlay-header">
          <h2 id="settings-overlay-title" style={{ margin: 0 }}>
            Settings
          </h2>
          <button type="button" className="settings-overlay-close" onClick={onClose} aria-label="Close settings">
            ✕
          </button>
        </div>
        <div className="chart-tabs settings-overlay-tabs" role="tablist" aria-label="Settings sections" style={{ marginTop: 12, flexWrap: "wrap", gap: 6 }}>
          {(
            [
              ["global", "Global / Live"],
              ["labs", "Simulation labs"],
              ["rules_bands", "Rules & bands"],
              ["patient_stop", "Patient stop-loss"],
              ["optimizer", "Optimizer"],
              ["fees_sim", "Fees & sim"],
              ["data", "Data & backups"],
              ["help", "Help & first-time guide"],
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
        {showHelp ? (
          <SettingsHelpPlaybook
            goGlobal={() => setSettingsTab("global")}
            goLabs={(lab) => {
              setSettingsTab("labs");
              setActiveLab(lab);
            }}
            goRules={() => setSettingsTab("rules_bands")}
            goPatientStop={() => setSettingsTab("patient_stop")}
            goOptimizer={() => setSettingsTab("optimizer")}
            goFeesSim={() => setSettingsTab("fees_sim")}
            goData={() => setSettingsTab("data")}
          />
        ) : (
          <>
        <div style={{ marginTop: 10 }}>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
            <strong style={{ fontSize: 11, letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--muted)" }}>
              Kalshi & connection
            </strong>
          </div>
          <div style={{ marginTop: 8, overflowX: "auto" }}>
            <KalshiSetupOrbRow dash={dash} cfg={cfg} />
          </div>
        </div>
        <div className="settings-lab-engines-panel" style={{ marginTop: 12 }}>
          <div className="settings-lab-engines-panel__title-row">
            <strong style={{ fontSize: 11, letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--muted)" }}>
              Engines
            </strong>
          </div>
          <div className="settings-lab-engine-status" aria-label="Engine running state">
            <span className={`pill ${liveEngineOn ? "pill--engine-on" : "pill--engine-off"}`}>
              Live · <strong>{liveEngineOn ? "Active" : "Stopped"}</strong>
            </span>
            <span className={`pill ${labEngineAOn ? "pill--engine-on" : "pill--engine-off"}`}>
              Lab A · <strong>{labEngineAOn ? "Active" : "Stopped"}</strong>
            </span>
            <span className={`pill ${labEngineBOn ? "pill--engine-on" : "pill--engine-off"}`}>
              Lab B · <strong>{labEngineBOn ? "Active" : "Stopped"}</strong>
            </span>
            <span className={`pill ${labEngineCOn ? "pill--engine-on" : "pill--engine-off"}`}>
              Lab C · <strong>{labEngineCOn ? "Active" : "Stopped"}</strong>
            </span>
            <span className={`pill ${labEngineDOn ? "pill--engine-on" : "pill--engine-off"}`}>
              Lab D · <strong>{labEngineDOn ? "Active" : "Stopped"}</strong>
            </span>
            <span className={`pill ${labEngineEOn ? "pill--engine-on" : "pill--engine-off"}`}>
              Lab E · <strong>{labEngineEOn ? "Active" : "Stopped"}</strong>
            </span>
          </div>
          <div className="settings-lab-engine-actions">
            <button
              type="button"
              className="primary"
              disabled={busy}
              title="Pull the latest dashboard payload now (dashboard also refreshes on its own)."
              onClick={() => void onRefresh()}
            >
              Refresh now
            </button>
            <button
              type="button"
              disabled={busy}
              title="Open history: browse stored rows and export CSV where supported."
              onClick={() => void onOpenHistory()}
            >
              History
            </button>
            <button type="button" className="primary" disabled={busy} title="Start or stop the Live trading loop (paper or real per config)." onClick={() => void onToggleLive()}>
              Turn Live {liveEngineOn ? "off" : "on"}
            </button>
            <button
              type="button"
              className="primary"
              disabled={busy}
              title="Lab A: paper simulation engine."
              onClick={() => void onToggleLabA()}
            >
              Turn A {labEngineAOn ? "off" : "on"}
            </button>
            <button type="button" className="primary" disabled={busy} title="Lab B: paper simulation." onClick={() => void onToggleLabB()}>
              Turn B {labEngineBOn ? "off" : "on"}
            </button>
            <button type="button" className="primary" disabled={busy} title="Lab C: paper simulation." onClick={() => void onToggleLabC()}>
              Turn C {labEngineCOn ? "off" : "on"}
            </button>
            <button type="button" className="primary" disabled={busy} title="Lab D: paper simulation." onClick={() => void onToggleLabD()}>
              Turn D {labEngineDOn ? "off" : "on"}
            </button>
            <button type="button" className="primary" disabled={busy} title="Lab E: paper simulation." onClick={() => void onToggleLabE()}>
              Turn E {labEngineEOn ? "off" : "on"}
            </button>
            <button
              type="button"
              disabled={busy}
              title="Add $100 to each lab's paper balance and lifetime basis (when set); trades and rules unchanged."
              onClick={() => void onAddAllLabsPaper()}
            >
              All +$100
            </button>
          </div>
          <div className="hero-meta" style={{ marginTop: 10 }} title="Kalshi REST target and environment come from the backend .env.">
            <span className="env-pill" title="REST base URL the backend uses (demo vs production).">
              API: <code>{kalshi?.api_base ? String(kalshi.api_base).replace("https://", "") : "—"}</code>
            </span>
            <span className="env-pill" title="KALSHI_ENV value (e.g. demo vs production).">
              Environment: <code>{String(kalshi?.env || "—")}</code>
            </span>
            <a
              className="muted-link"
              href="https://docs.kalshi.com/getting_started/api_keys"
              target="_blank"
              rel="noreferrer"
              title="Official Kalshi documentation for API keys."
            >
              Kalshi API keys (docs)
            </a>
          </div>
          <div
            className="panel settings-nested-panel section-tip"
            style={{ marginTop: 12, marginBottom: 0, padding: "12px 14px" }}
            title="Browser-only (localStorage): header ticker speed, trade toasts, and agent chatter visibility."
          >
            <h3 style={{ margin: 0, fontSize: 12, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--muted)" }}>
              Hero ticker & balance tile
            </h3>
            <p className="sub" style={{ marginTop: 6, marginBottom: 10, fontSize: 12, lineHeight: 1.45 }}>
              Adjust marquee speed. The hero column shows a six-row snapshot (Live + Labs A–E: balance and return). Preferences stay in this browser only.
            </p>
            <div className="field" style={{ marginBottom: 0 }} title="Scroll speed multiplier for the combined branch ticker (drag and momentum still apply).">
              <label htmlFor="hero_marquee_speed_mult">
                Marquee scroll speed: <strong>{heroMarqueeSpeedMult.toFixed(2)}×</strong>
              </label>
              <input
                id="hero_marquee_speed_mult"
                type="range"
                min="0.35"
                max="4"
                step="0.05"
                value={heroMarqueeSpeedMult}
                onChange={(e) => onHeroMarqueeSpeedMultChange(Number(e.target.value))}
              />
            </div>
            <div
              className="field"
              style={{ marginTop: 14, marginBottom: 0 }}
              title="Show trade open/close toasts in the bottom-right stack (Live or sim). When off, trade cards are hidden; optimizer and other notices can still appear. Cards auto-dismiss after a short delay. Browser-only."
            >
              <label className="section-tip" style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={tradePopupToastsEnabled}
                  onChange={(e) => onTradePopupToastsEnabledChange(e.target.checked)}
                />
                <span>
                  Trade open / settle toasts <span className="sub">(bottom-right; optimizer notices may share this stack)</span>
                </span>
              </label>
            </div>
            <div style={{ marginTop: 14 }}>
              <LabHiveChatSettingsPanel
                messages={labHiveMessages}
                enabled={labChatEnabled}
                onToggleEnabled={onLabChatEnabledChange}
              />
            </div>
          </div>
        </div>
        {showGlobal ? (
          <>
        <h2 style={{ marginTop: 12 }}>Filters</h2>
        <div className="field" key={`ysf-${String(cfg.only_yes_subtitle_contains ?? "")}`}>
          <label
            htmlFor="yes_sub_filter"
            className="section-tip"
            title="Optional. Substring match on market subtitle to bias Up vs Down; leave blank for both."
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
            title="Comma-separated substrings (case-insensitive). Matching markets are skipped for trading, not just hidden in the UI. Leave empty unless you need to filter noisy subtitles."
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

        <h2 style={{ marginTop: 16 }}>Live sizing</h2>
        <div className="row" style={{ marginTop: 10 }}>
          <span className="pill">
            fraction <strong>{String(cfg.balance_fraction_per_window ?? "")}</strong>
          </span>
          <span className="pill">
            window <strong>{String(cfg.window_minutes ?? "")}m</strong>
          </span>
          <span className="pill">
            poll <strong>{String(cfg.poll_seconds ?? "")}s</strong>
          </span>
        </div>

        <div
          key={`sizing-${String(cfg.balance_fraction_per_window)}-${String(cfg.window_minutes)}-${String(cfg.poll_seconds)}-${String(cfg.paper_balance_cents)}`}
        >
          <div className="field">
            <label htmlFor="frac">Balance fraction per trade</label>
            <input id="frac" type="text" defaultValue={String(cfg.balance_fraction_per_window ?? 0.03)} />
          </div>
          <div className="field">
            <label htmlFor="winmin">Window length (minutes)</label>
            <input id="winmin" type="number" defaultValue={String(cfg.window_minutes ?? 15)} />
          </div>
          <div className="field">
            <label htmlFor="poll">Poll seconds (2–120)</label>
            <input id="poll" type="number" defaultValue={String(cfg.poll_seconds ?? 8)} />
          </div>
          <div className="field">
            <label htmlFor="paper">Paper balance (cents)</label>
            <input id="paper" type="number" defaultValue={String(cfg.paper_balance_cents ?? 500000)} />
          </div>
          <button className="primary" disabled={busy} onClick={() => void onSaveSizing()}>
            Save sizing
          </button>
        </div>

        <div className="panel settings-nested-panel" style={{ marginTop: 16, padding: "12px 14px" }}>
          <h3 style={{ margin: 0 }}>Live branch data</h3>
          <p className="sub" style={{ marginTop: 8, fontSize: 12, lineHeight: 1.45 }}>
            Removes signals, trades, and equity snapshots for <code>live</code> only. With real-money enabled, you must confirm with <code>RESET_LIVE</code>.
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
            title="Delete Live-branch signals, trades, and equity snapshots in SQLite (labs unchanged)."
            onClick={() => {
              const el = document.getElementById("reset_backup_live") as HTMLInputElement | null;
              const backup = el ? el.checked : true;
              const sim = Boolean(cfg.simulate);
              if (
                !window.confirm(
                  sim
                    ? "Reset Live branch data only? This removes SQLite signals, trades, and equity snapshots for branch=live. Lab A/B/C rows are kept."
                    : "WARNING — Live is in Real $ mode.\n\nReset Live branch SQLite data only (signals, trades, equity snapshots where branch=live)? This does not cancel resting Kalshi orders by itself. Lab A/B/C rows are kept.\n\nIf you continue, you will be asked to type RESET_LIVE.",
                )
              ) {
                return;
              }
              if (!sim) {
                const ack = String(
                  window.prompt('Type RESET_LIVE exactly to confirm clearing Live SQLite history while in "Real $" mode.', "") ||
                    "",
                ).trim();
                if (ack !== "RESET_LIVE") {
                  window.alert("Live reset cancelled.");
                  return;
                }
              }
              void onResetTradingData("live", backup);
            }}
          >
            Reset Live branch data (SQLite)
          </button>
        </div>

        <details style={{ marginTop: 12 }}>
          <summary className="sub" style={{ cursor: "pointer" }}>
            Rules JSON
          </summary>
          <RulesEditor
            rules={cfg.rules ?? EMPTY_RULES_LIST}
            disabled={busy}
            onSave={(r) => void onSaveRules(r)}
            onServerValidate={onValidateRulesJson}
          />
        </details>
          </>
        ) : null}

        {showRulesBands ? (
          <>
            <h2 style={{ marginTop: 20 }}>Rules & bands (defaults)</h2>
            <RuleExperimentHints dash={dash} busy={busy} onApply={(r) => void onSaveRules(r)} />
            <RulesBandsSliders rules={cfg.rules ?? EMPTY_RULES_LIST} disabled={busy} onSave={(r) => void onSaveRules(r)} />
            <NoBandsSliders rules={cfg.rules ?? EMPTY_RULES_LIST} disabled={busy} onSave={(r) => void onSaveRules(r)} />
            <NoBetWhenYesBelowControl cfg={cfg} busy={busy} onSave={(v) => void onSaveNoBetWhenYesBelow(v)} />
            <DevSimHighYesControl cfg={cfg} busy={busy} onSave={(v) => void onSaveDevSimHighYesPct(v)} />
          </>
        ) : null}

        {showPatientStopTab ? (
          <>
            <h2 style={{ marginTop: 20 }}>Patient stop-loss</h2>
            <PatientStopLossPanel
              title="Live (paper sim)"
              busy={busy}
              enable={Boolean(cfg.enable_patient_stop_loss ?? true)}
              triggerPct={Number(cfg.stop_loss_trigger_pct ?? -10)}
              minHold={Number(cfg.min_hold_minutes_before_stop ?? 45)}
              onSave={(patch) => void onSavePatientStopLossLive(patch)}
            />
            <PatientStopLossPanel
              title="Lab A — staging / adoption (paper sim)"
              busy={busy}
              enable={Boolean(labA.enable_patient_stop_loss ?? true)}
              triggerPct={Number(labA.stop_loss_trigger_pct ?? -6)}
              minHold={Number(labA.min_hold_minutes_before_stop ?? 20)}
              onSave={(patch) => void onSavePatientStopLossLab("a", patch)}
            />
            <PatientStopLossPanel
              title="Lab B (paper sim)"
              busy={busy}
              enable={Boolean(labB.enable_patient_stop_loss ?? true)}
              triggerPct={Number(labB.stop_loss_trigger_pct ?? -8)}
              minHold={Number(labB.min_hold_minutes_before_stop ?? 30)}
              onSave={(patch) => void onSavePatientStopLossLab("b", patch)}
            />
            <PatientStopLossPanel
              title="Lab C (paper sim)"
              busy={busy}
              enable={Boolean(labC.enable_patient_stop_loss ?? true)}
              triggerPct={Number(labC.stop_loss_trigger_pct ?? -12)}
              minHold={Number(labC.min_hold_minutes_before_stop ?? 60)}
              onSave={(patch) => void onSavePatientStopLossLab("c", patch)}
            />
            <PatientStopLossPanel
              title="Lab D (paper sim)"
              busy={busy}
              enable={Boolean(labD.enable_patient_stop_loss ?? true)}
              triggerPct={Number(labD.stop_loss_trigger_pct ?? -7)}
              minHold={Number(labD.min_hold_minutes_before_stop ?? 25)}
              onSave={(patch) => void onSavePatientStopLossLab("d", patch)}
            />
            <PatientStopLossPanel
              title="Lab E (paper sim)"
              busy={busy}
              enable={Boolean(labE.enable_patient_stop_loss ?? true)}
              triggerPct={Number(labE.stop_loss_trigger_pct ?? -8)}
              minHold={Number(labE.min_hold_minutes_before_stop ?? 22)}
              onSave={(patch) => void onSavePatientStopLossLab("e", patch)}
            />
          </>
        ) : null}

        {showFeesSim ? (
          <>
            <h2 style={{ marginTop: 20 }}>Fees & simulation</h2>
            <SwingExitImpliedDropControl cfg={cfg} busy={busy} onSave={(v) => void onSaveSwingExitImpliedDropPct(v)} />
            <PaperFeeBpsControl cfg={cfg} busy={busy} onSave={(patch) => void onSavePaperFees(patch)} />
          </>
        ) : null}

        {showLabSizingGrid ? (
          <div
            key={`lab-sizing-${String(labA.paper_balance_cents ?? "")}-${String(labB.paper_balance_cents ?? "")}-${String(labC.paper_balance_cents ?? "")}-${String(labD.paper_balance_cents ?? "")}-${String(labE.paper_balance_cents ?? "")}-${String(labA.balance_fraction_per_window ?? "")}-${String(labB.balance_fraction_per_window ?? "")}-${String(labC.balance_fraction_per_window ?? "")}-${String(labD.balance_fraction_per_window ?? "")}-${String(labE.balance_fraction_per_window ?? "")}`}
            className="panel settings-nested-panel"
            style={{ marginTop: showGlobal ? 20 : 12, padding: "12px 14px" }}
          >
            <h2 style={{ marginTop: 0 }}>Simulation labs</h2>
            <p className="sub" style={{ marginTop: 6, fontSize: 12, lineHeight: 1.45 }}>
              Five independent paper branches (A–E). Sizing and rules are per lab; use <strong>Save all labs</strong> or per-lab saves. The <strong>Reset Live + all labs</strong> panel below wipes <strong>Live + A–E</strong> sim history in SQLite; per-lab saves alone do not delete history.
            </p>
            <div
              className="panel settings-nested-panel"
              style={{
                marginTop: 12,
                padding: "12px 14px",
                border: "1px solid rgba(180, 83, 120, 0.45)",
                background: "rgba(24, 12, 20, 0.35)",
              }}
            >
              <h3 className="section-tip" style={{ margin: "0 0 6px 0", fontSize: 13 }} title="POST /api/data/reset?branch=all_labs (Live + labs A–E)">
                Reset Live + all labs (A–E) + paper balance
              </h3>
              <p className="sub" style={{ margin: "0 0 10px 0", fontSize: 12, lineHeight: 1.45 }}>
                Wipes <strong>Live + Lab A–E</strong> signals, trades, and equity snapshots in SQLite (and clears in-memory engine dedupe for those branches). If you set a cent amount below, the API also sets that same{" "}
                <code>paper_balance_cents</code> on <strong>Live paper</strong> and <strong>every lab key in config</strong> (including breeding child slots) and clears per-lab lifetime basis fields so charts start from the new seed.
              </p>
              {dash?.storage?.data_reset_token_configured ? (
                <div className="field" style={{ marginBottom: 10 }}>
                  <label htmlFor="reset_token_labs_bulk" className="section-tip" title="Same as Data tab — required when DATA_RESET_TOKEN is set.">
                    Reset token
                  </label>
                  <input id="reset_token_labs_bulk" type="password" autoComplete="off" disabled={busy} placeholder="DATA_RESET_TOKEN" />
                </div>
              ) : null}
              <div className="field">
                <label htmlFor="all_labs_uniform_reset_cents" className="section-tip" title="Applied after the wipe via bot_config (same as Data → Reset all branches optional field).">
                  Same starting paper balance after reset (cents)
                </label>
                <input
                  id="all_labs_uniform_reset_cents"
                  type="number"
                  min={0}
                  max={100_000_000}
                  step={1000}
                  disabled={busy}
                  defaultValue={String(Number(labA?.paper_balance_cents ?? cfg?.paper_balance_cents ?? 500_000))}
                />
                <div className="sub" style={{ marginTop: 4, fontSize: 11, opacity: 0.88 }}>
                  Example: <code>10000</code> = $100.00 each where applied. Clear the field to wipe history without changing bankroll fields in config.
                </div>
              </div>
              <label className="checkbox section-tip" style={{ border: "none", marginBottom: 10 }}>
                <input id="all_labs_reset_backup" type="checkbox" defaultChecked disabled={busy} />
                <span>SQLite + JSONL backup before wipe (first lab owns the backup when all_labs)</span>
              </label>
              <button
                type="button"
                className="primary"
                style={{ borderColor: "#6b2a2a", background: "linear-gradient(180deg,#2a1520,#1a0f18)" }}
                disabled={busy}
                title="POST /api/data/reset?branch=all_labs&confirm=yes"
                onClick={() => {
                  const backupEl = document.getElementById("all_labs_reset_backup") as HTMLInputElement | null;
                  const backup = backupEl ? backupEl.checked : true;
                  const balEl = document.getElementById("all_labs_uniform_reset_cents") as HTMLInputElement | null;
                  const rawBal = balEl?.value?.trim() ?? "";
                  let uniformCents: number | null = null;
                  if (rawBal !== "") {
                    const n = Number(rawBal.replace(/,/g, ""));
                    if (!Number.isFinite(n) || n < 0 || n > 100_000_000) {
                      window.alert("Paper balance must be a number between 0 and 100000000 cents, or leave blank to skip bankroll changes.");
                      return;
                    }
                    uniformCents = Math.round(n);
                  }
                  const balHint =
                    uniformCents != null
                      ? `Then Live + all lab config slots will be set to ${uniformCents} cents paper (and lifetime bases cleared).`
                      : "Config bankroll fields are left unchanged (only Live + lab SQLite trading rows are deleted).";
                  if (
                    !window.confirm(
                      `Reset Live + Lab A–E trading data (SQLite signals/trades/equity for each)? This cannot be undone. ${balHint}`,
                    )
                  ) {
                    return;
                  }
                  void onResetTradingData("all_labs", backup, uniformCents);
                }}
              >
                Reset Live + labs (A–E)
              </button>
            </div>
            <div className="chart-tabs" role="tablist" aria-label="Simulation labs A through E" style={{ marginTop: 12 }}>
              {sizingTabs.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  aria-selected={activeLab === t.id}
                  className={`chart-tab ${activeLab === t.id ? "chart-tab--active" : ""}`}
                  onClick={() => setActiveLab(t.id)}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div className="row" style={{ marginTop: 12 }}>
              {activeLab === "a" ? <LabSizingInputs which="a" lab={labA} cfg={cfg} busy={busy} /> : null}
              {activeLab === "b" ? <LabSizingInputs which="b" lab={labB} cfg={cfg} busy={busy} /> : null}
              {activeLab === "c" ? <LabSizingInputs which="c" lab={labC} cfg={cfg} busy={busy} /> : null}
              {activeLab === "d" ? <LabSizingInputs which="d" lab={labD} cfg={cfg} busy={busy} /> : null}
              {activeLab === "e" ? <LabSizingInputs which="e" lab={labE} cfg={cfg} busy={busy} /> : null}
            </div>
            {showCombinedLabReset ? (
              <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
                <h3 className="section-tip" style={{ margin: "0 0 6px 0", fontSize: 13 }} title="Optionally wipe selected lab SQLite data, then apply the sizing row in one request.">
                  Reset lab data + apply sizing (A–E)
                </h3>
                <p className="sub" style={{ marginBottom: 10, fontSize: 12, lineHeight: 1.45 }}>
                  Combines optional branch reset with the bankroll fields above—same scope as per-lab resets, fewer clicks.
                </p>
                <div className="field">
                  <label htmlFor="bulk_lab_reset" className="section-tip" title="If not &quot;No reset&quot;, wipe runs before lab_* fields are written.">
                    Reset lab trading data first
                  </label>
                  <select id="bulk_lab_reset" defaultValue="none" disabled={busy}>
                    <option value="none">No reset (config only)</option>
                    <option value="lab_a">Lab A only</option>
                    <option value="lab_b">Lab B only</option>
                    <option value="lab_c">Lab C only</option>
                    <option value="lab_d">Lab D only</option>
                    <option value="lab_e">Lab E only</option>
                    <option value="both">Lab A + Lab B</option>
                    <option value="all_labs">Lab A + B + C + D + E</option>
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
                  title="PUT /api/config/lab-branches: persist bankroll and sizing from this row (no wipe unless selected above)."
                  onClick={() => {
                    const parseC = (id: string, fallback: number) => {
                      const el = document.getElementById(id) as HTMLInputElement | null;
                      if (!el) return fallback;
                      const raw = String(el.value ?? "").replace(/,/g, "").trim();
                      if (!raw) return fallback;
                      return Math.round(Number(raw));
                    };
                    const parseF = (id: string, fallback: number) => {
                      const el = document.getElementById(id) as HTMLInputElement | null;
                      if (!el) return fallback;
                      const raw = String(el.value ?? "").replace(/,/g, "").trim();
                      if (!raw) return fallback;
                      return Number(raw);
                    };
                    const readBool = (id: string, fallback: boolean) => {
                      const el = document.getElementById(id) as HTMLInputElement | null;
                      return el ? Boolean(el.checked) : fallback;
                    };
                    const resetVal = String((document.getElementById("bulk_lab_reset") as HTMLSelectElement | null)?.value || "none");
                    const backupEl = document.getElementById("bulk_lab_backup") as HTMLInputElement | null;
                    const backup = backupEl ? backupEl.checked : true;
                    const laPaper = parseC("lab_a_paper", Number(labA?.paper_balance_cents ?? cfg?.paper_balance_cents ?? 500000));
                    const laFrac = parseF("lab_a_frac", Number(labA?.balance_fraction_per_window ?? 0.055));
                    const laWin = parseC("lab_a_win", Number(labA?.window_minutes ?? 15));
                    const lbPaper = parseC("lab_b_paper", Number(labB?.paper_balance_cents ?? cfg?.paper_balance_cents ?? 500000));
                    const lbFrac = parseF("lab_b_frac", Number(labB?.balance_fraction_per_window ?? 0.06));
                    const lbWin = parseC("lab_b_win", Number(labB?.window_minutes ?? 12));
                    const lcPaper = parseC("lab_c_paper", Number(labC?.paper_balance_cents ?? cfg?.paper_balance_cents ?? 500000));
                    const lcFrac = parseF("lab_c_frac", Number(labC?.balance_fraction_per_window ?? 0.1));
                    const lcWin = parseC("lab_c_win", Number(labC?.window_minutes ?? 10));
                    const ldPaper = parseC("lab_d_paper", Number(labD?.paper_balance_cents ?? cfg?.paper_balance_cents ?? 500000));
                    const ldFrac = parseF("lab_d_frac", Number(labD?.balance_fraction_per_window ?? 0.13));
                    const ldWin = parseC("lab_d_win", Number(labD?.window_minutes ?? 10));
                    const lePaper = parseC("lab_e_paper", Number(labE?.paper_balance_cents ?? cfg?.paper_balance_cents ?? 500000));
                    const leFrac = parseF("lab_e_frac", Number(labE?.balance_fraction_per_window ?? 0.115));
                    const leWin = parseC("lab_e_win", Number(labE?.window_minutes ?? 10));
                    // If a checkbox isn't rendered in this tab, keep current backend value instead of forcing false.
                    const laAutoReset = readBool("lab_a_auto_reset_failure", Boolean(labA?.auto_reset_paper_on_tick_failure));
                    const lbAutoReset = readBool("lab_b_auto_reset_failure", Boolean(labB?.auto_reset_paper_on_tick_failure));
                    const lcAutoReset = readBool("lab_c_auto_reset_failure", Boolean(labC?.auto_reset_paper_on_tick_failure));
                    const ldAutoReset = readBool("lab_d_auto_reset_failure", Boolean(labD?.auto_reset_paper_on_tick_failure));
                    const leAutoReset = readBool("lab_e_auto_reset_failure", Boolean(labE?.auto_reset_paper_on_tick_failure));
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
                    if (!Number.isFinite(ldFrac) || ldFrac < 0.0001 || ldFrac > 1) {
                      window.alert("Lab D balance fraction must be between 0.0001 and 1.");
                      return;
                    }
                    if (!Number.isFinite(leFrac) || leFrac < 0.0001 || leFrac > 1) {
                      window.alert("Lab E balance fraction must be between 0.0001 and 1.");
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
                    if (!Number.isFinite(ldWin) || ldWin < 1 || ldWin > 1440 || !Number.isInteger(ldWin)) {
                      window.alert("Lab D window must be an integer 1–1440 minutes.");
                      return;
                    }
                    if (!Number.isFinite(leWin) || leWin < 1 || leWin > 1440 || !Number.isInteger(leWin)) {
                      window.alert("Lab E window must be an integer 1–1440 minutes.");
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
                    if (!Number.isFinite(ldPaper) || ldPaper < 0 || !Number.isInteger(ldPaper)) {
                      window.alert("Lab D paper balance must be a non-negative integer (cents).");
                      return;
                    }
                    if (!Number.isFinite(lePaper) || lePaper < 0 || !Number.isInteger(lePaper)) {
                      window.alert("Lab E paper balance must be a non-negative integer (cents).");
                      return;
                    }
                    if (resetVal !== "none") {
                      const scope =
                        resetVal === "both"
                          ? "Lab A and Lab B"
                          : resetVal === "all_labs"
                            ? "Lab A, Lab B, Lab C, Lab D, and Lab E"
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
                        auto_reset_paper_on_tick_failure: laAutoReset,
                      },
                      lab_b: {
                        paper_balance_cents: lbPaper,
                        balance_fraction_per_window: lbFrac,
                        window_minutes: lbWin,
                        auto_reset_paper_on_tick_failure: lbAutoReset,
                      },
                      lab_c: {
                        paper_balance_cents: lcPaper,
                        balance_fraction_per_window: lcFrac,
                        window_minutes: lcWin,
                        auto_reset_paper_on_tick_failure: lcAutoReset,
                      },
                      lab_d: {
                        paper_balance_cents: ldPaper,
                        balance_fraction_per_window: ldFrac,
                        window_minutes: ldWin,
                        auto_reset_paper_on_tick_failure: ldAutoReset,
                      },
                      lab_e: {
                        paper_balance_cents: lePaper,
                        balance_fraction_per_window: leFrac,
                        window_minutes: leWin,
                        auto_reset_paper_on_tick_failure: leAutoReset,
                      },
                    });
                  }}
                >
                  Save all labs (no reset if "No reset" selected)
                </button>
              </div>
            ) : null}
          </div>
        ) : null}

        {showLabsBranchPanel ? (
          <LabBranchPanel
            branch={activeLab}
            lab={activeLabObj}
            cfg={cfg}
            busy={busy}
            onResetTradingData={onResetTradingData}
            onSaveLabRules={saveActiveLabRules}
            onSaveLabFromSliders={saveActiveLabSliders}
            showPatientStop={false}
            onSavePatientStopLossLab={(patch) => void onSavePatientStopLossLab(activeLab, patch)}
            style={{ marginTop: showLabSizingGrid ? 12 : 20 }}
          />
        ) : null}

        {showOpt ? (
          <div className="panel settings-nested-panel" style={{ marginTop: 16, padding: "12px 14px" }}>
            <h2 style={{ marginTop: 0 }}>Optimizer</h2>
            <p className="sub" style={{ marginTop: 6, fontSize: 12, lineHeight: 1.45 }}>
              Choose <strong>duel</strong> or <strong>independent</strong> context; adaptive pulses apply to <strong>Lab A</strong>. Sizing lives under <strong>Simulation labs</strong> (also available when
              this tab is open). Advanced diagnostics (traces, internal logs) are available via <code>GET /api/optimizer/status</code>.
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
            <div className="field">
              <label>Scheduled run interval (minutes)</label>
              <input
                id="opt_interval_minutes"
                type="number"
                min={5}
                max={1440}
                defaultValue={String(optimizerCfg?.interval_minutes ?? 20)}
              />
            </div>
            <div className="field">
              <label>Optimizer data lookback (hours)</label>
              <input
                id="opt_lookback_hours"
                type="number"
                min={1}
                max={720}
                defaultValue={String(optimizerCfg?.lookback_hours ?? 48)}
              />
            </div>
            <label className="checkbox" style={{ border: "none" }}>
              <input id="opt_adaptive_enabled" type="checkbox" defaultChecked={Boolean(optimizerCfg?.adaptive_enabled ?? true)} disabled={busy} />
              <span>Enable adaptive threshold/time auto-correction</span>
            </label>
            <div className="sub" style={{ margin: "-4px 0 8px 26px", fontSize: 11, lineHeight: 1.45, color: "var(--muted)" }}>
              Internal pulse (loss-streak tighten, optional win-path easing, Lab A bet fraction) follows the optimizer interval even when scheduled full runs are off.
            </div>
            <label className="checkbox" style={{ border: "none" }}>
              <input id="opt_lab_a_enabled" type="checkbox" defaultChecked={Boolean(optimizerCfg?.lab_a_enabled ?? true)} disabled={busy} />
              <span>Lab A (adaptive + bet pulse applies here)</span>
            </label>
            <label className="checkbox" style={{ border: "none" }}>
              <input id="opt_lab_b_enabled" type="checkbox" defaultChecked={Boolean(optimizerCfg?.lab_b_enabled ?? true)} disabled={busy} />
              <span>Include Lab B in optimizer context</span>
            </label>
            <label className="checkbox" style={{ border: "none" }}>
              <input id="opt_lab_c_enabled" type="checkbox" defaultChecked={Boolean(optimizerCfg?.lab_c_enabled ?? true)} disabled={busy} />
              <span>Include Lab C in optimizer context</span>
            </label>
            <label className="checkbox" style={{ border: "none" }}>
              <input id="opt_lab_d_enabled" type="checkbox" defaultChecked={Boolean(optimizerCfg?.lab_d_enabled ?? true)} disabled={busy} />
              <span>Include Lab D in optimizer context</span>
            </label>
            <label className="checkbox" style={{ border: "none" }}>
              <input id="opt_lab_e_enabled" type="checkbox" defaultChecked={Boolean(optimizerCfg?.lab_e_enabled ?? true)} disabled={busy} />
              <span>Include Lab E in optimizer context</span>
            </label>
            <div className="field">
              <label>Lab A style</label>
              <select id="opt_lab_a_style" defaultValue={String(optimizerCfg?.lab_a_style || "blend")}>
                <option value="blend">Blend</option>
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
                <option value="wild">Wild</option>
              </select>
            </div>
            <div className="field">
              <label>Lab D style</label>
              <select id="opt_lab_d_style" defaultValue={String(optimizerCfg?.lab_d_style || "wild")}>
                <option value="wild">Wild</option>
                <option value="aggressive">Aggressive</option>
                <option value="conservative">Conservative</option>
                <option value="blend">Blend</option>
              </select>
            </div>
            <div className="field">
              <label>Lab E style</label>
              <select id="opt_lab_e_style" defaultValue={String(optimizerCfg?.lab_e_style || "balanced")}>
                <option value="balanced">Balanced</option>
                <option value="blend">Blend</option>
                <option value="conservative">Conservative</option>
                <option value="aggressive">Aggressive</option>
                <option value="wild">Wild</option>
              </select>
            </div>
            <div className="field">
              <label>Losses at/above YES floor before adaptive adjustment</label>
              <input id="opt_loss_streak_trigger" type="number" min={1} max={12} defaultValue={String(optimizerCfg?.loss_streak_trigger ?? 1)} />
            </div>
            <div className="field">
              <label>YES threshold step (% points)</label>
              <input id="opt_threshold_step_pct" type="number" min={1} max={5} defaultValue={String(optimizerCfg?.threshold_step_pct ?? 2)} />
            </div>
            <div className="field">
              <label>Time step (minutes)</label>
              <input id="opt_minute_step" type="number" min={1} max={5} defaultValue={String(optimizerCfg?.minute_step ?? 2)} />
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
              <label>Lab D YES floor (%)</label>
              <input id="opt_lab_d_yes_floor_pct" type="number" min={45} max={95} defaultValue={String(optimizerCfg?.lab_d_yes_floor_pct ?? 50)} />
            </div>
            <div className="field">
              <label>Lab D min minutes-left floor</label>
              <input id="opt_lab_d_min_minutes_left" type="number" min={0} max={30} defaultValue={String(optimizerCfg?.lab_d_min_minutes_left ?? 2)} />
            </div>
            <div className="field">
              <label>Lab E YES floor (%)</label>
              <input id="opt_lab_e_yes_floor_pct" type="number" min={45} max={95} defaultValue={String(optimizerCfg?.lab_e_yes_floor_pct ?? 53)} />
            </div>
            <div className="field">
              <label>Lab E min minutes-left floor</label>
              <input id="opt_lab_e_min_minutes_left" type="number" min={0} max={30} defaultValue={String(optimizerCfg?.lab_e_min_minutes_left ?? 3)} />
            </div>
            <div className="field">
              <label>Min settled trades before optimize</label>
              <input id="opt_min_trades_for_optimize" type="number" min={2} max={500} defaultValue={String(optimizerCfg?.min_trades_for_optimize ?? 8)} />
            </div>
            <div className="field">
              <label>Min profitable trades before optimize</label>
              <input id="opt_min_profitable_trades" type="number" min={0} max={200} defaultValue={String(optimizerCfg?.min_profitable_trades ?? 2)} />
            </div>
            <div className="field">
              <label>Regime lookback (hours)</label>
              <input id="opt_regime_lookback_hours" type="number" min={1} max={168} defaultValue={String(optimizerCfg?.regime_lookback_hours ?? 4)} />
            </div>
            <label className="checkbox" style={{ border: "none" }}>
              <input id="opt_optimize_bet_size" type="checkbox" defaultChecked={Boolean(optimizerCfg?.optimize_bet_size ?? true)} disabled={busy} />
              <span>Let optimizer suggest Lab A bet fraction (only lab_a is auto-applied)</span>
            </label>
            <label className="checkbox" style={{ border: "none" }}>
              <input
                id="opt_optimize_internal_mutations"
                type="checkbox"
                defaultChecked={Boolean(optimizerCfg?.optimize_internal_mutations ?? true)}
                disabled={busy}
              />
              <span>Enable internal mutant-cycle rule/parameter mutations (replay + statistical gate before apply)</span>
            </label>
            <label className="checkbox" style={{ border: "none" }}>
              <input id="opt_include_fees_in_score" type="checkbox" defaultChecked={Boolean(optimizerCfg?.include_fees_in_score ?? true)} disabled={busy} />
              <span>Include fees in adaptive replay score</span>
            </label>
            <label className="checkbox" style={{ border: "none" }}>
              <input id="opt_backtest_proposals" type="checkbox" defaultChecked={Boolean(optimizerCfg?.backtest_proposals ?? true)} disabled={busy} />
              <span>Backtest adaptive rule proposals before applying</span>
            </label>
            <label className="checkbox" style={{ border: "none" }}>
              <input
                id="opt_adaptive_skip_backtest_gate"
                type="checkbox"
                defaultChecked={Boolean(optimizerCfg?.adaptive_skip_backtest_gate ?? false)}
                disabled={busy}
              />
              <span title="When backtesting is enabled, still allow adaptive threshold moves if replay does not beat baseline. Use sparingly during deep drawdowns—widens the safety gate.">
                Allow adaptive changes when replay does not beat baseline (risky)
              </span>
            </label>
            <button
              className="primary"
              disabled={busy || optimizerSaving}
              title="Save optimizer and adaptive tuning fields to the server."
              onClick={() =>
                void onSaveOptimizerConfig({
                  enabled: Boolean((document.getElementById("opt_enabled") as HTMLInputElement | null)?.checked),
                  interval_minutes: Number((document.getElementById("opt_interval_minutes") as HTMLInputElement | null)?.value || 20),
                  lookback_hours: Number((document.getElementById("opt_lookback_hours") as HTMLInputElement | null)?.value || 48),
                  adaptive_enabled: Boolean((document.getElementById("opt_adaptive_enabled") as HTMLInputElement | null)?.checked),
                  mode: String((document.getElementById("opt_mode") as HTMLSelectElement | null)?.value || "duel"),
                  lab_a_enabled: Boolean((document.getElementById("opt_lab_a_enabled") as HTMLInputElement | null)?.checked),
                  lab_b_enabled: Boolean((document.getElementById("opt_lab_b_enabled") as HTMLInputElement | null)?.checked),
                  lab_c_enabled: Boolean((document.getElementById("opt_lab_c_enabled") as HTMLInputElement | null)?.checked),
                  lab_d_enabled: Boolean((document.getElementById("opt_lab_d_enabled") as HTMLInputElement | null)?.checked),
                  lab_e_enabled: Boolean((document.getElementById("opt_lab_e_enabled") as HTMLInputElement | null)?.checked),
                  lab_a_style: String((document.getElementById("opt_lab_a_style") as HTMLSelectElement | null)?.value || "blend"),
                  lab_b_style: String((document.getElementById("opt_lab_b_style") as HTMLSelectElement | null)?.value || "conservative"),
                  lab_c_style: String((document.getElementById("opt_lab_c_style") as HTMLSelectElement | null)?.value || "aggressive"),
                  lab_d_style: String((document.getElementById("opt_lab_d_style") as HTMLSelectElement | null)?.value || "wild"),
                  lab_e_style: String((document.getElementById("opt_lab_e_style") as HTMLSelectElement | null)?.value || "balanced"),
                  loss_streak_trigger: Number((document.getElementById("opt_loss_streak_trigger") as HTMLInputElement | null)?.value || 1),
                  threshold_step_pct: Number((document.getElementById("opt_threshold_step_pct") as HTMLInputElement | null)?.value || 2),
                  minute_step: Number((document.getElementById("opt_minute_step") as HTMLInputElement | null)?.value || 2),
                  lab_a_yes_floor_pct: Number((document.getElementById("opt_lab_a_yes_floor_pct") as HTMLInputElement | null)?.value || 57),
                  lab_b_yes_floor_pct: Number((document.getElementById("opt_lab_b_yes_floor_pct") as HTMLInputElement | null)?.value || 55),
                  lab_a_min_minutes_left: Number((document.getElementById("opt_lab_a_min_minutes_left") as HTMLInputElement | null)?.value || 5),
                  lab_b_min_minutes_left: Number((document.getElementById("opt_lab_b_min_minutes_left") as HTMLInputElement | null)?.value || 3),
                  lab_c_yes_floor_pct: Number((document.getElementById("opt_lab_c_yes_floor_pct") as HTMLInputElement | null)?.value || 52),
                  lab_c_min_minutes_left: Number((document.getElementById("opt_lab_c_min_minutes_left") as HTMLInputElement | null)?.value || 3),
                  lab_d_yes_floor_pct: Number((document.getElementById("opt_lab_d_yes_floor_pct") as HTMLInputElement | null)?.value || 50),
                  lab_d_min_minutes_left: Number((document.getElementById("opt_lab_d_min_minutes_left") as HTMLInputElement | null)?.value || 2),
                  lab_e_yes_floor_pct: Number((document.getElementById("opt_lab_e_yes_floor_pct") as HTMLInputElement | null)?.value || 53),
                  lab_e_min_minutes_left: Number((document.getElementById("opt_lab_e_min_minutes_left") as HTMLInputElement | null)?.value || 3),
                  min_trades_for_optimize: Number((document.getElementById("opt_min_trades_for_optimize") as HTMLInputElement | null)?.value || 8),
                  min_profitable_trades: Number((document.getElementById("opt_min_profitable_trades") as HTMLInputElement | null)?.value || 2),
                  regime_lookback_hours: Number((document.getElementById("opt_regime_lookback_hours") as HTMLInputElement | null)?.value || 4),
                  optimize_bet_size: Boolean((document.getElementById("opt_optimize_bet_size") as HTMLInputElement | null)?.checked),
                  optimize_internal_mutations: Boolean(
                    (document.getElementById("opt_optimize_internal_mutations") as HTMLInputElement | null)?.checked,
                  ),
                  include_fees_in_score: Boolean((document.getElementById("opt_include_fees_in_score") as HTMLInputElement | null)?.checked),
                  backtest_proposals: Boolean((document.getElementById("opt_backtest_proposals") as HTMLInputElement | null)?.checked),
                  adaptive_skip_backtest_gate: Boolean(
                    (document.getElementById("opt_adaptive_skip_backtest_gate") as HTMLInputElement | null)?.checked,
                  ),
                })
              }
            >
              Save optimizer settings
            </button>
            <div style={{ marginTop: 18 }} className="field">
              <h3 className="section-tip" style={{ margin: "0 0 10px 0", fontSize: 14 }}>
                Internal Optimizer Controls
              </h3>
              <button
                type="button"
                className="primary"
                disabled={busy || optimizerSaving || forcingMutation || !onForceInternalMutationNow}
                title="POST /api/optimizer/force-internal-mutation: one internal mutant cycle with replay + fitness gate; bypasses the scheduler. Same as the dashboard force control. Does not place exchange orders."
                onClick={() =>
                  void (async () => {
                    if (!onForceInternalMutationNow) return;
                    setForcingMutation(true);
                    try {
                      await onForceInternalMutationNow();
                    } finally {
                      setForcingMutation(false);
                    }
                  })()
                }
              >
                {forcingMutation ? "Forcing Internal Mutation..." : "Force Internal Mutation Now"}
              </button>
              <p className="sub" style={{ marginTop: 8, fontSize: 11, lineHeight: 1.45 }}>
                Runs one internal rule and parameter mutation with the same replay fitness gate as scheduled ticks. Also advances any due internal lab-evolution housekeeping on this call.
              </p>
            </div>
            <div style={{ marginTop: 20 }}>
              <h3 style={{ margin: "0 0 8px 0", fontSize: 13, color: "var(--text)" }}>Internal Optimizer Trace (last 20 cycles)</h3>
              <div
                className="sub"
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                  gap: "6px 12px",
                  marginBottom: 8,
                  fontSize: 11,
                  lineHeight: 1.3,
                }}
              >
                <div title="Rows in the rolling trace window (last 20).">
                  Cycles: <strong>{optimizerTraceStats.cycles}</strong>
                </div>
                <div title="Share of trace rows marked accepted (same basis as the dashboard health badge when populated).">
                  Accept %: <strong>{optimizerTraceStats.rate.toFixed(1)}%</strong>
                </div>
                <div title="Fitness score from the newest trace row, if present.">
                  Last: <strong>{optimizerTraceStats.lastScore == null ? "—" : optimizerTraceStats.lastScore.toFixed(3)}</strong>
                </div>
                <div title="Average score change per step across the window (rough momentum).">
                  Trend/c: <strong>
                    {optimizerTraceStats.avgTrend >= 0 ? "+" : ""}
                    {optimizerTraceStats.avgTrend.toFixed(3)}
                  </strong>
                </div>
              </div>
              <div style={{ width: "100%", height: 180, marginTop: 8 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={optimizerTraceChartRows}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1a2544" vertical={false} />
                    <XAxis dataKey="idx" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 10 }} width={40} />
                    <Tooltip
                      content={({ active, payload, label }) => {
                        if (!active || !payload || !payload.length) return null;
                        const p = payload[0].payload as {
                          score: number | null;
                          label: string;
                          stopN: number;
                          stopRate: number;
                          stopPnl: number;
                        };
                        return (
                          <div
                            style={{
                              background: "rgba(20,24,40,.95)",
                              border: "1px solid var(--border)",
                              borderRadius: 6,
                              padding: "8px 10px",
                              fontSize: 11,
                              lineHeight: 1.45,
                            }}
                          >
                            <div style={{ fontWeight: 600, marginBottom: 4 }}>Cycle {String(label)} · {p.label}</div>
                            <div>
                              Fitness: {p.score == null ? "—" : p.score.toFixed(3)}
                            </div>
                            <div>
                              Stop-loss exits: {p.stopN} ({p.stopRate.toFixed(1)}% of replay trades)
                            </div>
                            <div>
                              PnL from stops: {p.stopPnl >= 0 ? "+" : ""}
                              {p.stopPnl.toFixed(2)} $
                            </div>
                          </div>
                        );
                      }}
                    />
                    <Line type="monotone" dataKey="score" stroke="#6ee7ff" strokeWidth={2} dot={false} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div
                className="sub"
                style={{ marginTop: 8, maxHeight: 160, overflowY: "auto", fontSize: 10, lineHeight: 1.4 }}
                title="Newest-first trace lines. Stop metrics use the Lab A replay for that cycle."
              >
                {optimizerTraceRows.map((r, i) => {
                  const sn = Number(r?.stop_loss_exits_n ?? 0) || 0;
                  const sr = Number(r?.stop_loss_trigger_rate_pct ?? 0) || 0;
                  const sp = Number(r?.total_pnl_from_stops_dollars ?? 0) || 0;
                  const sc = r?.score_after ?? r?.score ?? r?.score_before;
                  return (
                    <div
                      key={`${String(r?.at || "")}-${i}`}
                      style={{
                        marginBottom: 6,
                        paddingBottom: 6,
                        borderBottom: "1px solid var(--border)",
                      }}
                    >
                      <div>
                        <strong>#{i + 1}</strong> {formatOptimizerTraceAt(String(r?.at || ""))} · fitness{" "}
                        {sc != null && Number.isFinite(Number(sc)) ? Number(sc).toFixed(3) : "—"}
                      </div>
                      <div style={{ opacity: 0.85 }}>
                        Stop-loss exits: {sn} trades ({sr.toFixed(1)}%) · PnL from stops: {sp >= 0 ? "+" : ""}
                        {sp.toFixed(2)} $
                      </div>
                    </div>
                  );
                })}
              </div>
              <div style={{ width: "100%", height: 120, marginTop: 10 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={[{ name: "decisions", accepted: optimizerTraceStats.accepted, rejected: Math.max(0, optimizerTraceStats.cycles - optimizerTraceStats.accepted) }]}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1a2544" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 10 }} width={40} allowDecimals={false} />
                    <Tooltip />
                    <Bar dataKey="accepted" fill="#3ddc97" />
                    <Bar dataKey="rejected" fill="#ff8a80" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
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
        <h2 className="section-tip" style={{ marginTop: 28 }} title="SQLite paths, JSONL streams, and full reset options.">
          Data & backups
        </h2>
        <p className="sub" style={{ marginTop: 6, fontSize: 12, lineHeight: 1.45 }} title="Paths mirror the storage object from GET /api/dashboard.">
          <strong>SQLite</strong>:{" "}
          <code style={{ wordBreak: "break-all" }} title="Primary SQLite database for signals, trades, equity, and config.">
            {String(dash?.storage?.sqlite_path ?? "—")}
          </code>
          <br />
          <strong>JSONL logs</strong>:{" "}
          <code style={{ wordBreak: "break-all" }} title="Daily JSONL streams (signals, trades, system, etc.).">
            {String(dash?.storage?.data_log_dir ?? "—")}
          </code>
          {dash?.storage?.data_reset_token_configured ? (
            <>
              <br />
              <span className="sub" title="POST /api/data/reset expects header X-Reset-Token when DATA_RESET_TOKEN is set.">
                <strong>Reset token</strong> is configured in <code>.env</code>. Enter it below for guarded resets, or remove <code>DATA_RESET_TOKEN</code> to
                disable the header check.
              </span>
              <div className="field" style={{ marginTop: 10 }}>
                <label htmlFor="reset_token_field" className="section-tip" title="Must match DATA_RESET_TOKEN from the backend environment.">
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
        <label className="checkbox section-tip" style={{ border: "none", marginTop: 8 }} title="When enabled, export SQLite and table JSONL backups before destructive deletes.">
          <input id="reset_backup" type="checkbox" defaultChecked disabled={busy} />
          <span>Before reset: copy SQLite + table JSONL exports</span>
        </label>
        <div className="field" style={{ marginTop: 10 }}>
          <label htmlFor="reset_uniform_paper_cents" className="section-tip" title="After wipe, optionally set identical paper_balance_cents on Live (if paper) and Labs A–E.">
            Same starting paper balance after reset (cents)
          </label>
          <input
            id="reset_uniform_paper_cents"
            type="number"
            min={0}
            max={100_000_000}
            step={1000}
            disabled={busy}
            placeholder="leave blank to keep current config values"
          />
          <div className="sub" style={{ marginTop: 4, fontSize: 11, opacity: 0.88 }}>
            Example: <code>500000</code> = $5,000.00 per branch. Empty = do not change bankroll fields in{" "}
            <code>bot_config</code>. When set, per-lab <code>paper_lifetime_basis_cents</code> is cleared so Labs
            A–E and Live all use the same equity baseline (otherwise older labs could keep a higher lifetime basis).
          </div>
        </div>
        <button
          type="button"
          className="primary"
          style={{ marginTop: 10, borderColor: "#6b2a2a", background: "linear-gradient(180deg,#2a1520,#1a0f18)" }}
          disabled={busy}
          title="Deletes all signals, trades, and equity snapshots on every branch. Keeps bot_config (rules, assets, optimizer settings, etc.). Optional uniform paper only updates bankroll fields."
          onClick={() => {
            const el = document.getElementById("reset_backup") as HTMLInputElement | null;
            const backup = el ? el.checked : true;
            const balEl = document.getElementById("reset_uniform_paper_cents") as HTMLInputElement | null;
            const rawBal = balEl?.value?.trim() ?? "";
            let uniformCents: number | null = null;
            if (rawBal !== "") {
              const n = Number(rawBal);
              if (!Number.isFinite(n) || n < 0 || n > 100_000_000) {
                window.alert("Same starting balance must be a number between 0 and 100000000 cents (leave blank to skip).");
                return;
              }
              uniformCents = Math.round(n);
            }
            if (
              !window.confirm(
                uniformCents != null
                  ? `Reset ALL branch trading data? This removes every signal, trade, and equity snapshot row from SQLite (live, lab_a, lab_b, lab_c, lab_d, lab_e). Then Live + each lab paper balance will be set to ${uniformCents} cents. Optimizer settings and other bot_config are otherwise kept.`
                  : "Reset ALL branch trading data? This removes every signal, trade, and equity snapshot row from SQLite (live, lab_a, lab_b, lab_c, lab_d, lab_e). Paper balance fields in config are unchanged unless you filled the optional cents field above; optimizer settings are not cleared. Prefer per-branch resets under Global / Live or Simulation labs when possible.",
              )
            ) {
              return;
            }
            void onResetTradingData("all", backup, uniformCents);
          }}
        >
          Reset all branches (SQLite)
        </button>
          </>
        ) : null}
          </>
        )}
      </div>
    </div>
  );
}
