import { useEffect, useState } from "react";

type AnyObj = Record<string, any>;

/** Use instead of `rules || []` in parents so slider/editor `useEffect([rules])` does not run every render (new [] each time). */
export const EMPTY_RULES_LIST: AnyObj[] = [];

function isNoRule(r: AnyObj): boolean {
  return String(r?.side || "").toLowerCase() === "no";
}

/** First three non-NO rules, padded (YES / default-side bands). */
export function padRulesToThree(rules: AnyObj[]): AnyObj[] {
  const yes = (rules || []).filter((r) => !isNoRule(r));
  const r = [...yes].slice(0, 3);
  while (r.length < 3) {
    r.push({
      name: `Band ${r.length + 1}`,
      min_prob: 0.45,
      max_prob: 0.55,
      min_minutes_left: 5,
      max_minutes_left: 15,
    });
  }
  return r;
}

/** First three NO rules, padded. */
export function padNoRulesToThree(rules: AnyObj[]): AnyObj[] {
  const no = (rules || []).filter((r) => isNoRule(r));
  const r = [...no].slice(0, 3);
  while (r.length < 3) {
    r.push({
      name: `NO band ${r.length + 1}`,
      side: "no",
      min_prob: 0.62,
      max_prob: 0.78,
      min_minutes_left: 3,
      max_minutes_left: 12,
    });
  }
  return r;
}

/** Replace first three YES and first three NO slots from sliders; keep remaining rules in order. */
export function mergeRulesFromSliders(fullRules: AnyObj[], yesThree: AnyObj[], noThree: AnyObj[]): AnyObj[] {
  const fr = fullRules || [];
  const yesPool = fr.filter((r) => !isNoRule(r));
  const noPool = fr.filter((r) => isNoRule(r));
  const restYes = yesPool.slice(3);
  const restNo = noPool.slice(3);
  const yesFixed = yesThree.map((b) => {
    const o: AnyObj = { ...b };
    delete o.side;
    return o;
  });
  const noFixed = noThree.map((b) => {
    let minp = Number(b.min_prob) || 0;
    let maxp = Number(b.max_prob) || 1;
    if (minp > maxp) {
      const t = minp;
      minp = maxp;
      maxp = t;
    }
    let mn = Number(b.min_minutes_left) ?? 0;
    let mx = Number(b.max_minutes_left) ?? 15;
    if (mn > mx) {
      const t2 = mn;
      mn = mx;
      mx = t2;
    }
    return {
      ...b,
      side: "no",
      name: b.name || "NO band",
      min_prob: minp,
      max_prob: maxp,
      min_minutes_left: mn,
      max_minutes_left: mx,
    };
  });
  return [...yesFixed, ...restYes, ...noFixed, ...restNo];
}

export function RuleExperimentHints({
  dash,
  busy,
  onApply,
}: {
  dash: AnyObj;
  busy: boolean;
  onApply: (r: AnyObj[]) => void;
}) {
  const rs = dash?.rule_suggestions as AnyObj | undefined;
  if (!rs) return null;
  const presets = (rs.presets || []) as AnyObj[];
  const dyn = rs.dynamic_band as AnyObj | undefined;
  return (
    <div className="panel settings-nested-panel" style={{ marginTop: 14, padding: "12px 14px", borderStyle: "dashed" }}>
      <h2
        className="section-tip"
        style={{ marginTop: 0 }}
        title="Heuristic suggestions only, not advice. NONE under an asset = no band fits implied YES + time — widen bands or shift ranges. Sim lab stays paper."
      >
        Rule band experiments
      </h2>
      {rs.note ? <p className="sub" style={{ marginTop: 6 }}>{String(rs.note)}</p> : null}
      {dyn && dyn.name ? (
        <div style={{ marginTop: 10 }}>
          <button
            type="button"
            className="primary"
            disabled={busy}
            title="Replace rule slot #1 with a band centered on the latest cross-asset snapshot (still 3 bands total)."
            onClick={() => onApply(padRulesToThree([{ ...dyn }]))}
          >
            Apply snapshot band → rule #1
          </button>
        </div>
      ) : null}
      <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
        {presets.map((p: AnyObj) => (
          <div key={String(p.id)}>
            <button
              type="button"
              disabled={busy}
              title="Replace your three rule bands with this preset (saved to server on apply via parent save)."
              onClick={() => onApply(padRulesToThree((p.rules || []) as AnyObj[]))}
            >
              Apply preset: {String(p.label || p.id)}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

export function NoBandsSliders({
  rules,
  disabled,
  onSave,
}: {
  rules: AnyObj[];
  disabled: boolean;
  onSave: (r: AnyObj[]) => void;
}) {
  const [bands, setBands] = useState<AnyObj[]>(() => padNoRulesToThree(rules));
  useEffect(() => {
    setBands(padNoRulesToThree(rules));
  }, [rules]);

  const setBand = (i: number, patch: AnyObj) => {
    setBands((prev) => {
      const n = [...prev];
      n[i] = { ...n[i], ...patch };
      return n;
    });
  };

  return (
    <div style={{ marginTop: 16 }}>
      <h2
        className="section-tip"
        title="Up to three NO bands: min/max apply to implied NO (1 − implied YES mid). Save merges with your YES bands and any rules beyond the first three per side."
      >
        NO rule bands (sliders)
      </h2>
      {bands.map((b, i) => (
        <div key={i} className="band-card">
          <div className="field">
            <label>Band name</label>
            <input
              type="text"
              value={String(b.name || "")}
              disabled={disabled}
              onChange={(e) => setBand(i, { name: e.target.value })}
            />
          </div>
          <div className="band-sliders">
            <div className="field">
              <label>Min NO % (0–100)</label>
              <input
                type="range"
                min={0}
                max={100}
                step={1}
                disabled={disabled}
                value={Math.round(Number(b.min_prob ?? 0) * 100)}
                onChange={(e) => setBand(i, { min_prob: Number(e.target.value) / 100 })}
              />
              <span className="sub">{Math.round(Number(b.min_prob ?? 0) * 100)}%</span>
            </div>
            <div className="field">
              <label>Max NO % (0–100)</label>
              <input
                type="range"
                min={0}
                max={100}
                step={1}
                disabled={disabled}
                value={Math.round(Number(b.max_prob ?? 1) * 100)}
                onChange={(e) => setBand(i, { max_prob: Number(e.target.value) / 100 })}
              />
              <span className="sub">{Math.round(Number(b.max_prob ?? 1) * 100)}%</span>
            </div>
            <div className="field">
              <label>Min minutes left</label>
              <input
                type="range"
                min={0}
                max={30}
                step={1}
                disabled={disabled}
                value={Math.round(Number(b.min_minutes_left ?? 0))}
                onChange={(e) => setBand(i, { min_minutes_left: Number(e.target.value) })}
              />
              <span className="sub">{Math.round(Number(b.min_minutes_left ?? 0))}</span>
            </div>
            <div className="field">
              <label>Max minutes left</label>
              <input
                type="range"
                min={0}
                max={30}
                step={1}
                disabled={disabled}
                value={Math.round(Number(b.max_minutes_left ?? 15))}
                onChange={(e) => setBand(i, { max_minutes_left: Number(e.target.value) })}
              />
              <span className="sub">{Math.round(Number(b.max_minutes_left ?? 15))}</span>
            </div>
          </div>
        </div>
      ))}
      <button
        className="primary"
        style={{ marginTop: 12 }}
        disabled={disabled}
        title="Normalize min/max pairs and merge the three NO bands into config.rules (YES bands unchanged)."
        onClick={() => {
          const fixed = bands.map((b) => {
            let minp = Number(b.min_prob) || 0;
            let maxp = Number(b.max_prob) || 1;
            if (minp > maxp) {
              const t = minp;
              minp = maxp;
              maxp = t;
            }
            let mn = Number(b.min_minutes_left) || 0;
            let mx = Number(b.max_minutes_left) || 15;
            if (mn > mx) {
              const t2 = mn;
              mn = mx;
              mx = t2;
            }
            return { ...b, side: "no", min_prob: minp, max_prob: maxp, min_minutes_left: mn, max_minutes_left: mx };
          });
          onSave(mergeRulesFromSliders(rules, padRulesToThree(rules), fixed));
        }}
      >
        Save NO rule bands
      </button>
    </div>
  );
}

export function NoBetWhenYesBelowControl({
  cfg,
  busy,
  onSave,
}: {
  cfg: AnyObj;
  busy: boolean;
  onSave: (v: number | null) => void | Promise<void>;
}) {
  const serverV = cfg.no_bet_when_yes_below_pct;
  const serverOn = serverV != null && serverV !== false;
  const [autoOn, setAutoOn] = useState(serverOn);
  const [autoPct, setAutoPct] = useState(() =>
    serverOn ? Math.min(95, Math.max(1, Math.round(Number(serverV)))) : 30,
  );
  useEffect(() => {
    const on = serverV != null && serverV !== false;
    setAutoOn(on);
    setAutoPct(on ? Math.min(95, Math.max(1, Math.round(Number(serverV)))) : 30);
  }, [serverV]);

  return (
    <div className="panel settings-nested-panel" style={{ marginTop: 16, padding: "12px 14px" }}>
      <h2
        className="section-tip"
        style={{ marginTop: 0 }}
        title="Adds a catch-all NO rule evaluated last: buy NO when implied YES is below the threshold (needs a NO book). Uncheck and save to disable."
      >
        Auto NO when implied YES is low
      </h2>
      <p className="sub" style={{ marginTop: 6, fontSize: 12, lineHeight: 1.45 }}>
        When enabled, the engine appends one synthetic NO rule so any market with implied YES under your threshold can match (in addition to your explicit NO bands above).
      </p>
      <div className="field" style={{ marginTop: 10 }}>
        <label className="section-tip" style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
          <input type="checkbox" checked={autoOn} disabled={busy} onChange={(e) => setAutoOn(e.target.checked)} />
          Enable: buy NO when implied YES is below threshold
        </label>
      </div>
      <div className="field" style={{ marginTop: 8, opacity: autoOn ? 1 : 0.55 }}>
        <label className="section-tip" title="Implied YES (mid of bid/ask when both exist). 30 means trade NO when YES is under 30%.">
          Threshold (implied YES %): <strong>{autoPct}%</strong>
        </label>
        <input
          type="range"
          min={1}
          max={95}
          step={1}
          disabled={busy || !autoOn}
          value={autoPct}
          onChange={(e) => setAutoPct(Number(e.target.value))}
        />
      </div>
      <button
        className="primary"
        style={{ marginTop: 12 }}
        disabled={busy}
        title={autoOn ? "Persist threshold (1–95% implied YES)." : "Clear the auto NO rule on the server."}
        onClick={() => void onSave(autoOn ? autoPct : null)}
      >
        Save auto NO setting
      </button>
    </div>
  );
}

export function DevSimHighYesControl({
  cfg,
  busy,
  onSave,
}: {
  cfg: AnyObj;
  busy: boolean;
  onSave: (v: number | null) => void | Promise<void>;
}) {
  const rawPct = cfg.dev_sim_yes_implied_ge_pct;
  const legacyOn = Boolean(cfg.dev_sim_yes_implied_ge_70);
  const serverOn = (rawPct != null && rawPct !== false) || legacyOn;
  const serverPct =
    rawPct != null && rawPct !== false
      ? Math.min(99, Math.max(1, Math.round(Number(rawPct))))
      : 70;
  const [autoOn, setAutoOn] = useState(serverOn);
  const [autoPct, setAutoPct] = useState(() => (serverOn ? serverPct : 70));
  useEffect(() => {
    const on = (rawPct != null && rawPct !== false) || legacyOn;
    const pct =
      rawPct != null && rawPct !== false
        ? Math.min(99, Math.max(1, Math.round(Number(rawPct))))
        : 70;
    setAutoOn(on);
    setAutoPct(on ? pct : 70);
  }, [rawPct, legacyOn]);

  return (
    <div className="panel settings-nested-panel" style={{ marginTop: 16, padding: "12px 14px" }}>
      <h2
        className="section-tip"
        style={{ marginTop: 0 }}
        title="Simulated orders only (Live paper mode or Sim lab). Buys YES when implied YES is at or above your threshold and no normal rule matched. Uncheck and save to disable."
      >
        Temporary — high-probability sim trades
      </h2>
      <p className="sub" style={{ marginTop: 6, fontSize: 12, lineHeight: 1.45 }}>
        When enabled, the engine can match a dev bypass rule so YES trades fire even if no configured band matches. Does nothing when Live is in real-money mode.
      </p>
      <div className="field" style={{ marginTop: 10 }}>
        <label className="section-tip" style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
          <input type="checkbox" checked={autoOn} disabled={busy} onChange={(e) => setAutoOn(e.target.checked)} />
          Enable: trade YES when implied win chance ≥ threshold (sim only)
        </label>
      </div>
      <div className="field" style={{ marginTop: 8, opacity: autoOn ? 1 : 0.55 }}>
        <label className="section-tip" title="Implied YES from the book. 70 means buy YES when implied YES is at least 70%.">
          Threshold (implied YES %): <strong>{autoPct}%</strong>
        </label>
        <input
          type="range"
          min={1}
          max={99}
          step={1}
          disabled={busy || !autoOn}
          value={autoPct}
          onChange={(e) => setAutoPct(Number(e.target.value))}
        />
      </div>
      <button
        className="primary"
        style={{ marginTop: 12 }}
        disabled={busy}
        title={autoOn ? "Persist threshold (1–99% implied YES)." : "Turn off the dev sim YES bypass on the server."}
        onClick={() => void onSave(autoOn ? autoPct : null)}
      >
        Save dev sim YES setting
      </button>
    </div>
  );
}

export function SwingExitImpliedDropControl({
  cfg,
  busy,
  onSave,
}: {
  cfg: AnyObj;
  busy: boolean;
  onSave: (v: number | null) => void | Promise<void>;
}) {
  const fromServer =
    cfg.swing_exit_implied_drop_pct != null && Number(cfg.swing_exit_implied_drop_pct) > 0
      ? Math.min(90, Math.max(5, Math.round(Number(cfg.swing_exit_implied_drop_pct) / 5) * 5))
      : 0;
  const [pct, setPct] = useState(fromServer);
  useEffect(() => {
    const r = cfg.swing_exit_implied_drop_pct;
    setPct(r != null && Number(r) > 0 ? Math.min(90, Math.max(5, Math.round(Number(r) / 5) * 5)) : 0);
  }, [cfg.swing_exit_implied_drop_pct]);

  return (
    <div className="panel settings-nested-panel" style={{ marginTop: 16, padding: "12px 14px" }}>
      <h2
        className="section-tip"
        style={{ marginTop: 0 }}
        title="Live paper and Sim lab only. Compares current implied YES to the value stored when you bought. YES long: exit if implied YES fell by at least this many percentage points (e.g. 75%→25% = 50 pts). NO long: exit if implied YES rose by the same margin. Closes at the bid for synthetic PnL."
      >
        Swing exit (paper)
      </h2>
      <p className="sub" style={{ marginTop: 6, fontSize: 12, lineHeight: 1.45 }}>
        0 = off. Otherwise, when the book moves against your entry by at least the threshold (percentage{" "}
        <em>points</em>, not percent of entry), the bot marks the sim row settled at the bid so realized PnL updates.
        Kalshi final settlement still applies if you did not exit first.
      </p>
      <div className="field" style={{ marginTop: 10 }}>
        <label className="section-tip" title="Minimum adverse move in implied YES probability, in points (0–100 scale).">
          Min swing to exit: <strong>{pct === 0 ? "Off" : `${pct} pts`}</strong>
          {pct > 0 ? (
            <span className="sub" style={{ marginLeft: 8 }}>
              (e.g. entry 75% → need ≤ {Math.max(0, 75 - pct)}% YES for a YES long)
            </span>
          ) : null}
        </label>
        <input
          type="range"
          min={0}
          max={90}
          step={5}
          disabled={busy}
          value={pct}
          onChange={(e) => setPct(Number(e.target.value))}
          style={{ width: "100%" }}
        />
      </div>
      <button
        className="primary"
        style={{ marginTop: 12 }}
        disabled={busy}
        title={pct === 0 ? "Disable swing exits." : `Require at least ${pct} percentage-point adverse move before exiting at bid.`}
        onClick={() => void onSave(pct === 0 ? null : pct)}
      >
        Save swing exit
      </button>
    </div>
  );
}

function clampPatientTriggerPct(n: number): number {
  const x = Number(n);
  if (!Number.isFinite(x)) return -8;
  const v = x > 0 ? -Math.abs(x) : x;
  const stepped = Math.round(v * 2) / 2;
  return Math.max(-20, Math.min(-2, stepped));
}

function clampPatientHoldMin(n: number): number {
  const s = Math.round(Number(n));
  if (!Number.isFinite(s)) return 30;
  return Math.max(5, Math.min(120, Math.round(s / 5) * 5));
}

/** Per-branch patient stop-loss: toggle + loss % trigger + min hold (paper sim). */
export function PatientStopLossPanel({
  title,
  busy,
  enable,
  triggerPct,
  minHold,
  onSave,
}: {
  title: string;
  busy: boolean;
  enable: boolean;
  triggerPct: number;
  minHold: number;
  onSave: (patch: AnyObj) => void | Promise<void>;
}) {
  const [en, setEn] = useState(Boolean(enable));
  const [tr, setTr] = useState(() => clampPatientTriggerPct(triggerPct));
  const [mh, setMh] = useState(() => clampPatientHoldMin(minHold));

  useEffect(() => {
    setEn(Boolean(enable));
    setTr(clampPatientTriggerPct(triggerPct));
    setMh(clampPatientHoldMin(minHold));
  }, [enable, triggerPct, minHold]);

  return (
    <details className="panel settings-nested-panel" style={{ marginTop: 16, padding: "12px 14px" }}>
      <summary className="section-tip" style={{ cursor: "pointer" }} title="Paper sim: close at bid after min hold when fee-aware unrealized P&amp;L % hits the loss trigger.">
        <strong>Patient Stop-Loss (Loss-Recoup Exits)</strong>
        <span className="sub" style={{ marginLeft: 8, fontWeight: 400 }}>
          — {title}
        </span>
      </summary>
      <p className="sub" style={{ marginTop: 8, fontSize: 12, lineHeight: 1.45 }}>
        Uses the same Kalshi fee model as swing exits on the <strong>sell</strong> side. Trigger compares net unrealized % vs
        total entry debit (includes entry fee already in amount).
      </p>
      <label className="checkbox section-tip" style={{ border: "none", marginTop: 10 }}>
        <input type="checkbox" checked={en} disabled={busy} onChange={(e) => setEn(e.target.checked)} />
        <span>Enable patient stop-loss</span>
      </label>
      <div className="field" style={{ marginTop: 10, opacity: en ? 1 : 0.5 }}>
        <label className="section-tip" title="Negative percent vs entry debit; exit when net unrealized (after sell fees) is at or below this.">
          % loss trigger: <strong>{tr.toFixed(1)}%</strong>
        </label>
        <input
          type="range"
          min={-20}
          max={-2}
          step={0.5}
          disabled={busy || !en}
          value={tr}
          onChange={(e) => setTr(clampPatientTriggerPct(Number(e.target.value)))}
          style={{ width: "100%" }}
        />
      </div>
      <div className="field" style={{ marginTop: 10, opacity: en ? 1 : 0.5 }}>
        <label className="section-tip" title="Minimum minutes from open before the stop can fire.">
          Min hold minutes: <strong>{mh}</strong>
        </label>
        <input
          type="range"
          min={5}
          max={120}
          step={5}
          disabled={busy || !en}
          value={mh}
          onChange={(e) => setMh(clampPatientHoldMin(Number(e.target.value)))}
          style={{ width: "100%" }}
        />
      </div>
      <button
        className="primary"
        style={{ marginTop: 12 }}
        disabled={busy}
        title="Writes enable_patient_stop_loss, stop_loss_trigger_pct, min_hold_minutes_before_stop for this branch."
        onClick={() =>
          void onSave({
            enable_patient_stop_loss: en,
            stop_loss_trigger_pct: tr,
            min_hold_minutes_before_stop: mh,
          })
        }
      >
        Save patient stop-loss ({title})
      </button>
    </details>
  );
}

function normalizeFeeModelId(raw: unknown): string {
  if (raw == null || raw === "") return "bps";
  const s = String(raw).trim().toLowerCase().replace(/-/g, "_");
  if (s === "kalshi" || s === "taker" || s === "kalshi_taker") return "kalshi_taker";
  if (s === "maker" || s === "kalshi_maker") return "kalshi_maker";
  if (s === "none" || s === "off" || s === "no" || s === "false" || s === "0") return "none";
  return "bps";
}

export function PaperFeeBpsControl({
  cfg,
  busy,
  onSave,
}: {
  cfg: AnyObj;
  busy: boolean;
  onSave: (patch: AnyObj) => void | Promise<void>;
}) {
  const raw = cfg.paper_fee_bps;
  const fromServer = raw != null && Number(raw) > 0 ? Math.min(100, Math.max(1, Math.round(Number(raw)))) : 0;
  const [bps, setBps] = useState(fromServer);
  const [model, setModel] = useState(() => normalizeFeeModelId(cfg.paper_fee_model));
  const [mult, setMult] = useState(() => {
    const m = cfg.kalshi_fee_multiplier;
    if (m == null || m === "") return 1;
    const n = Number(m);
    return Number.isFinite(n) && n > 0 ? Math.min(10, Math.max(0.01, n)) : 1;
  });
  useEffect(() => {
    const r = cfg.paper_fee_bps;
    setBps(r != null && Number(r) > 0 ? Math.min(100, Math.max(1, Math.round(Number(r)))) : 0);
  }, [cfg.paper_fee_bps]);
  useEffect(() => {
    setModel(normalizeFeeModelId(cfg.paper_fee_model));
  }, [cfg.paper_fee_model]);
  useEffect(() => {
    const m = cfg.kalshi_fee_multiplier;
    if (m == null || m === "") setMult(1);
    else {
      const n = Number(m);
      setMult(Number.isFinite(n) && n > 0 ? Math.min(10, Math.max(0.01, n)) : 1);
    }
  }, [cfg.kalshi_fee_multiplier]);

  const save = () => {
    const patch: AnyObj = { paper_fee_model: model };
    if (model === "bps") {
      patch.paper_fee_bps = bps === 0 ? null : bps;
    } else {
      patch.paper_fee_bps = null;
    }
    if (model === "kalshi_taker" || model === "kalshi_maker") {
      patch.kalshi_fee_multiplier = mult;
    }
    void onSave(patch);
  };

  return (
    <div className="panel settings-nested-panel" style={{ marginTop: 16, padding: "12px 14px" }}>
      <h2
        className="section-tip"
        style={{ marginTop: 0 }}
        title="Paper / simulated trades only. Kalshi option uses the quadratic General Trading Fee (see Kalshi fee schedule PDF) with centicent rounding; basis points mode is a simple % of premium / proceeds."
      >
        Paper fees (sim)
      </h2>
      <p className="sub" style={{ marginTop: 6, fontSize: 12, lineHeight: 1.45 }}>
        <a href="https://kalshi.com/docs/kalshi-fee-schedule.pdf" target="_blank" rel="noreferrer">
          Kalshi fee schedule (PDF)
        </a>
        {" · "}
        <a href="https://docs.kalshi.com/getting_started/fee_rounding" target="_blank" rel="noreferrer">
          Fee rounding (docs)
        </a>
      </p>
      <div className="field" style={{ marginTop: 10 }}>
        <label className="section-tip" title="Taker matches IOC-style fills; maker uses ¼ taker coefficient.">
          Model
        </label>
        <select
          value={model}
          disabled={busy}
          style={{ width: "100%", marginTop: 4 }}
          onChange={(e) => setModel(e.target.value)}
        >
          <option value="kalshi_taker">Kalshi quadratic (taker)</option>
          <option value="kalshi_maker">Kalshi quadratic (maker)</option>
          <option value="bps">Custom basis points</option>
          <option value="none">No fees</option>
        </select>
      </div>
      {model === "kalshi_taker" || model === "kalshi_maker" ? (
        <div className="field" style={{ marginTop: 10 }}>
          <label className="section-tip" title="Series fee_multiplier from Kalshi API; 1.0 matches published table.">
            Fee multiplier <strong>{mult}</strong>
          </label>
          <input
            type="range"
            min={0.25}
            max={10}
            step={0.05}
            disabled={busy}
            value={mult}
            onChange={(e) => setMult(Number(e.target.value))}
            style={{ width: "100%" }}
          />
        </div>
      ) : null}
      {model === "bps" ? (
        <div className="field" style={{ marginTop: 10 }}>
          <label className="section-tip" title="Fee rate in basis points. 100 bps = 1.00%.">
            Fee rate: <strong>{bps === 0 ? "Off" : `${bps} bps`}</strong>
          </label>
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            disabled={busy}
            value={bps}
            onChange={(e) => setBps(Number(e.target.value))}
            style={{ width: "100%" }}
          />
        </div>
      ) : null}
      <button className="primary" style={{ marginTop: 12 }} disabled={busy} title="Writes paper fee settings to bot config." onClick={save}>
        Save paper fees
      </button>
    </div>
  );
}

export function RulesBandsSliders({
  rules,
  disabled,
  onSave,
}: {
  rules: AnyObj[];
  disabled: boolean;
  onSave: (r: AnyObj[]) => void;
}) {
  const [bands, setBands] = useState<AnyObj[]>(() => padRulesToThree(rules));
  useEffect(() => {
    setBands(padRulesToThree(rules));
  }, [rules]);

  const setBand = (i: number, patch: AnyObj) => {
    setBands((prev) => {
      const n = [...prev];
      n[i] = { ...n[i], ...patch };
      return n;
    });
  };

  return (
    <div style={{ marginTop: 16 }}>
      <h2
        className="section-tip"
        title="Up to three bands. A market matches when implied YES and minutes-to-close fall inside a band. Save writes the rules list to the server."
      >
        Rule bands (sliders)
      </h2>
      {bands.map((b, i) => (
        <div key={i} className="band-card">
          <div className="field">
            <label>Band name</label>
            <input
              type="text"
              value={String(b.name || "")}
              disabled={disabled}
              onChange={(e) => setBand(i, { name: e.target.value })}
            />
          </div>
          <div className="band-sliders">
            <div className="field">
              <label>Min YES % (0–100)</label>
              <input
                type="range"
                min={0}
                max={100}
                step={1}
                disabled={disabled}
                value={Math.round(Number(b.min_prob ?? 0) * 100)}
                onChange={(e) => setBand(i, { min_prob: Number(e.target.value) / 100 })}
              />
              <span className="sub">{Math.round(Number(b.min_prob ?? 0) * 100)}%</span>
            </div>
            <div className="field">
              <label>Max YES % (0–100)</label>
              <input
                type="range"
                min={0}
                max={100}
                step={1}
                disabled={disabled}
                value={Math.round(Number(b.max_prob ?? 1) * 100)}
                onChange={(e) => setBand(i, { max_prob: Number(e.target.value) / 100 })}
              />
              <span className="sub">{Math.round(Number(b.max_prob ?? 1) * 100)}%</span>
            </div>
            <div className="field">
              <label>Min minutes left</label>
              <input
                type="range"
                min={0}
                max={30}
                step={1}
                disabled={disabled}
                value={Math.round(Number(b.min_minutes_left ?? 0))}
                onChange={(e) => setBand(i, { min_minutes_left: Number(e.target.value) })}
              />
              <span className="sub">{Math.round(Number(b.min_minutes_left ?? 0))}</span>
            </div>
            <div className="field">
              <label>Max minutes left</label>
              <input
                type="range"
                min={0}
                max={30}
                step={1}
                disabled={disabled}
                value={Math.round(Number(b.max_minutes_left ?? 15))}
                onChange={(e) => setBand(i, { max_minutes_left: Number(e.target.value) })}
              />
              <span className="sub">{Math.round(Number(b.max_minutes_left ?? 15))}</span>
            </div>
          </div>
        </div>
      ))}
      <button
        className="primary"
        style={{ marginTop: 12 }}
        disabled={disabled}
        title="Normalize min/max pairs and persist the three bands as config.rules."
        onClick={() => {
          const fixed = bands.map((b) => {
            let minp = Number(b.min_prob) || 0;
            let maxp = Number(b.max_prob) || 1;
            if (minp > maxp) {
              const t = minp;
              minp = maxp;
              maxp = t;
            }
            let mn = Number(b.min_minutes_left) || 0;
            let mx = Number(b.max_minutes_left) || 15;
            if (mn > mx) {
              const t2 = mn;
              mn = mx;
              mx = t2;
            }
            return { ...b, min_prob: minp, max_prob: maxp, min_minutes_left: mn, max_minutes_left: mx };
          });
          onSave(mergeRulesFromSliders(rules, fixed, padNoRulesToThree(rules)));
        }}
      >
        Save rule bands
      </button>
    </div>
  );
}

export function RulesEditor({
  rules,
  disabled,
  onSave,
  onServerValidate,
}: {
  rules: AnyObj[];
  disabled: boolean;
  onSave: (r: AnyObj[]) => void;
  /** Optional: POST parsed rules to ``/api/config/validate-rules`` and show server message. */
  onServerValidate?: (r: AnyObj[]) => Promise<{ ok?: boolean; count?: number; detail?: string }>;
}) {
  const [txt, setTxt] = useState(() => JSON.stringify(rules, null, 2));

  useEffect(() => {
    setTxt(JSON.stringify(rules, null, 2));
  }, [rules]);

  return (
    <div style={{ marginTop: 16 }}>
      <h2 className="section-tip" title="Array of rules: each matches on implied YES probability and minutes-to-close within min/max bounds.">
        Probability / time rules (JSON)
      </h2>
      <textarea
        value={txt}
        disabled={disabled}
        onChange={(e) => setTxt(e.target.value)}
        title="Must be a JSON array of rule objects. Save parses and validates."
        rows={14}
        style={{
          width: "100%",
          marginTop: 10,
          borderRadius: 12,
          border: "1px solid var(--border)",
          background: "#0b1228",
          color: "var(--text)",
          padding: 10,
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
          fontSize: 12,
        }}
      />
      <div style={{ marginTop: 10, display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
        <button
          className="primary"
          disabled={disabled}
          title="Parse JSON and save as rules if valid."
          onClick={() => {
            try {
              const parsed = JSON.parse(txt);
              if (!Array.isArray(parsed)) throw new Error("rules must be an array");
              onSave(parsed);
            } catch (e: any) {
              window.alert(String(e?.message || e));
            }
          }}
        >
          Save rules
        </button>
        {onServerValidate ? (
          <button
            type="button"
            className="chart-tab"
            disabled={disabled}
            title="Validate with server Pydantic rules (same checks as save) without writing config."
            onClick={() => {
              void (async () => {
                try {
                  const parsed = JSON.parse(txt);
                  if (!Array.isArray(parsed)) throw new Error("rules must be an array");
                  const res = await onServerValidate(parsed);
                  window.alert(
                    res.detail
                      ? String(res.detail)
                      : `OK — ${res.count ?? parsed.length} rule(s) pass server validation.`,
                  );
                } catch (e: any) {
                  window.alert(String(e?.message || e));
                }
              })();
            }}
          >
            Validate on server
          </button>
        ) : null}
      </div>
    </div>
  );
}
