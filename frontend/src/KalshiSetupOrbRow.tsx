import type { ReactNode } from "react";

type AnyObj = Record<string, any>;

/**
 * One-row Kalshi API + getting-started status; hover each orb for checklist copy.
 * Lives in Settings; previously shown on the home hero.
 */
export function KalshiSetupOrbRow({ dash, cfg }: { dash: AnyObj | null; cfg: AnyObj }): ReactNode {
  const k = dash?.kalshi as AnyObj | undefined;
  if (!dash || !k) return null;
  const cred = (k.credentials || {}) as AnyObj;
  const credOk = Boolean(cred.api_key_id_configured) && Boolean(cred.private_key_configured);
  const pub = Boolean(k.public_ok);
  const priv = Boolean(k.private_ok);
  const simLive = Boolean(k.simulate_live);
  const writes = Boolean(k.order_writes_live);
  const poll = Boolean(k.polling_enabled);
  const pos = Number(k.position_count ?? 0);
  const ord = Number(k.resting_order_count ?? 0);
  const notes = k.portfolio_notes ? String(k.portfolio_notes) : "";

  const writeDetail = simLive
    ? "Live branch uses paper fills; Kalshi does not receive orders from Live."
    : writes
      ? "Live branch can POST limit orders when the Live engine is on and a rule matches."
      : priv
        ? "Authenticated but order posting is not enabled for this configuration."
        : "Fix authentication before enabling real orders.";

  let writeState: "ok" | "warn" | "bad";
  if (simLive) writeState = "ok";
  else if (writes) writeState = "warn";
  else if (priv) writeState = "warn";
  else writeState = "bad";

  const privateMissingTooltip = `Public data only — no Kalshi account linked. Quotes, series, and engine ticks use the public API; balance and exchange positions stay hidden until you add KALSHI_API_KEY_ID and your RSA private key to .env (optional for paper / signals).${k.private_error ? ` ${String(k.private_error)}` : ""}`;

  const orbs: {
    step: number;
    title: string;
    subtitle: string;
    hint: string;
    /** When set, used as the native tooltip (full diagnosis); otherwise step title + subtitle + hint. */
    tooltip?: string;
    state: "ok" | "warn" | "bad" | "fatal";
  }[] = [
    {
      step: 1,
      title: "Backend and this page are running",
      subtitle: "Dashboard",
      hint: "You already loaded the dashboard from npm run dev with the API proxy.",
      state: dash ? "ok" : "bad",
    },
    {
      step: 2,
      title: "Configure .env for Kalshi",
      subtitle: "Keys in .env",
      hint:
        cred.private_key_source === "file_missing"
          ? "KALSHI_PRIVATE_KEY_PATH points to a file that was not found."
          : "Copy .env.example to .env in the repo root; set KALSHI_API_KEY_ID and PEM path or KALSHI_PRIVATE_KEY_PEM.",
      state: credOk ? "ok" : "warn",
    },
    {
      step: 3,
      title: "Markets (public read)",
      subtitle: pub ? "Reachable" : "Unreachable",
      hint: pub
        ? "Kalshi public API responded OK. Used for quotes, series, and sim settlement checks."
        : "Cannot reach public Kalshi API. Check KALSHI_ENV and network.",
      state: pub ? "ok" : "bad",
    },
    {
      step: 4,
      title: "Portfolio (private read)",
      subtitle: priv ? `Signed in · ${pos} pos, ${ord} orders` : pub ? "Public only" : "Not signed in",
      hint: priv
        ? `Signed portfolio API. Loaded ${pos} position(s), ${ord} resting order(s).`
        : pub
          ? "Hover the red indicator for what is missing (keys in .env)."
          : "Cannot use portfolio API until public Kalshi read works.",
      tooltip: priv ? undefined : pub ? privateMissingTooltip : undefined,
      state: priv ? "ok" : pub ? "fatal" : "bad",
    },
    {
      step: 5,
      title: "Turn on an engine to stream markets into the bot",
      subtitle: poll ? "Polling on" : "Engines idle",
      hint: "Enable Live engine and/or labs so ticks run and markets_scanned updates.",
      state: poll ? "ok" : "warn",
    },
    {
      step: 6,
      title: "Live mode (simulate vs real)",
      subtitle: cfg.simulate ? "Paper (simulate)" : "Real $",
      hint: cfg.simulate
        ? "Simulate is on — Live branch will not POST orders to Kalshi."
        : "Real $ is on — Live branch can POST limit orders when the Live engine runs and a rule matches.",
      state: cfg.simulate ? "ok" : "warn",
    },
    {
      step: 7,
      title: "Live orders (write)",
      subtitle: simLive ? "Simulated" : writes ? "Real posts on" : "Blocked",
      hint: writeDetail,
      state: writeState,
    },
    {
      step: 8,
      title: "Portfolio notes",
      subtitle: notes ? "See tooltip" : "No warnings",
      hint: notes || "No extra portfolio notes from the last signed read.",
      state: notes ? "warn" : "ok",
    },
  ];

  return (
    <div
      className="kalshi-setup-orbs section-tip"
      role="list"
      title="Kalshi API (read / write) and getting started — hover each dot for status. Red ☐ = public data only (no signed account); hover for full detail."
      aria-label="Kalshi connection and setup checklist as compact status dots"
    >
      {orbs.map((o) => {
        const fullTitle = `${o.step}. ${o.title} · ${o.subtitle} — ${o.hint}`;
        const hoverTitle = o.tooltip ?? fullTitle;
        const tone = o.state;
        const glyph = o.state === "ok" ? "✓" : o.state === "fatal" ? "☐" : String(o.step);
        return (
          <span
            key={o.step}
            className={`kalshi-setup-orb kalshi-setup-orb--${tone} section-tip`}
            role="listitem"
            title={hoverTitle}
            aria-label={o.tooltip ? `${o.title}. ${o.subtitle}. ${o.tooltip}` : `${o.title}. ${o.subtitle}. ${o.hint}`}
          >
            {glyph}
          </span>
        );
      })}
    </div>
  );
}
