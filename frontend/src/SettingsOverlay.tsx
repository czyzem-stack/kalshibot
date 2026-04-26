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
import { KalshiSetupOrbRow } from "./KalshiSetupOrbRow";

type AnyObj = Record<string, any>;
type SettingsTab = "live" | "lab_a" | "lab_b" | "lab_c" | "lab_d" | "lab_ab_optimizer" | "all" | "help";
type LabBranchKey = "a" | "b" | "c" | "d";

/** Local display for optimizer ``claude_proposals_trace[].at`` (ISO from backend). */
function formatClaudeTraceAt(iso: string): string {
  const s = String(iso || "").trim();
  if (!s) return "—";
  const ms = Date.parse(s);
  if (!Number.isFinite(ms)) return s;
  return new Date(ms).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function LabSizingInputs({ which, lab, cfg, busy }: { which: LabBranchKey; lab: AnyObj; cfg: AnyObj; busy: boolean }) {
  const p = `lab_${which}`;
  const defFrac = which === "a" ? 0.055 : which === "b" ? 0.06 : which === "c" ? 0.1 : 0.13;
  const defWin = which === "a" ? 15 : which === "b" ? 12 : which === "c" ? 10 : 10;
  const labTitle = which === "a" ? "A (staging)" : which === "b" ? "B (conservative)" : which === "c" ? "C (aggressive)" : "D (wild)";
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
  onResetTradingData: (branch: "lab_a" | "lab_b" | "lab_c" | "lab_d", backup: boolean) => void;
  onSaveLabRules: (rules: AnyObj[]) => void;
  onSaveLabFromSliders: () => void;
  style?: CSSProperties;
}) {
  const p = `lab_${branch}`;
  const resetKey = branch === "a" ? "lab_a" : branch === "b" ? "lab_b" : branch === "c" ? "lab_c" : "lab_d";
  const title = branch === "a" ? "Lab A (staging)" : branch === "b" ? "Lab B (conservative)" : branch === "c" ? "Lab C (aggressive)" : "Lab D (wild)";
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
      branch === "c" ? <>Clears <code>lab_c</code> rows only, once per bad streak (tick error or equity ≤ 0).</> : <>Clears <code>lab_d</code> rows only, once per bad streak (tick error or equity ≤ 0).</>
    );
  const resetConfirm =
    branch === "a"
      ? "Reset Lab A data only? Removes SQLite signals, trades, and equity snapshots for Lab A (including legacy sim_lab). Live and other labs are kept."
      : branch === "b"
        ? "Reset Lab B data only? Removes SQLite signals, trades, and equity snapshots for Lab B. Live and other labs are kept."
        : branch === "c"
          ? "Reset Lab C data only? Removes SQLite signals, trades, and equity snapshots for Lab C. Live and other labs are kept."
          : "Reset Lab D data only? Removes SQLite signals, trades, and equity snapshots for Lab D. Live and other labs are kept.";
  const resetBtnTitle =
    branch === "a"
      ? "Deletes Lab A branch rows only (lab_a and legacy sim_lab)."
      : branch === "b"
        ? "Deletes Lab B branch rows only."
        : branch === "c"
          ? "Deletes Lab C branch rows only."
          : "Deletes Lab D branch rows only.";

  return (
    <div
      key={`lab-${branch}-fields-${String(lab.paper_balance_cents ?? "")}-${String(lab.window_minutes ?? "")}-${String(lab.balance_fraction_per_window ?? "")}-${lab.auto_reset_paper_on_tick_failure ? 1 : 0}`}
      className="panel settings-nested-panel"
      style={{ padding: "12px 14px", ...style }}
    >
      <h3 style={{ margin: 0 }} title={`Branch lab_${branch} configuration.`}>
        {title}
      </h3>
      <p className="sub" style={{ marginTop: 8, marginBottom: 0, fontSize: 12, lineHeight: 1.45 }}>
        Bankroll, fraction, and window are in the <strong>Simulation labs</strong> row above. Here: auto-reset, rule bands, and save.
        Scheduled optimizer persists adaptive tuning to <strong>Lab A only</strong>; B/C stay reference arms.
      </p>
      <label className="checkbox section-tip" style={{ border: "none", marginTop: 12 }} title={autoResetTitle}>
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
        title={`Save ${title} options (sizing uses values in the row above).`}
        onClick={() => void onSaveLabFromSliders()}
      >
        Save {title} options
      </button>
    </div>
  );
}

function SettingsMenuItemsList({
  title,
  items,
}: {
  title: string;
  items: Array<{ name: string; what: string; impact?: string; range?: string; tip?: string }>;
}) {
  return (
    <div className="panel settings-nested-panel" style={{ marginTop: 10, padding: "10px 12px" }}>
      <h4 style={{ margin: "0 0 8px 0", fontSize: 13 }}>{title}</h4>
      {items.map((it) => (
        <div key={it.name} className="sub" style={{ marginTop: 8, fontSize: 12, lineHeight: 1.45 }}>
          <strong>{it.name}</strong> - {it.what}
          {it.impact ? <div style={{ marginTop: 2 }}>What happens: {it.impact}</div> : null}
          {it.range ? <div style={{ marginTop: 2 }}>Recommended range: {it.range}</div> : null}
          {it.tip ? <div style={{ marginTop: 2 }}>Tip: {it.tip}</div> : null}
        </div>
      ))}
    </div>
  );
}

function HelpStepCard({
  title,
  summary,
  actionLabel,
  onAction,
  defaultOpen = false,
  children,
}: {
  title: string;
  summary: string;
  actionLabel?: string;
  onAction?: () => void;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <details className="panel settings-nested-panel" style={{ marginTop: 10, padding: "10px 12px" }} open={defaultOpen}>
      <summary style={{ cursor: "pointer" }}>
        <strong>{title}</strong>
        <div className="sub" style={{ marginTop: 4, fontSize: 12, lineHeight: 1.4 }}>
          {summary}
        </div>
      </summary>
      <div style={{ marginTop: 10 }}>
        {onAction && actionLabel ? (
          <button type="button" className="primary" style={{ marginBottom: 10 }} onClick={onAction}>
            {actionLabel}
          </button>
        ) : null}
        {children}
      </div>
    </details>
  );
}

function SettingsHelpSection({
  onOpenTab,
  onOpenLabSizingTab,
}: {
  onOpenTab: (tab: SettingsTab) => void;
  onOpenLabSizingTab: (tab: LabBranchKey) => void;
}) {
  const checklistStorageKey = "kb_help_checklist_v2";
  const defaultChecklist = {
    step1WorkflowMap: false,
    step2SafeStartup: false,
    step3LabArchitecture: false,
    step4PerLabRules: false,
    step5OptimizerSetup: false,
    step6PerformanceReview: false,
    step7PromotionGate: false,
  };
  const [checklist, setChecklist] = useState(() => {
    try {
      const raw = sessionStorage.getItem(checklistStorageKey);
      if (!raw) return defaultChecklist;
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      return {
        ...defaultChecklist,
        ...Object.fromEntries(Object.keys(defaultChecklist).map((k) => [k, Boolean(parsed[k])])),
      };
    } catch {
      return defaultChecklist;
    }
  });
  const completed = Object.values(checklist).filter(Boolean).length;
  const total = Object.keys(checklist).length;
  useEffect(() => {
    try {
      sessionStorage.setItem(checklistStorageKey, JSON.stringify(checklist));
    } catch {
      // Ignore storage failures (private mode/quota).
    }
  }, [checklist]);

  return (
    <div className="panel settings-nested-panel" style={{ marginTop: 14, padding: "14px 16px" }}>
      <h2 style={{ marginTop: 0, marginBottom: 8 }}>Interactive Help: Start to Profit Playbook</h2>
      <p className="sub" style={{ fontSize: 12, lineHeight: 1.5 }}>
        This tutorial is an end-to-end setup path: make the bot stable in paper mode first, tune quality next, and only
        then graduate toward live execution with clear promotion gates.
      </p>
      <p className="sub" style={{ marginTop: 6, fontSize: 12, lineHeight: 1.5 }}>
        Checklist progress: <strong>{completed}</strong> / <strong>{total}</strong>. Mark each item after you confirm
        behavior in activity and trade logs.
      </p>

      <div className="panel settings-nested-panel" style={{ marginTop: 10, padding: "10px 12px" }}>
        <strong>Quick nav</strong>
        <div className="row" style={{ marginTop: 8, gap: 8 }}>
          <button type="button" className="primary" onClick={() => onOpenTab("live")}>
            Open Live tab
          </button>
          <button
            type="button"
            className="primary"
            onClick={() => {
              onOpenTab("all");
              onOpenLabSizingTab("a");
            }}
          >
            Open Simulation labs
          </button>
          <button type="button" className="primary" onClick={() => onOpenTab("lab_a")}>
            Open Lab A tab
          </button>
        </div>
      </div>

      <div className="panel settings-nested-panel" style={{ marginTop: 10, padding: "10px 12px" }}>
        <strong>Tutorial checklist ({completed}/{total})</strong>
        <label className="checkbox" style={{ border: "none", marginTop: 8 }}>
          <input
            type="checkbox"
            checked={checklist.step1WorkflowMap}
            onChange={(e) => setChecklist((c) => ({ ...c, step1WorkflowMap: e.target.checked }))}
          />
          <span>Step 1: I understand the workflow map and tab roles</span>
        </label>
        <label className="checkbox" style={{ border: "none" }}>
          <input
            type="checkbox"
            checked={checklist.step2SafeStartup}
            onChange={(e) => setChecklist((c) => ({ ...c, step2SafeStartup: e.target.checked }))}
          />
          <span>Step 2: Lab sizing/architecture set (A staging, B/C reference, D stress)</span>
        </label>
        <label className="checkbox" style={{ border: "none" }}>
          <input
            type="checkbox"
            checked={checklist.step3LabArchitecture}
            onChange={(e) => setChecklist((c) => ({ ...c, step3LabArchitecture: e.target.checked }))}
          />
          <span>Step 3: Safe startup completed (paper mode + filters + baseline risk)</span>
        </label>
        <label className="checkbox" style={{ border: "none" }}>
          <input
            type="checkbox"
            checked={checklist.step4PerLabRules}
            onChange={(e) => setChecklist((c) => ({ ...c, step4PerLabRules: e.target.checked }))}
          />
          <span>Step 4: Per-lab rules tuned and saved branch-by-branch</span>
        </label>
        <label className="checkbox" style={{ border: "none" }}>
          <input
            type="checkbox"
            checked={checklist.step5OptimizerSetup}
            onChange={(e) => setChecklist((c) => ({ ...c, step5OptimizerSetup: e.target.checked }))}
          />
          <span>Step 5: Optimizer guardrails and cadence configured</span>
        </label>
        <label className="checkbox" style={{ border: "none" }}>
          <input
            type="checkbox"
            checked={checklist.step6PerformanceReview}
            onChange={(e) => setChecklist((c) => ({ ...c, step6PerformanceReview: e.target.checked }))}
          />
          <span>Step 6: Performance reviewed for repeatability and drawdown control</span>
        </label>
        <label className="checkbox" style={{ border: "none" }}>
          <input
            type="checkbox"
            checked={checklist.step7PromotionGate}
            onChange={(e) => setChecklist((c) => ({ ...c, step7PromotionGate: e.target.checked }))}
          />
          <span>Step 7: Promotion gate passed before increasing live exposure</span>
        </label>
      </div>

      <HelpStepCard
        title="1) Workflow map: settings as a runbook"
        summary="Use tabs as a pipeline: safety -> sizing -> branch tuning -> optimizer -> review."
        actionLabel="Go to All tab"
        onAction={() => onOpenTab("all")}
        defaultOpen
      >
        <ul className="sub" style={{ marginTop: 0, fontSize: 12, lineHeight: 1.5 }}>
          <li>
            <strong>Live</strong>: market filters, global sizing, and default rules.
          </li>
          <li>
            <strong>Lab A/B/C/D</strong>: per-lab overrides and branch-specific save.
          </li>
          <li>
            <strong>Optimizer</strong>: scheduler, adaptive thresholds, style, guardrails.
          </li>
          <li>
            <strong>All</strong>: combined view + all labs bulk apply tools.
          </li>
        </ul>
        <SettingsMenuItemsList
          title="Settings menu map"
          items={[
            {
              name: "Live",
              what: "Filters + baseline sizing + global rule controls.",
              impact: "Changes affect default live behavior and fallbacks used when lab rules are absent.",
            },
            {
              name: "Lab A / Lab B / Lab C / Lab D",
              what: "Branch-specific controls (rule sliders and branch save).",
              impact: "Only the selected lab branch is changed.",
            },
            {
              name: "Optimizer",
              what: "Scheduler, adaptive controls, lab include toggles, thresholds, replay/backtest gates.",
              impact: "Affects optimization loop; persisted adaptive writes target Lab A.",
            },
            {
              name: "All",
              what: "Combined controls including the Simulation labs row and bulk apply actions.",
              impact: "Lets you update multiple labs in one workflow.",
            },
          ]}
        />
      </HelpStepCard>

      <HelpStepCard
        title="2) Simulation lab sizing and architecture"
        summary="Configure lab bankroll/sizing and branch roles before comparing performance."
        actionLabel="Open Simulation labs (Lab A)"
        onAction={() => {
          onOpenTab("all");
          onOpenLabSizingTab("a");
        }}
      >
        <ul className="sub" style={{ marginTop: 0, fontSize: 12, lineHeight: 1.5 }}>
          <li>
            <strong>Paper balance (cents)</strong>: starting bankroll for that lab.
          </li>
          <li>
            <strong>Balance fraction per window</strong>: percent of available paper bankroll used when the engine buys.
          </li>
          <li>
            <strong>Window (minutes)</strong>: spend bucket for pacing and dedupe timing.
          </li>
        </ul>
        <div className="row" style={{ gap: 8 }}>
          <button
            type="button"
            className="primary"
            onClick={() => {
              onOpenTab("all");
              onOpenLabSizingTab("a");
            }}
          >
            Jump to Lab A sliders
          </button>
          <button
            type="button"
            className="primary"
            onClick={() => {
              onOpenTab("all");
              onOpenLabSizingTab("b");
            }}
          >
            Jump to Lab B sliders
          </button>
          <button
            type="button"
            className="primary"
            onClick={() => {
              onOpenTab("all");
              onOpenLabSizingTab("c");
            }}
          >
            Jump to Lab C sliders
          </button>
        </div>
        <SettingsMenuItemsList
          title="Exact slider items in Simulation labs"
          items={[
            {
              name: "Paper balance (cents)",
              what: "Seed bankroll for that lab.",
              impact: "Changes available paper capital and affects return-vs-start metrics.",
              range: "Start around 500000-2000000 cents ($5k-$20k paper) for stable testing.",
            },
            {
              name: "Balance fraction per window",
              what: "Fraction of available bankroll used for entries.",
              impact: "Higher values increase trade size and drawdown speed.",
              range: "Lab A 0.04-0.07, Lab B 0.03-0.06, Lab C 0.08-0.14.",
              tip: "Move by small increments (~0.005 to 0.01) and observe at least one full market session.",
            },
            {
              name: "Window (minutes)",
              what: "Spend bucket / dedupe timing horizon.",
              impact: "Shorter windows recycle spend sooner but can increase churn.",
              range: "8-20 minutes for most paper setups.",
            },
            {
              name: "Save all labs",
              what: "Applies the sizing row values for A/B/C/D in one request.",
              impact: "Writes multiple branch configs together.",
            },
          ]}
        />
      </HelpStepCard>

      <HelpStepCard
        title="3) Safe startup before optimization"
        summary="Verify feed health, keep paper mode, and narrow the market universe."
        actionLabel="Open Live tab"
        onAction={() => onOpenTab("live")}
      >
        <ul className="sub" style={{ marginTop: 0, fontSize: 12, lineHeight: 1.5 }}>
          <li>
            <strong>Only if YES title contains</strong>: allow only rows whose YES subtitle contains text.
          </li>
          <li>
            <strong>Skip if YES title contains</strong>: comma-separated deny list.
          </li>
          <li>
            <strong>Balance fraction/window/poll/paper balance</strong>: defines baseline loop behavior.
          </li>
        </ul>
        <SettingsMenuItemsList
          title="Exact Live tab menu items"
          items={[
            {
              name: "Only if YES title contains",
              what: "Whitelist filter for YES subtitle text.",
              impact: "Rows that do not match are skipped before rule evaluation.",
            },
            {
              name: "Skip if YES title contains (comma-separated)",
              what: "Blacklist filter for subtitle tokens.",
              impact: "Matching rows are excluded from trading decisions.",
              tip: "Keep conservative skip tokens in production; be looser on demo environments if subtitles are noisy.",
            },
            {
              name: "Balance fraction per trade",
              what: "Global default fraction for live baseline sizing.",
              impact: "Controls default trade size when branch overrides are absent.",
            },
            {
              name: "Window length (minutes) / Poll seconds / Paper balance (cents)",
              what: "Loop cadence and spending context.",
              impact: "Changes risk pacing, scan cycle rhythm, and fallback bankroll.",
              range: "Poll often 5-12 seconds; window commonly 10-20 minutes.",
            },
          ]}
        />
      </HelpStepCard>

      <HelpStepCard
        title="4) Per-lab rules and branch save flow"
        summary="Tune one branch at a time and verify before additional edits."
        actionLabel="Open Lab A tab"
        onAction={() => onOpenTab("lab_a")}
      >
        <p className="sub" style={{ marginTop: 0, fontSize: 12, lineHeight: 1.5 }}>
          Each lab tab contains branch-level controls. Lab A is staging and receives adaptive persisted tuning. B/C/D act as reference arms.
        </p>
        <div className="row" style={{ gap: 8 }}>
          <button type="button" className="primary" onClick={() => onOpenTab("lab_a")}>
            Open Lab A tab
          </button>
          <button type="button" className="primary" onClick={() => onOpenTab("lab_b")}>
            Open Lab B tab
          </button>
          <button type="button" className="primary" onClick={() => onOpenTab("lab_c")}>
            Open Lab C tab
          </button>
          <button type="button" className="primary" onClick={() => onOpenTab("lab_d")}>
            Open Lab D tab
          </button>
        </div>
        <SettingsMenuItemsList
          title="Exact per-lab menu items"
          items={[
            {
              name: "Lab X controls panel",
              what: "Per-lab safety and behavior controls plus branch-specific rules.",
              impact: "Changes only the selected lab branch.",
            },
            {
              name: "RulesBandsSliders / NoBandsSliders",
              what: "Interactive branch rule threshold editors.",
              impact: "Changes branch entry behavior for probability bands and side filters.",
            },
            {
              name: "Save Lab X options",
              what: "Commits current lab branch panel settings.",
              impact: "Persists branch-specific rules and options for that lab key.",
            },
          ]}
        />
      </HelpStepCard>

      <HelpStepCard
        title="5) Optimizer guardrails and cadence"
        summary="Prioritize quality gates over speed to avoid overfitting."
        actionLabel="Open Optimizer tab"
        onAction={() => onOpenTab("lab_ab_optimizer")}
      >
        <p className="sub" style={{ marginTop: 0, fontSize: 12, lineHeight: 1.5 }}>
          Start conservative: keep backtest checks on, keep skip-backtest-gate off, and wait for enough settled paper data before increasing aggressiveness.
        </p>
        <SettingsMenuItemsList
          title="Exact Optimizer tab menu items"
          items={[
            {
              name: "Mode / Enable scheduled optimizer loop / Scheduled run interval / Optimizer data lookback",
              what: "Core scheduling and context horizon controls.",
              impact: "Changes how frequently optimizer evaluates and what history window it considers.",
            },
            {
              name: "Enable adaptive threshold/time auto-correction",
              what: "Turns on internal adaptive pulse behavior.",
              impact: "Allows floor/minutes and bet-fraction adaptation based on trade outcomes and guards.",
            },
            {
              name: "Lab include toggles + Lab style selectors",
              what: "Decides which labs participate in optimizer context and their posture labels.",
              impact: "Changes context interpretation; persisted adaptive writes still target Lab A.",
            },
            {
              name: "Losses trigger / threshold step / minute step / YES floors / min-minutes-left",
              what: "Adaptive sensitivity and guardrail knobs.",
              impact: "Adjusts how quickly optimizer tightens or relaxes thresholds.",
              tip: "Increase cautiously; tune one variable at a time after sufficient settled paper data.",
            },
            {
              name: "Min trades / Min profitable / Regime lookback / Optimize bet size / Include fees / Backtest proposals / Skip gate",
              what: "Quality gates and risk controls for proposal acceptance.",
              impact: "Controls whether changes are allowed and how strict replay validation is.",
            },
          ]}
        />
      </HelpStepCard>

      <HelpStepCard
        title="6) Review, compare, and validate edge"
        summary="Confirm repeatability before any live-capital escalation."
        actionLabel="Open All tab"
        onAction={() => onOpenTab("all")}
      >
        <ul className="sub" style={{ marginTop: 0, fontSize: 12, lineHeight: 1.5 }}>
          <li>Compare branches over matching windows, not one-off spike periods.</li>
          <li>Track drawdown depth and recovery speed alongside total PnL.</li>
          <li>Use the trades-by-lab snapshot toast as a recent behavior journal.</li>
        </ul>
        <SettingsMenuItemsList
          title="Signals of robust profitability"
          items={[
            {
              name: "Settled sample size",
              what: "Enough closed trades to trust directional performance.",
              impact: "Small samples are noisy and often regress.",
            },
            {
              name: "Consistency across sessions",
              what: "Repeatable behavior under multiple market regimes.",
              impact: "More valuable than one outsized gain day.",
            },
            {
              name: "Controlled drawdowns",
              what: "Losses remain inside your predefined risk budget.",
              impact: "Determines survivability and confidence for promotion.",
            },
          ]}
        />
      </HelpStepCard>

      <HelpStepCard
        title="7) Promotion gate for live capital"
        summary="Treat live rollout as phased deployment, not a single switch."
        actionLabel="Open Live tab"
        onAction={() => onOpenTab("live")}
      >
        <SettingsMenuItemsList
          title="Promotion gate checklist (recommended)"
          items={[
            {
              name: "Gate 1 - data sufficiency",
              what: "Sufficient settled history across multiple sessions.",
              impact: "Reduces chance of promoting random luck.",
            },
            {
              name: "Gate 2 - risk behavior",
              what: "Drawdown and loss streaks stay inside acceptable limits.",
              impact: "Prevents over-sizing unstable behavior.",
            },
            {
              name: "Gate 3 - staged rollout",
              what: "Increase live exposure in small steps only.",
              impact: "Limits blast radius while validating real execution.",
              tip: "Change one major variable at a time, then observe before the next change.",
            },
          ]}
        />
      </HelpStepCard>

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
  onSaveLabARules: (rules: AnyObj[]) => void | Promise<void>;
  onSaveLabBRules: (rules: AnyObj[]) => void | Promise<void>;
  onSaveLabCRules: (rules: AnyObj[]) => void | Promise<void>;
  onSaveLabDRules: (rules: AnyObj[]) => void | Promise<void>;
  onSaveDevSimHighYesPct: (pct: number | null) => void | Promise<void>;
  onSaveNoBetWhenYesBelow: (pct: number | null) => void | Promise<void>;
  onSaveSwingExitImpliedDropPct: (pct: number | null) => void | Promise<void>;
  onSavePaperFees: (patch: AnyObj) => void | Promise<void>;
  optimizerCfg: AnyObj;
  onSaveOptimizerConfig: (patch: AnyObj) => void | Promise<void>;
  optimizerSaving?: boolean;
  /** POST /api/optimizer/run (force); refreshes config when done. */
  onRunOptimizerNow?: () => void | Promise<void>;
  onResetTradingData: (
    branch: "all" | "all_labs" | "live" | "lab_a" | "lab_b" | "lab_c" | "lab_d",
    backup: boolean,
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
  onToggleLabA: () => void | Promise<void>;
  onToggleLabB: () => void | Promise<void>;
  onToggleLabC: () => void | Promise<void>;
  onToggleLabD: () => void | Promise<void>;
  onAddAllLabsPaper: () => void | Promise<void>;
  onRefresh: () => void | Promise<void>;
  onOpenHistory: () => void | Promise<void>;
  kalshi: AnyObj;
  heroMarqueeSpeedMult: number;
  onHeroMarqueeSpeedMultChange: (mult: number) => void;
  tradePopupToastsEnabled: boolean;
  onTradePopupToastsEnabledChange: (on: boolean) => void;
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
  busy,
  onSaveRules,
  onSaveYesSubtitleFilter,
  onSaveExcludeSubtitleFilter,
  onSaveSizing,
  onSaveLabAFromSliders,
  onSaveLabBFromSliders,
  onSaveLabCFromSliders,
  onSaveLabDFromSliders,
  onSaveLabARules,
  onSaveLabBRules,
  onSaveLabCRules,
  onSaveLabDRules,
  onSaveDevSimHighYesPct,
  onSaveNoBetWhenYesBelow,
  onSaveSwingExitImpliedDropPct,
  onSavePaperFees,
  optimizerCfg,
  onSaveOptimizerConfig,
  optimizerSaving = false,
  onRunOptimizerNow,
  onResetTradingData,
  onApplyLabBranches,
  liveEngineOn,
  onToggleLive,
  labEngineAOn,
  labEngineBOn,
  labEngineCOn,
  labEngineDOn,
  onToggleLabA,
  onToggleLabB,
  onToggleLabC,
  onToggleLabD,
  onAddAllLabsPaper,
  onRefresh,
  onOpenHistory,
  kalshi,
  heroMarqueeSpeedMult,
  onHeroMarqueeSpeedMultChange,
  tradePopupToastsEnabled,
  onTradePopupToastsEnabledChange,
}: SettingsOverlayProps) {
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("all");
  const [labSizingTab, setLabSizingTab] = useState<LabBranchKey>("a");
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
      setSettingsTab("all");
      setLabSizingTab("a");
    }
  }, [open]);
  useEffect(() => {
    if (settingsTab === "lab_a") setLabSizingTab("a");
    else if (settingsTab === "lab_b") setLabSizingTab("b");
    else if (settingsTab === "lab_c") setLabSizingTab("c");
    else if (settingsTab === "lab_d") setLabSizingTab("d");
  }, [settingsTab]);

  const showLive = settingsTab === "live" || settingsTab === "all";
  const showLabA = settingsTab === "lab_a" || settingsTab === "all";
  const showLabB = settingsTab === "lab_b" || settingsTab === "all";
  const showLabC = settingsTab === "lab_c" || settingsTab === "all";
  const showLabD = settingsTab === "lab_d" || settingsTab === "all";
  /** Shared bankroll row on non-Live/non-Help tabs (includes optimizer tab). */
  const showLabSizingGrid = settingsTab !== "live" && settingsTab !== "help";
  const showLabAColumn = settingsTab === "all" || settingsTab === "lab_a" || settingsTab === "lab_ab_optimizer";
  const showLabBColumn = settingsTab === "all" || settingsTab === "lab_b" || settingsTab === "lab_ab_optimizer";
  const showLabCColumn = settingsTab === "all" || settingsTab === "lab_c" || settingsTab === "lab_ab_optimizer";
  const showLabDColumn = settingsTab === "all" || settingsTab === "lab_d" || settingsTab === "lab_ab_optimizer";
  const showCombinedLabReset =
    settingsTab === "all" ||
    settingsTab === "lab_ab_optimizer" ||
    settingsTab === "lab_a" ||
    settingsTab === "lab_b" ||
    settingsTab === "lab_c" ||
    settingsTab === "lab_d";
  const sizingTabs: Array<{ id: LabBranchKey; label: string; visible: boolean }> = [
    { id: "a", label: "Lab A", visible: showLabAColumn },
    { id: "b", label: "Lab B", visible: showLabBColumn },
    { id: "c", label: "Lab C", visible: showLabCColumn },
    { id: "d", label: "Lab D", visible: showLabDColumn },
  ];
  const visibleSizingTabs = sizingTabs.filter((t) => t.visible);
  const activeLabSizingTab = visibleSizingTabs.some((t) => t.id === labSizingTab) ? labSizingTab : (visibleSizingTabs[0]?.id ?? "a");
  // Optimizer UI is intentionally hidden for now.
  const showOpt = false;
  const showData = settingsTab === "all";
  const showHelp = settingsTab === "help";
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
              ["lab_d", "Lab D"],
              ["all", "All"],
              ["help", "Help"],
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
        <div
          className="section-tip"
          style={{ marginTop: 10 }}
          title="Each dot reflects live signals from the last /api/dashboard — same 8 steps as the former home hero row (backend, .env, public API, private portfolio, engines, simulate, writes, notes)."
        >
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
            <strong style={{ fontSize: 11, letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--muted)" }}>
              Kalshi & connection
            </strong>
            <span className="sub" style={{ fontSize: 11 }}>
              Read / write, keys, and engine polling — hover each orb
            </span>
          </div>
          <div style={{ marginTop: 8, overflowX: "auto" }}>
            <KalshiSetupOrbRow dash={dash} cfg={cfg} />
          </div>
        </div>
        <div
          className="section-tip settings-lab-engines-panel"
          style={{ marginTop: 12 }}
          title="Start/stop the Live and paper lab engine loops. Status reflects the last dashboard poll."
        >
          <div className="settings-lab-engines-panel__title-row">
            <strong style={{ fontSize: 11, letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--muted)" }}>
              Engine controls
            </strong>
            <span className="sub" style={{ fontSize: 11 }}>
              Persistent header across all settings tabs
            </span>
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
          </div>
          <div className="settings-lab-engine-actions">
            <button
              type="button"
              className="primary"
              disabled={busy}
              title="Fetch /api/dashboard now (auto every ~8s)."
              onClick={() => void onRefresh()}
            >
              Refresh now
            </button>
            <button
              type="button"
              disabled={busy}
              title="Explore saved historical rows and export CSV."
              onClick={() => void onOpenHistory()}
            >
              History
            </button>
            <button type="button" className="primary" disabled={busy} title="Live engine loop." onClick={() => void onToggleLive()}>
              Turn Live {liveEngineOn ? "off" : "on"}
            </button>
            <button type="button" className="primary" disabled={busy} title="Lab A - staging paper engine." onClick={() => void onToggleLabA()}>
              Turn A {labEngineAOn ? "off" : "on"}
            </button>
            <button type="button" className="primary" disabled={busy} title="Lab B - conservative reference arm." onClick={() => void onToggleLabB()}>
              Turn B {labEngineBOn ? "off" : "on"}
            </button>
            <button type="button" className="primary" disabled={busy} title="Lab C - aggressive reference arm." onClick={() => void onToggleLabC()}>
              Turn C {labEngineCOn ? "off" : "on"}
            </button>
            <button type="button" className="primary" disabled={busy} title="Lab D - wild reference arm." onClick={() => void onToggleLabD()}>
              Turn D {labEngineDOn ? "off" : "on"}
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
          <div className="hero-meta" style={{ marginTop: 10 }} title="Kalshi REST host and environment loaded by the backend from .env.">
            <span className="env-pill" title="Base URL the backend uses for Kalshi (demo vs prod).">
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
            title="Stored in this browser only (localStorage). Controls the header ticker and the Live / Lab balance tile."
          >
            <h3 style={{ margin: 0, fontSize: 12, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--muted)" }}>
              Hero ticker & balance tile
            </h3>
            <p className="sub" style={{ marginTop: 6, marginBottom: 10, fontSize: 12, lineHeight: 1.45 }}>
              Marquee speed; the right column shows a fixed five-row snapshot (Live + Lab A–D with $ and return). Stored in this browser only.
            </p>
            <div className="field" style={{ marginBottom: 0 }} title="Multiplier for how fast the combined branch line scrolls (drag / throw still works).">
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
            <div className="field" style={{ marginTop: 14, marginBottom: 0 }} title="Bottom-right cards when a trade opens or settles (Live or sim). Stored in this browser only.">
              <label className="section-tip" style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={tradePopupToastsEnabled}
                  onChange={(e) => onTradePopupToastsEnabledChange(e.target.checked)}
                />
                <span>
                  Trade open / settle toasts <span className="sub">(bottom-right)</span>
                </span>
              </label>
            </div>
          </div>
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
          <RulesEditor
            rules={cfg.rules ?? EMPTY_RULES_LIST}
            disabled={busy}
            onSave={(r) => void onSaveRules(r)}
            onServerValidate={onValidateRulesJson}
          />
        </details>
          </>
        ) : null}

        {showLabSizingGrid ? (
          <div
            key={`lab-sizing-${String(labA.paper_balance_cents ?? "")}-${String(labB.paper_balance_cents ?? "")}-${String(labC.paper_balance_cents ?? "")}-${String(labD.paper_balance_cents ?? "")}-${String(labA.balance_fraction_per_window ?? "")}-${String(labB.balance_fraction_per_window ?? "")}-${String(labC.balance_fraction_per_window ?? "")}-${String(labD.balance_fraction_per_window ?? "")}`}
            className="panel settings-nested-panel"
            style={{ marginTop: showLive ? 20 : 12, padding: "12px 14px" }}
          >
            <h2 className="section-tip" style={{ marginTop: 0 }} title="Parallel paper labs with separate sizing, rules, and bankroll.">
              Simulation labs
            </h2>
            <p className="sub" style={{ marginTop: 6, fontSize: 12, lineHeight: 1.45 }}>
              <strong>Lab A</strong> = staging (scheduled optimizer persists adaptive tuning here). <strong>Lab B</strong> = conservative and{" "}
              <strong>Lab C</strong> = aggressive and <strong>Lab D</strong> = wild reference arms (same data to Claude for context; no auto-applied rule changes on B/C/D). Bankroll
              row values are used by per-lab <strong>Save … options</strong> and <code>PUT /api/config/lab-branches</code>. Per-lab YES/NO bands override Live until cleared in JSON;
              sliders fall back to the Live rule list when a lab has no saved <code>rules</code>.
            </p>
            <div className="chart-tabs" role="tablist" aria-label="Lab sizing branch tabs" style={{ marginTop: 12 }}>
              {visibleSizingTabs.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  aria-selected={activeLabSizingTab === t.id}
                  className={`chart-tab ${activeLabSizingTab === t.id ? "chart-tab--active" : ""}`}
                  onClick={() => setLabSizingTab(t.id)}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div className="row" style={{ marginTop: 12 }}>
              {activeLabSizingTab === "a" ? <LabSizingInputs which="a" lab={labA} cfg={cfg} busy={busy} /> : null}
              {activeLabSizingTab === "b" ? <LabSizingInputs which="b" lab={labB} cfg={cfg} busy={busy} /> : null}
              {activeLabSizingTab === "c" ? <LabSizingInputs which="c" lab={labC} cfg={cfg} busy={busy} /> : null}
              {activeLabSizingTab === "d" ? <LabSizingInputs which="d" lab={labD} cfg={cfg} busy={busy} /> : null}
            </div>
            {showCombinedLabReset ? (
              <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
                <h3 className="section-tip" style={{ margin: "0 0 6px 0", fontSize: 13 }} title="Optional SQLite wipe, then merge the bankroll/sizing numbers above in one request.">
                  Reset lab data + apply sizing (A / B / C / D)
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
                    <option value="lab_d">Lab D only</option>
                    <option value="both">Lab A + Lab B</option>
                    <option value="all_labs">Lab A + B + C + D</option>
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
                  title="PUT /api/config/lab-branches — applies bankroll/sizing (and lab toggles) from this row without wiping data."
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
                    // If a checkbox isn't rendered in this tab, keep current backend value instead of forcing false.
                    const laAutoReset = readBool("lab_a_auto_reset_failure", Boolean(labA?.auto_reset_paper_on_tick_failure));
                    const lbAutoReset = readBool("lab_b_auto_reset_failure", Boolean(labB?.auto_reset_paper_on_tick_failure));
                    const lcAutoReset = readBool("lab_c_auto_reset_failure", Boolean(labC?.auto_reset_paper_on_tick_failure));
                    const ldAutoReset = readBool("lab_d_auto_reset_failure", Boolean(labD?.auto_reset_paper_on_tick_failure));
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
                    if (resetVal !== "none") {
                      const scope =
                        resetVal === "both"
                          ? "Lab A and Lab B"
                          : resetVal === "all_labs"
                            ? "Lab A, Lab B, Lab C, and Lab D"
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
                    });
                  }}
                >
                  Save all labs (no reset if "No reset" selected)
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
        {showLabD ? (
          <LabBranchPanel
            branch="d"
            lab={labD}
            cfg={cfg}
            busy={busy}
            onResetTradingData={onResetTradingData}
            onSaveLabRules={onSaveLabDRules}
            onSaveLabFromSliders={onSaveLabDFromSliders}
            style={{ marginTop: showLabC || showLabB || showLabA ? 12 : showLabSizingGrid ? 12 : 20 }}
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
              Internal pulse (loss-streak tighten, optional win-path ease, Lab A bet fraction) runs on the optimizer interval even when the Claude scheduler is off.
            </div>
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
            <label className="checkbox" style={{ border: "none" }}>
              <input id="opt_lab_d_enabled" type="checkbox" defaultChecked={Boolean(optimizerCfg?.lab_d_enabled ?? true)} disabled={busy} />
              <span>Include Lab D in optimizer context</span>
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
                id="opt_optimize_rules_with_claude"
                type="checkbox"
                defaultChecked={Boolean(optimizerCfg?.optimize_rules_with_claude ?? true)}
                disabled={busy}
              />
              <span>Let Claude mutate Lab A rules (replay + statistical gate before apply)</span>
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
              <span title="When backtesting is on, still allow adaptive threshold moves even if replay PnL does not improve (use when the replay gate blocks all changes during a drawdown).">
                Allow adaptive changes when replay does not beat baseline (risky)
              </span>
            </label>
            <button
              className="primary"
              disabled={busy || optimizerSaving}
              title="Persist optimizer / adaptive tuning fields to the backend."
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
                  lab_a_style: String((document.getElementById("opt_lab_a_style") as HTMLSelectElement | null)?.value || "blend"),
                  lab_b_style: String((document.getElementById("opt_lab_b_style") as HTMLSelectElement | null)?.value || "conservative"),
                  lab_c_style: String((document.getElementById("opt_lab_c_style") as HTMLSelectElement | null)?.value || "aggressive"),
                  lab_d_style: String((document.getElementById("opt_lab_d_style") as HTMLSelectElement | null)?.value || "wild"),
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
                  min_trades_for_optimize: Number((document.getElementById("opt_min_trades_for_optimize") as HTMLInputElement | null)?.value || 8),
                  min_profitable_trades: Number((document.getElementById("opt_min_profitable_trades") as HTMLInputElement | null)?.value || 2),
                  regime_lookback_hours: Number((document.getElementById("opt_regime_lookback_hours") as HTMLInputElement | null)?.value || 4),
                  optimize_bet_size: Boolean((document.getElementById("opt_optimize_bet_size") as HTMLInputElement | null)?.checked),
                  optimize_rules_with_claude: Boolean(
                    (document.getElementById("opt_optimize_rules_with_claude") as HTMLInputElement | null)?.checked,
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
            <div style={{ marginTop: 14 }} className="field">
              <button
                type="button"
                className="primary"
                disabled={busy || optimizerSaving || !onRunOptimizerNow}
                title="POST /api/optimizer/run — runs internal pulse plus Claude when API key and rules/bet toggles allow."
                onClick={() => void onRunOptimizerNow?.()}
              >
                Force optimizer / Claude cycle now
              </button>
              <p className="sub" style={{ marginTop: 8, fontSize: 11, lineHeight: 1.45 }}>
                Uses <code>force=true</code> so Claude runs even if the scheduler checkbox is off (still requires{" "}
                <code>ANTHROPIC_API_KEY</code>).
              </p>
            </div>
            <div style={{ marginTop: 16 }}>
              <h3 style={{ margin: "0 0 6px 0", fontSize: 13, color: "var(--text)" }}>Claude proposals trace (last 10)</h3>
              <p className="sub" style={{ marginBottom: 8, fontSize: 11 }}>
                Each row is one proposal cycle. Expand for scores and summary; reasoning has its own toggle.
              </p>
              {(Array.isArray(optimizerCfg?.claude_proposals_trace) ? (optimizerCfg.claude_proposals_trace as AnyObj[]) : []).map(
                (row, i) => {
                  const ts = formatClaudeTraceAt(String(row.at || ""));
                  const headline = `${ts}${row.mutant ? " · mutant" : ""} · ${row.accepted ? "accepted" : "rejected"}`;
                  return (
                    <details
                      key={String(row.at || i)}
                      className="sub"
                      style={{
                        marginTop: 10,
                        fontSize: 11,
                        lineHeight: 1.45,
                        border: "1px solid var(--border)",
                        borderRadius: 6,
                        padding: "6px 10px",
                      }}
                    >
                      <summary style={{ cursor: "pointer", fontWeight: 600, listStylePosition: "outside" }}>{headline}</summary>
                      <div style={{ marginTop: 8, paddingLeft: 2 }}>
                        <div className="sub" style={{ fontSize: 10, opacity: 0.85 }} title="Raw ISO timestamp from server">
                          UTC / stored: <code>{String(row.at || "—")}</code>
                        </div>
                        {row.reject_reason ? (
                          <div style={{ marginTop: 6 }}>
                            <code>{String(row.reject_reason)}</code>
                          </div>
                        ) : null}
                        {row.score_before != null || row.score_after != null ? (
                          <div style={{ marginTop: 6 }}>
                            Score {String(row.score_before ?? "—")} → {String(row.score_after ?? "—")}
                          </div>
                        ) : null}
                        {row.summary ? <div style={{ marginTop: 6 }}>{String(row.summary).slice(0, 400)}</div> : null}
                        {row.reasoning ? (
                          <details style={{ marginTop: 8 }}>
                            <summary style={{ cursor: "pointer", fontWeight: 500 }}>Reasoning (full)</summary>
                            <pre
                              style={{
                                marginTop: 6,
                                whiteSpace: "pre-wrap",
                                fontSize: 10,
                                maxHeight: 220,
                                overflow: "auto",
                              }}
                            >
                              {String(row.reasoning)}
                            </pre>
                          </details>
                        ) : null}
                      </div>
                    </details>
                  );
                },
              )}
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
        {showHelp ? (
          <SettingsHelpSection
            onOpenTab={(tab) => setSettingsTab(tab)}
            onOpenLabSizingTab={(tab) => {
              setSettingsTab("all");
              setLabSizingTab(tab);
            }}
          />
        ) : null}
      </div>
    </div>
  );
}
