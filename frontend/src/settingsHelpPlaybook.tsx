import { useEffect, useState, type ReactNode } from "react";

export type SettingsHelpLabBranch = "a" | "b" | "c" | "d";

export type SettingsHelpPlaybookProps = {
  goGlobal: () => void;
  goLabs: (lab: SettingsHelpLabBranch) => void;
  goRules: () => void;
  goPatientStop: () => void;
  goOptimizer: () => void;
  goFeesSim: () => void;
  goData: () => void;
};

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
          <strong>{it.name}</strong> — {it.what}
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

/** Restored interactive playbook + checklist (sessionStorage) after Settings IA streamline removed the Help tab. */
export default function SettingsHelpPlaybook({
  goGlobal,
  goLabs,
  goRules,
  goPatientStop,
  goOptimizer,
  goFeesSim,
  goData,
}: SettingsHelpPlaybookProps) {
  const checklistStorageKey = "kb_help_checklist_v3";
  const defaultChecklist = {
    step1WorkflowMap: false,
    step2SafeStartup: false,
    step3LabArchitecture: false,
    step4PerLabRules: false,
    step5OptimizerSetup: false,
    step6PerformanceReview: false,
    step7PromotionGate: false,
    step8PatientStopLoss: false,
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
      // private mode / quota
    }
  }, [checklist]);

  return (
    <div className="panel settings-nested-panel" style={{ marginTop: 14, padding: "14px 16px" }}>
      <h2 style={{ marginTop: 0, marginBottom: 8 }}>Interactive help: start-to-profit playbook</h2>
      <p className="sub" style={{ fontSize: 12, lineHeight: 1.5 }}>
        End-to-end setup path: stabilize paper first, tune quality, then move toward live capital with clear promotion gates.
      </p>
      <p className="sub" style={{ marginTop: 6, fontSize: 12, lineHeight: 1.5 }}>
        Checklist progress: <strong>{completed}</strong> / <strong>{total}</strong>. Check each box after you confirm behavior in activity and trade logs.
      </p>

      <div className="panel settings-nested-panel" style={{ marginTop: 10, padding: "10px 12px" }}>
        <strong>Quick nav</strong>
        <div className="row" style={{ marginTop: 8, gap: 8, flexWrap: "wrap" }}>
          <button type="button" className="primary" onClick={() => goGlobal()}>
            Global / Live
          </button>
          <button
            type="button"
            className="primary"
            onClick={() => {
              goLabs("a");
            }}
          >
            Simulation labs (Lab A)
          </button>
          <button type="button" className="primary" onClick={() => goLabs("b")}>
            Labs · B
          </button>
          <button type="button" className="primary" onClick={() => goLabs("c")}>
            Labs · C
          </button>
          <button type="button" className="primary" onClick={() => goLabs("d")}>
            Labs · D
          </button>
          <button type="button" className="primary" onClick={() => goRules()}>
            Rules &amp; bands
          </button>
          <button type="button" className="primary" onClick={() => goPatientStop()}>
            Patient stop-loss
          </button>
          <button type="button" className="primary" onClick={() => goOptimizer()}>
            Optimizer
          </button>
          <button type="button" className="primary" onClick={() => goFeesSim()}>
            Fees &amp; sim
          </button>
          <button type="button" className="primary" onClick={() => goData()}>
            Data &amp; backups
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
          <span>Step 1: Workflow map — settings as a runbook (tab roles)</span>
        </label>
        <label className="checkbox" style={{ border: "none" }}>
          <input
            type="checkbox"
            checked={checklist.step2SafeStartup}
            onChange={(e) => setChecklist((c) => ({ ...c, step2SafeStartup: e.target.checked }))}
          />
          <span>Step 2: Simulation lab sizing and architecture (A staging, B/C reference, D stress)</span>
        </label>
        <label className="checkbox" style={{ border: "none" }}>
          <input
            type="checkbox"
            checked={checklist.step3LabArchitecture}
            onChange={(e) => setChecklist((c) => ({ ...c, step3LabArchitecture: e.target.checked }))}
          />
          <span>Step 3: Safe startup before optimization (paper, filters, baseline risk)</span>
        </label>
        <label className="checkbox" style={{ border: "none" }}>
          <input
            type="checkbox"
            checked={checklist.step4PerLabRules}
            onChange={(e) => setChecklist((c) => ({ ...c, step4PerLabRules: e.target.checked }))}
          />
          <span>Step 4: Per-lab rules and branch save flow (Labs A–D)</span>
        </label>
        <label className="checkbox" style={{ border: "none" }}>
          <input
            type="checkbox"
            checked={checklist.step5OptimizerSetup}
            onChange={(e) => setChecklist((c) => ({ ...c, step5OptimizerSetup: e.target.checked }))}
          />
          <span>Step 5: Optimizer guardrails and cadence</span>
        </label>
        <label className="checkbox" style={{ border: "none" }}>
          <input
            type="checkbox"
            checked={checklist.step6PerformanceReview}
            onChange={(e) => setChecklist((c) => ({ ...c, step6PerformanceReview: e.target.checked }))}
          />
          <span>Step 6: Review, compare, and validate edge (repeatability, drawdown)</span>
        </label>
        <label className="checkbox" style={{ border: "none" }}>
          <input
            type="checkbox"
            checked={checklist.step7PromotionGate}
            onChange={(e) => setChecklist((c) => ({ ...c, step7PromotionGate: e.target.checked }))}
          />
          <span>Step 7: Promotion gate for live capital</span>
        </label>
        <label className="checkbox" style={{ border: "none" }}>
          <input
            type="checkbox"
            checked={checklist.step8PatientStopLoss}
            onChange={(e) => setChecklist((c) => ({ ...c, step8PatientStopLoss: e.target.checked }))}
          />
          <span>Step 8: Patient stop-loss vs swing exit (per branch; fee-aware; Live + Labs)</span>
        </label>
      </div>

      <HelpStepCard
        title="1) Workflow map: settings as a runbook"
        summary="Use tabs as a pipeline: global filters and live sizing → simulation labs → rules → patient stops → optimizer → fees → data."
        actionLabel="Open Simulation labs"
        onAction={() => goLabs("a")}
        defaultOpen
      >
        <ul className="sub" style={{ marginTop: 0, fontSize: 12, lineHeight: 1.5 }}>
          <li>
            <strong>Global / Live</strong>: subtitle filters, live sizing, swing exit, live reset, shared rules JSON.
          </li>
          <li>
            <strong>Simulation labs</strong>: <strong>Reset all labs (A–D)</strong> (optional uniform paper cents), four-branch sizing row, per-lab panels (auto-reset, YES/NO band sliders, branch save).
          </li>
          <li>
            <strong>Rules &amp; bands</strong>: default YES/NO bands, dev sim controls, experiment hints.
          </li>
          <li>
            <strong>Patient stop-loss</strong>: Live + Labs A–D stop panels in one place.
          </li>
          <li>
            <strong>Optimizer</strong>: scheduler, adaptive thresholds, lab styles, traces, change history.
          </li>
          <li>
            <strong>Fees &amp; sim</strong>: paper fee model for sim exits and replay.
          </li>
          <li>
            <strong>Data &amp; backups</strong>: SQLite paths, guarded resets, optional uniform paper after wipe.
          </li>
        </ul>
        <SettingsMenuItemsList
          title="Settings menu map (current tabs)"
          items={[
            {
              name: "Global / Live",
              what: "Filters, live branch sizing, swing exit, rules JSON. (Patient stop-loss has its own tab.)",
              impact: "Changes default live behavior and shared fallbacks.",
            },
            {
              name: "Simulation labs",
              what: "A/B/C/D sizing row, lab sub-tabs, per-lab rules sliders and save.",
              impact: "Only the edited lab branch changes when you save that panel.",
            },
            {
              name: "Rules & bands",
              what: "Default rule bands, NO bands, subtitle experiments.",
              impact: "Feeds baseline rules when a lab does not override.",
            },
            {
              name: "Patient stop-loss",
              what: "Live + Lab A–D patient stop panels together.",
              impact: "Each panel saves its branch via config APIs.",
            },
            {
              name: "Optimizer",
              what: "Scheduler, adaptive controls, lab include toggles, replay gates, internal trace.",
              impact: "Adaptive persisted writes still target Lab A staging.",
            },
            {
              name: "Fees & sim",
              what: "Paper fee model (quadratic / bps / none).",
              impact: "Affects sim PnL, exits, and replay scoring when fees are on.",
            },
            {
              name: "Data & backups",
              what: "Paths, reset token field, all-branch reset with optional uniform paper.",
              impact: "Destructive; prefer per-branch resets when possible.",
            },
          ]}
        />
      </HelpStepCard>

      <HelpStepCard
        title="2) Simulation lab sizing and architecture"
        summary="Configure lab bankroll/sizing and branch roles before comparing performance."
        actionLabel="Open Simulation labs (Lab A)"
        onAction={() => goLabs("a")}
      >
        <ul className="sub" style={{ marginTop: 0, fontSize: 12, lineHeight: 1.5 }}>
          <li>
            <strong>Paper balance (cents)</strong>: starting bankroll for that lab.
          </li>
          <li>
            <strong>Balance fraction per window</strong>: fraction of available paper bankroll used when the engine buys.
          </li>
          <li>
            <strong>Window (minutes)</strong>: spend bucket for pacing and dedupe timing.
          </li>
        </ul>
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          {(["a", "b", "c", "d"] as const).map((k) => (
            <button key={k} type="button" className="primary" onClick={() => goLabs(k)}>
              Jump to Lab {k.toUpperCase()} sliders
            </button>
          ))}
        </div>
        <SettingsMenuItemsList
          title="Exact slider items in Simulation labs"
          items={[
            {
              name: "Paper balance (cents)",
              what: "Seed bankroll for that lab.",
              impact: "Changes available paper capital and return-vs-start metrics.",
              range: "Often 500000–2000000 cents ($5k–$20k paper) for stable testing.",
            },
            {
              name: "Balance fraction per window",
              what: "Fraction of available bankroll used for entries.",
              impact: "Higher values increase trade size and drawdown speed.",
              range: "Lab A ~0.04–0.07, B ~0.03–0.06, C ~0.08–0.14, D (wild) often 0.10–0.16.",
              tip: "Move in small steps; observe at least one full session; include Lab D when stress-testing.",
            },
            {
              name: "Window (minutes)",
              what: "Spend bucket / dedupe timing horizon.",
              impact: "Shorter windows recycle spend sooner but can increase churn.",
              range: "8–20 minutes for many paper setups.",
            },
            {
              name: "Save all labs",
              what: "Applies the sizing row for A/B/C/D in one request.",
              impact: "Writes multiple branch configs together.",
            },
          ]}
        />
      </HelpStepCard>

      <HelpStepCard
        title="3) Safe startup before optimization"
        summary="Verify feed health, keep paper mode, and narrow the market universe."
        actionLabel="Open Global / Live"
        onAction={() => goGlobal()}
      >
        <p className="sub" style={{ marginTop: 0, fontSize: 12, lineHeight: 1.5 }}>
          Swing exit knobs stay on <strong>Global / Live</strong>. Paper fee model is under <strong>Fees &amp; sim</strong>. Patient stop-loss for every branch is under{" "}
          <strong>Patient stop-loss</strong>.
        </p>
        <ul className="sub" style={{ marginTop: 8, fontSize: 12, lineHeight: 1.5 }}>
          <li>
            <strong>Only if YES title contains</strong>: allow only rows whose YES subtitle contains text.
          </li>
          <li>
            <strong>Skip if YES title contains</strong>: comma-separated deny list.
          </li>
          <li>
            <strong>Balance fraction / window / poll / paper balance</strong> on Global / Live: baseline loop behavior for the live branch.
          </li>
          <li>
            <strong>Labs A–D</strong> inherit defaults until overridden per lab; tune Lab D with A/B/C for tail-risk review.
          </li>
        </ul>
        <SettingsMenuItemsList
          title="Global / Live (core)"
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
              tip: "Keep conservative skip tokens in production.",
            },
            {
              name: "Balance fraction per trade (Live)",
              what: "Global default fraction for live baseline sizing.",
              impact: "Controls default trade size when branch overrides are absent.",
            },
            {
              name: "Window length / poll / paper balance",
              what: "Loop cadence and spending context for the live branch.",
              impact: "Changes risk pacing and scan rhythm.",
              range: "Poll often 5–12 s; window commonly 10–20 minutes.",
            },
            {
              name: "Swing exit (paper)",
              what: "Closes sim positions on adverse implied YES move; same fee model as other sim exits.",
              impact: "Independent of patient stop-loss timing.",
              range: "Typical 15–40 pts; 0 = off.",
            },
          ]}
        />
      </HelpStepCard>

      <HelpStepCard
        title="4) Per-lab rules and branch save flow"
        summary="Tune one branch at a time; use Rules & bands for shared defaults."
        actionLabel="Open Simulation labs (Lab A)"
        onAction={() => goLabs("a")}
      >
        <p className="sub" style={{ marginTop: 0, fontSize: 12, lineHeight: 1.5 }}>
          Lab A is staging and receives adaptive persisted tuning. B/C are reference arms. <strong>Lab D</strong> is the wild stress arm. Per-lab{" "}
          <strong>patient stop-loss</strong> is edited on the <strong>Patient stop-loss</strong> tab (not inside each lab card).
        </p>
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          {(["a", "b", "c", "d"] as const).map((k) => (
            <button key={k} type="button" className="primary" onClick={() => goLabs(k)}>
              Open Lab {k.toUpperCase()}
            </button>
          ))}
          <button type="button" className="primary" onClick={() => goRules()}>
            Rules &amp; bands
          </button>
        </div>
        <SettingsMenuItemsList
          title="Per-lab vs shared"
          items={[
            {
              name: "Simulation labs · Lab X panel",
              what: "Auto-reset, YES/NO band sliders, branch save.",
              impact: "Changes only the selected lab branch.",
            },
            {
              name: "Rules & bands tab",
              what: "Default YES/NO bands and shared experiments.",
              impact: "Feeds defaults when a lab has no override.",
            },
            {
              name: "Save Lab X options",
              what: "Commits the visible lab panel.",
              impact: "Persists that branch via lab-branches API.",
            },
            {
              name: "Patient stop-loss tab",
              what: "Live + Lab A–D panels in one scrollable section.",
              impact: "Each panel saves its own branch.",
            },
          ]}
        />
      </HelpStepCard>

      <HelpStepCard
        title="5) Optimizer guardrails and cadence"
        summary="Prioritize quality gates over speed to avoid overfitting."
        actionLabel="Open Optimizer tab"
        onAction={() => goOptimizer()}
      >
        <p className="sub" style={{ marginTop: 0, fontSize: 12, lineHeight: 1.5 }}>
          Start conservative: keep backtest checks on, keep skip-backtest-gate off, and wait for enough settled paper data before increasing aggressiveness.
        </p>
        <SettingsMenuItemsList
          title="Optimizer tab (headline controls)"
          items={[
            {
              name: "Mode / enable loop / interval / lookback",
              what: "Scheduling and context horizon.",
              impact: "How often full optimizer runs and how much history it sees.",
            },
            {
              name: "Adaptive auto-correction",
              what: "Internal adaptive pulse on loss streaks and related guards.",
              impact: "Can move floors and bet fraction on Lab A between scheduled runs.",
            },
            {
              name: "Lab include toggles + styles",
              what: "Which arms participate and labels (blend, conservative, aggressive, wild).",
              impact: "Context for proposals; adaptive writes still target Lab A.",
            },
            {
              name: "Min trades / profitable / regime / fees / backtest / skip gate",
              what: "Quality and replay gates for accepting changes.",
              impact: "Stricter gates reduce overfitting risk.",
            },
          ]}
        />
      </HelpStepCard>

      <HelpStepCard
        title="6) Review, compare, and validate edge"
        summary="Confirm repeatability before any live-capital escalation."
        actionLabel="Open Simulation labs"
        onAction={() => goLabs("a")}
      >
        <ul className="sub" style={{ marginTop: 0, fontSize: 12, lineHeight: 1.5 }}>
          <li>
            Compare <strong>Live + Lab A–D</strong> over matching windows; include <strong>Lab D</strong> for tail churn.
          </li>
          <li>Track drawdown depth and recovery speed alongside total PnL.</li>
          <li>
            Dashboard <strong>Optimizer report</strong> overlay: schedule, rollups, traces. Bottom-right: trade toasts (when enabled) and optimizer toasts in the same stack (~10–15s dismiss).
          </li>
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
              what: "Repeatable behavior under multiple regimes.",
              impact: "More valuable than one spike day.",
            },
            {
              name: "Controlled drawdowns",
              what: "Losses stay inside your risk budget.",
              impact: "Determines survivability for promotion.",
            },
          ]}
        />
      </HelpStepCard>

      <HelpStepCard
        title="7) Promotion gate for live capital"
        summary="Treat live rollout as phased deployment, not a single switch."
        actionLabel="Open Global / Live"
        onAction={() => goGlobal()}
      >
        <SettingsMenuItemsList
          title="Promotion gate checklist (recommended)"
          items={[
            {
              name: "Gate 1 — data sufficiency",
              what: "Enough settled history across multiple sessions.",
              impact: "Reduces promoting random luck.",
            },
            {
              name: "Gate 2 — risk behavior",
              what: "Drawdown and loss streaks within limits.",
              impact: "Avoids over-sizing unstable behavior.",
            },
            {
              name: "Gate 2b — Lab D sanity",
              what: "Review wild-arm stress so tails do not surprise you after promotion.",
              impact: "D is intentionally aggressive.",
            },
            {
              name: "Gate 3 — staged rollout",
              what: "Increase live exposure in small steps.",
              impact: "Limits blast radius during real execution.",
              tip: "Change one major variable at a time, then observe.",
            },
          ]}
        />
      </HelpStepCard>

      <HelpStepCard
        title="8) Patient stop-loss vs swing exit (paper sim)"
        summary="Swing reacts to implied-price moves; patient stop reacts to fee-aware underwater PnL after a minimum hold."
        actionLabel="Open Patient stop-loss tab"
        onAction={() => goPatientStop()}
      >
        <ul className="sub" style={{ marginTop: 0, fontSize: 12, lineHeight: 1.5 }}>
          <li>
            <strong>Swing exit</strong> (Global / Live): adverse implied YES move from entry in percentage points; can fire soon after entry.
          </li>
          <li>
            <strong>Patient stop-loss</strong>: requires min hold <em>and</em> net unrealized return (after modeled sell fees) at or below your negative % vs entry debit.
          </li>
          <li>
            Use the <strong>Patient stop-loss</strong> tab for Live + each lab; optimizer replay uses branch trading config.
          </li>
        </ul>
        <div className="row" style={{ marginTop: 10, gap: 8, flexWrap: "wrap" }}>
          <button type="button" className="primary" onClick={() => goFeesSim()}>
            Fees &amp; sim (paper fee model)
          </button>
          <button type="button" className="primary" onClick={() => goData()}>
            Data &amp; backups
          </button>
        </div>
      </HelpStepCard>
    </div>
  );
}
