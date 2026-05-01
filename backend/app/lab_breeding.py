# LABS BREEDING — unified project version v0.4.15.001.
"""
Invisible internal GA for paper labs (no Claude, no UI changes on dashboard).

**lab_a–lab_d** remain the visible parent slots. Up to **six** parallel child engines (``lab_child_1``…``lab_child_6``)
each have their own SQLite branch and ``TradingEngine`` when assigned a genome. Breeders **B/C/D** mint offspring on
the 30-minute cadence into free child slots; **Lab A** never breeds and may adopt. Parent slots are refilled from
the strongest pool child (live child engine genome) or breeder crossover on hard death; soft cull respects a short
cooldown to limit churn.

**Lineage / death** caps and ``labs_breeding_log`` (including optional toast hints) ship in config / ``GET /api/optimizer/status``.

Replacement cooldown (5m) applies only to **soft cull** and **adoption** — not hard (zero equity) death.
"""

from __future__ import annotations

import copy
import datetime as dt
import logging
import random
from statistics import fmean, median
from typing import TYPE_CHECKING, Any, Callable
from uuid import uuid4

from .api_models import normalize_rules_list
from .branch_config import (
    ALL_CFG_LAB_KEYS,
    BRANCH_BREEDERS,
    BRANCH_CHILD_LABS,
    BRANCH_LAB_A,
    BRANCH_LABS,
    LAB_BREEDING_INTERNAL_MAX_SLOTS,
    LAB_BREEDING_MAX_CHILD_SLOTS,
    LAB_BREEDING_TRAIT_KEYS,
    MIN_SETTLED_FOR_ADOPTION_COMPARE,
    _lab_key_for_branch,
    clamp_balance_fraction_per_window,
)
from .breeding_engine import (
    BreedingEngine,
    clear_pending_lab_a_adoption,
    decline_pending_lab_a_adoption,
)

if TYPE_CHECKING:
    from .persistence import Store

logger = logging.getLogger("kalshibot.lab_breeding")


def _expand_parent_lab_after_replacement(lab_key: str, patch: dict[str, Any]) -> dict[str, Any]:
    """
    Hard/soft replacement and crossover write a fresh genome onto a parent lab or ``lab_child_*`` slot.

    ``expand_partial_lab_branch`` strips ``engine_running`` — simulation branches always tick.
    """
    from .persistence import expand_partial_lab_branch

    merged = dict(patch)
    return expand_partial_lab_branch(lab_key, merged)


def _toast_fields(*, family: str, **kwargs: Any) -> dict[str, Any]:
    # LABS BREEDING — birth vs death/cull toasts (only visible “labs” surface)
    out: dict[str, Any] = {"toast_id": str(uuid4()), "toast_family": family}
    for k, v in kwargs.items():
        if v is not None and v != "":
            out[k] = v
    return out


def _signals_sorted_desc(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(signals, key=lambda s: int(s.get("id") or 0), reverse=True)


ReplayBundleFn = Callable[..., dict[str, Any]]
ReplayOpenKwFn = Callable[..., dict[str, Any]]

LABS_BREEDING_VERSION = "0.4.15.001"
LAB_BREEDING_GENERATION_INTERVAL = dt.timedelta(minutes=30)
REPLACEMENT_COOLDOWN = dt.timedelta(minutes=5)
MIN_SETTLED_FOR_SOFT_CULL = 5
# Back-compat alias: trait keys live in ``branch_config.LAB_BREEDING_TRAIT_KEYS``.
TRAIT_KEYS = LAB_BREEDING_TRAIT_KEYS
DEATH_CHAMBER_CAP = 10
LINEAGE_HISTORY_CAP = 10
BREEDER_V3_FIT_WEIGHT = 0.77
BREEDER_V3_RECENT_WEIGHT = 0.23

# LABS BREEDING — radar chart + Optimizer/Breeder toggle (12 mood axes; derived from traits + sizing for UI only).
MOOD_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("aggressive", "Aggressive"),
    ("greedy", "Greedy"),
    ("sophisticated", "Sophisticated"),
    ("patient", "Patient"),
    ("calm", "Calm"),
    ("adaptive", "Adaptive"),
    ("exploratory", "Exploratory"),
    ("resilient", "Resilient"),
    ("optimistic", "Optimistic"),
    ("cautious", "Cautious"),
    ("ruthless", "Ruthless"),
    ("methodical", "Methodical"),
)


def _mood_pct(x: float) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        v = 0.0
    if v != v:
        v = 0.0
    return max(0.0, min(100.0, v))


def mood_vector_for_lab(
    lab: dict[str, Any], *, base_rules: list[Any] | None = None
) -> dict[str, float]:
    """Map breeding traits + lab knobs to twelve 0–100 mood axes (read-only / display)."""
    lab_o = dict(lab) if isinstance(lab, dict) else {}
    t = _read_traits(lab_o)
    ag = float(t.get("aggressiveness", 0.5))
    rt = float(t.get("risk_tolerance", 0.5))
    ad = float(t.get("adaptivity", 0.5))
    ex = float(t.get("exploration", 0.5))
    res = float(t.get("resilience", 0.5))
    try:
        bf = float(lab_o.get("balance_fraction_per_window") or 0.03)
    except (TypeError, ValueError):
        bf = 0.03
    try:
        wm = float(lab_o.get("window_minutes") or 15)
    except (TypeError, ValueError):
        wm = 15.0
    try:
        mhold = float(lab_o.get("min_hold_minutes_before_stop") or 30)
    except (TypeError, ValueError):
        mhold = 30.0
    try:
        stp = float(lab_o.get("stop_loss_trigger_pct") or -8.0)
    except (TypeError, ValueError):
        stp = -8.0
    stp_n = min(1.0, max(0.0, abs(stp) / 35.0))
    base = list(base_rules) if isinstance(base_rules, list) else []
    lr = (
        lab_o.get("rules")
        if isinstance(lab_o.get("rules"), list) and len(lab_o["rules"]) > 0
        else base
    )
    try:
        rules = normalize_rules_list(lr)
    except Exception:
        rules = normalize_rules_list(base or [])
    rules_u = min(1.0, len(rules) / 24.0)
    bf_u = min(1.0, max(0.0, bf / 0.18))
    wm_u = min(1.0, max(0.0, wm / 60.0))
    mh_u = min(1.0, max(0.0, mhold / 120.0))
    aggressive = _mood_pct(ag * 100.0)
    greedy = _mood_pct(bf_u * 58.0 + ag * 42.0)
    sophisticated = _mood_pct(rules_u * 72.0 + ad * 28.0)
    patient = _mood_pct(mh_u * 52.0 + wm_u * 38.0 + (1.0 - ag) * 10.0)
    calm = _mood_pct(res * 62.0 + (1.0 - ag) * 22.0 + (1.0 - ex) * 16.0)
    adaptive = _mood_pct(ad * 100.0)
    exploratory = _mood_pct(ex * 100.0)
    resilient = _mood_pct(res * 100.0)
    optimistic = _mood_pct(rt * 100.0)
    cautious = _mood_pct((1.0 - 0.62 * ag - 0.28 * ex) * 100.0)
    ruthless = _mood_pct(ag * 58.0 + (1.0 - res) * 32.0 + bf_u * 28.0 + stp_n * 12.0)
    methodical = _mood_pct(ad * 48.0 + rules_u * 100.0 * 0.42 + (1.0 - ex) * 18.0)
    return {
        "aggressive": aggressive,
        "greedy": greedy,
        "sophisticated": sophisticated,
        "patient": patient,
        "calm": calm,
        "adaptive": adaptive,
        "exploratory": exploratory,
        "resilient": resilient,
        "optimistic": optimistic,
        "cautious": cautious,
        "ruthless": ruthless,
        "methodical": methodical,
    }


def _personality_branch_label(cfg_key: str) -> str:
    if cfg_key == "lab_a":
        return "Lab A"
    if cfg_key == "lab_b":
        return "Lab B"
    if cfg_key == "lab_c":
        return "Lab C"
    if cfg_key == "lab_d":
        return "Lab D"
    if cfg_key.startswith("lab_child_") and cfg_key[10:].isdigit():
        return f"Child {cfg_key[10:]}"
    return cfg_key


def build_labs_breeding_personality_radar(cfg: dict[str, Any]) -> dict[str, Any]:
    """Payload for Settings **Breeder** radar (parents + child slots)."""
    base_rules = cfg.get("rules") if isinstance(cfg.get("rules"), list) else []
    series: list[dict[str, Any]] = []
    for lk in ALL_CFG_LAB_KEYS:
        lab = cfg.get(lk) if isinstance(cfg.get(lk), dict) else {}
        moods = mood_vector_for_lab(lab, base_rules=base_rules)
        series.append(
            {
                "key": lk,
                "branch": lk,
                "label": _personality_branch_label(lk),
                "engine_running": bool(lab.get("engine_running")),
                "moods": {k: round(float(moods[k]), 1) for k, _ in MOOD_DIMENSIONS},
            }
        )
    rows: list[dict[str, Any]] = []
    for mk, mlabel in MOOD_DIMENSIONS:
        row: dict[str, Any] = {"subject": mlabel, "subject_key": mk}
        for s in series:
            row[str(s["key"])] = round(float(s["moods"].get(mk, 0.0)), 1)
        rows.append(row)
    return {
        "dimensions": [{"key": k, "label": lb} for k, lb in MOOD_DIMENSIONS],
        "series": series,
        "rows": rows,
    }


def _parse_iso_utc(s: str) -> dt.datetime | None:
    t = str(s or "").strip()
    if not t:
        return None
    try:
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        d = dt.datetime.fromisoformat(t)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except Exception:
        return None


def _record_replacement_cooldown(oc: dict[str, Any], end_iso: str) -> None:
    now = _parse_iso_utc(end_iso)
    if now is None:
        return
    oc["labs_breeding_replace_cooldown_until"] = (
        (now + REPLACEMENT_COOLDOWN).replace(microsecond=0).isoformat()
    )


def _replacement_cooldown_active(oc: dict[str, Any], end_iso: str) -> bool:
    until = _parse_iso_utc(str(oc.get("labs_breeding_replace_cooldown_until") or ""))
    now = _parse_iso_utc(end_iso)
    if until is None or now is None:
        return False
    return now < until


async def _last_equity_cents(store: Store, branch: str) -> int | None:
    rows = await store.equity_series(limit=1, branch=branch)
    if not rows or not isinstance(rows[-1], dict):
        return None
    try:
        return int(rows[-1].get("equity_cents") or 0)
    except (TypeError, ValueError):
        return None


def _lab_dict(cfg: dict[str, Any], branch: str) -> dict[str, Any]:
    lk = _lab_key_for_branch(branch)
    if not lk:
        return {}
    raw = cfg.get(lk)
    return dict(raw) if isinstance(raw, dict) else {}


def _rules_for_lab(
    cfg: dict[str, Any], lab_o: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base = cfg.get("rules") if isinstance(cfg.get("rules"), list) else []
    lr = (
        lab_o.get("rules")
        if isinstance(lab_o.get("rules"), list) and len(lab_o["rules"]) > 0
        else base
    )
    try:
        rules = normalize_rules_list(lr)
    except Exception:
        rules = normalize_rules_list(base or [])
    return lab_o, rules


def _default_traits() -> dict[str, float]:
    return {k: 0.9 for k in TRAIT_KEYS}


def _read_traits(lab_o: dict[str, Any]) -> dict[str, float]:
    raw = lab_o.get("_labs_breeding_traits")
    if not isinstance(raw, dict):
        return _default_traits()
    out: dict[str, float] = {}
    for k in TRAIT_KEYS:
        try:
            out[k] = max(0.08, min(0.99, float(raw.get(k, 0.9))))
        except (TypeError, ValueError):
            out[k] = 0.9
    return out


def _traits_birth_summary(traits: dict[str, float]) -> str:
    human = {
        "aggressiveness": "aggressiveness",
        "risk_tolerance": "risk tolerance",
        "adaptivity": "adaptivity",
        "exploration": "exploration",
        "resilience": "resilience",
    }
    ranked = sorted(
        ((float(traits.get(k, 0.0)), k) for k in TRAIT_KEYS), key=lambda x: -x[0]
    )
    if not ranked:
        return "a competitive trait mix"
    top = [k for _, k in ranked[:2]]
    if len(top) == 1:
        return f"strong {human.get(top[0], top[0])}"
    return f"high {human.get(top[0], top[0])} & {human.get(top[1], top[1])}"


def _competitive_trait_breed(
    rng: random.Random, parent: dict[str, float], elite: dict[str, float]
) -> dict[str, float]:
    out: dict[str, float] = {}
    for k in TRAIT_KEYS:
        base = 0.28 * float(parent.get(k, 0.9)) + 0.72 * float(elite.get(k, 0.9))
        skew = rng.uniform(0.16, 0.36)
        noise = rng.uniform(-0.01, 0.22)
        out[k] = max(0.08, min(0.99, base + skew + noise))
    return out


def _apply_competitive_traits(child: dict[str, Any], traits: dict[str, float]) -> None:
    child["_labs_breeding_traits"] = {k: float(traits.get(k, 0.9)) for k in TRAIT_KEYS}
    ag = float(traits.get("aggressiveness", 0.9))
    rt = float(traits.get("risk_tolerance", 0.9))
    res = float(traits.get("resilience", 0.9))
    try:
        bf = float(child.get("balance_fraction_per_window") or 0.03)
        child["balance_fraction_per_window"] = clamp_balance_fraction_per_window(
            bf * (0.69 + 0.56 * ag)
        )
    except (TypeError, ValueError):
        child["balance_fraction_per_window"] = clamp_balance_fraction_per_window(
            0.03 * (0.69 + 0.56 * ag)
        )
    try:
        wm = int(child.get("window_minutes") or 15)
        child["window_minutes"] = max(1, min(1440, wm - int((1.0 - rt) * 14)))
    except (TypeError, ValueError):
        pass
    try:
        st = float(child.get("stop_loss_trigger_pct") or -8.0)
        adj = -1.7 * (1.0 - res) + 1.22 * (ag - 0.5)
        child["stop_loss_trigger_pct"] = max(-35.0, min(-2.0, st + adj))
    except (TypeError, ValueError):
        pass


def _replay_metrics_for_branch(
    *,
    settled: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    include_fees: bool,
    lab_overlay: dict[str, Any],
    full_cfg: dict[str, Any],
    branch: str,
    replay_bundle: ReplayBundleFn,
    open_kw: ReplayOpenKwFn,
    at_iso: str,
    trades: list[dict[str, Any]],
    max_rows: int,
) -> dict[str, Any]:
    """
    Fitness inputs for breeding and adoption: **same replay bundle** as the main optimizer path.

    ``include_fees`` mirrors ``optimizer.include_fees_in_score``—when true, ``replay_bundle`` applies Kalshibot's
    **paper** fee model (quadratic / flat bps / none from branch + root config). That model is **consistent across
    sim trading and replay** but is **not** guaranteed to match every nuance of Kalshi's live exchange fee schedule
    (contract counts, promotions, etc.). Use scores to **rank** genomes under one internal ruler, not as published exchange PnL.
    """
    tail = settled[-max_rows:] if len(settled) > max_rows else settled
    try:
        return replay_bundle(
            tail,
            rules,
            _signals_sorted_desc(signals),
            include_fees_in_score=include_fees,
            max_rows=max_rows,
            branch_trading_cfg=lab_overlay,
            full_cfg=full_cfg,
            branch=branch,
            **open_kw(full_cfg, at_iso=at_iso, branch=branch, trades=trades),
        )
    except Exception:
        return {"score_dollars": 0.0, "advanced_metrics": {}}


def _fitness_for_branch(
    *,
    settled: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    include_fees: bool,
    lab_overlay: dict[str, Any],
    full_cfg: dict[str, Any],
    branch: str,
    replay_bundle: ReplayBundleFn,
    open_kw: ReplayOpenKwFn,
    at_iso: str,
    trades: list[dict[str, Any]],
    max_rows: int,
) -> float:
    fb = _replay_metrics_for_branch(
        settled=settled,
        rules=rules,
        signals=signals,
        include_fees=include_fees,
        lab_overlay=lab_overlay,
        full_cfg=full_cfg,
        branch=branch,
        replay_bundle=replay_bundle,
        open_kw=open_kw,
        at_iso=at_iso,
        trades=trades,
        max_rows=min(120, max_rows),
    )
    return float(fb.get("score_dollars") or 0.0)


def _mutate_frac(rng: random.Random, a: float, b: float) -> float:
    m = 0.5 * (float(a) + float(b))
    m *= 1.0 + rng.uniform(-0.06, 0.06)
    return max(0.0001, min(1.0, m))


def _mutate_win(rng: random.Random, a: int, b: int) -> int:
    v = int(round(0.5 * (float(a) + float(b)))) + rng.randint(-2, 2)
    return max(1, min(1440, v))


def _mutate_paper(rng: random.Random, a: int, b: int) -> int:
    base = max(int(a), int(b), 50_000)
    jitter = rng.randint(-25_000, 50_000)
    return max(100_000, min(5_000_000, base + jitter))


def _blend_rules(
    r1: list[dict[str, Any]],
    r2: list[dict[str, Any]],
    rng: random.Random,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    n = min(len(r1), len(r2), 24)
    for i in range(n):
        a, b = dict(r1[i]), dict(r2[i])
        if rng.random() < 0.45:
            out.append(b if rng.random() < 0.5 else a)
            continue
        c = copy.deepcopy(a)
        for key in ("min_prob", "max_prob"):
            if key in a and key in b:
                try:
                    va, vb = float(a[key]), float(b[key])
                    c[key] = round(
                        max(0.0, min(1.0, 0.5 * (va + vb) + rng.uniform(-0.02, 0.02))),
                        4,
                    )
                except (TypeError, ValueError):
                    pass
        if rng.random() < 0.12 and "name" in c:
            c["name"] = f"{c.get('name', 'rule')}_b{rng.randint(10, 99)}"
        out.append(c)
    if not out and r1:
        out = copy.deepcopy(r1[:24])
    try:
        return normalize_rules_list(out)
    except Exception:
        return normalize_rules_list(r1 or r2 or [])


def _blend_filters(
    p1: dict[str, Any], p2: dict[str, Any], rng: random.Random
) -> dict[str, Any]:
    o = copy.deepcopy(p1)
    if rng.random() < 0.35:
        o["only_yes_subtitle_contains"] = (
            p2.get("only_yes_subtitle_contains")
            or p1.get("only_yes_subtitle_contains")
            or ""
        )
    elif rng.random() < 0.2:
        s1 = str(p1.get("exclude_yes_subtitle_contains") or "").strip()
        s2 = str(p2.get("exclude_yes_subtitle_contains") or "").strip()
        o["exclude_yes_subtitle_contains"] = ",".join(
            {x.strip() for x in (s1 + "," + s2).split(",") if x.strip()}
        )[:400]
    return o


def _traits_from_two_parents(
    cfg: dict[str, Any],
    pa: str,
    pb: str,
    rng: random.Random,
) -> tuple[dict[str, float], list[str]]:
    t1 = _read_traits(_lab_dict(cfg, pa))
    t2 = _read_traits(_lab_dict(cfg, pb))
    elite = {k: 0.5 * (t1[k] + t2[k]) for k in TRAIT_KEYS}
    out = _competitive_trait_breed(rng, t1, elite)
    mutated: list[str] = []
    for k in TRAIT_KEYS:
        base = 0.5 * (float(t1.get(k, 0.9)) + float(t2.get(k, 0.9)))
        if abs(float(out.get(k, 0.9)) - base) >= 0.07:
            mutated.append(k)
    return out, mutated


def _recent_perf_momentum(settled: list[dict[str, Any]]) -> float:
    """Small recent-performance signal for breeder tournament scoring."""
    if not settled:
        return 0.0
    tail = settled[-8:]
    pnl_d = 0.0
    for t in tail:
        try:
            pnl_d += float(t.get("pnl_cents") or 0.0) / 100.0
        except (TypeError, ValueError):
            continue
    # Compact, bounded momentum to avoid dominating replay fitness.
    return max(-1.0, min(1.0, pnl_d / 60.0))


def _norm_by_range(v: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.5
    return max(0.0, min(1.0, (v - lo) / (hi - lo)))


def _selection_mode_for_rank(rank: int, rng: random.Random) -> tuple[int, str]:
    """
    Tournament mode:
    - top rank: 70%
    - second: 20%
    - random top-3: 10%
    """
    r = rng.random()
    if r < 0.70:
        return 0, "elite_pick_70"
    if r < 0.90:
        return min(1, rank), "runner_up_20"
    return rng.randint(0, min(2, rank)), "diversity_random_10"


def _tournament_select_parent(
    *,
    candidates: list[str],
    fitness_by_br: dict[str, float],
    settled_by_br: dict[str, list[dict[str, Any]]],
    rng: random.Random,
) -> tuple[str, str, list[dict[str, Any]]]:
    """
    Parent selection:
    rank candidates by weighted replay fitness + recent momentum, then select by 70/20/10 rule.
    Returns selected branch, explainable selection reason, and top-3 ranked entries.
    """
    ranked_raw: list[dict[str, Any]] = []
    for br in candidates:
        fit = float(fitness_by_br.get(br, 0.0))
        mom = _recent_perf_momentum(settled_by_br.get(br) or [])
        ranked_raw.append({"branch": br, "fitness": fit, "momentum": mom})
    fit_lo = min((x["fitness"] for x in ranked_raw), default=0.0)
    fit_hi = max((x["fitness"] for x in ranked_raw), default=1.0)
    mom_lo = min((x["momentum"] for x in ranked_raw), default=-1.0)
    mom_hi = max((x["momentum"] for x in ranked_raw), default=1.0)
    for row in ranked_raw:
        fit_n = _norm_by_range(float(row["fitness"]), fit_lo, fit_hi)
        mom_n = _norm_by_range(float(row["momentum"]), mom_lo, mom_hi)
        row["score"] = BREEDER_V3_FIT_WEIGHT * fit_n + BREEDER_V3_RECENT_WEIGHT * mom_n
    ranked = sorted(ranked_raw, key=lambda x: float(x["score"]), reverse=True)[:3]
    if not ranked:
        # Defensive fallback; caller ensures candidates is non-empty.
        b = candidates[0]
        return (
            b,
            "fallback single candidate",
            [{"branch": b, "fitness": 0.0, "momentum": 0.0, "score": 0.0}],
        )
    idx, mode = _selection_mode_for_rank(len(ranked) - 1, rng)
    idx = max(0, min(len(ranked) - 1, idx))
    picked = ranked[idx]
    reason = f"{mode}: top-3 tournament by replay fitness + recent momentum"
    return str(picked["branch"]), reason, ranked


def _trait_complementarity_score(cfg: dict[str, Any], pa: str, pb: str) -> float:
    t1 = _read_traits(_lab_dict(cfg, pa))
    t2 = _read_traits(_lab_dict(cfg, pb))
    vals: list[float] = []
    for k in TRAIT_KEYS:
        diff = abs(float(t1.get(k, 0.9)) - float(t2.get(k, 0.9)))
        # Peak complementarity around moderate differences (not identical, not chaotic opposite).
        score = 1.0 - abs(diff - 0.35) / 0.35
        vals.append(max(0.0, min(1.0, score)))
    if not vals:
        return 50.0
    return round(100.0 * (sum(vals) / len(vals)), 1)


def _has_repeated_similar_culls(oc: dict[str, Any]) -> bool:
    dc = [
        x for x in (oc.get("labs_breeding_death_chamber") or []) if isinstance(x, dict)
    ]
    if len(dc) < 3:
        return False
    reasons = [
        str(x.get("reason") or "").strip().lower()
        for x in dc[:5]
        if str(x.get("reason") or "").strip()
    ]
    if len(reasons) < 3:
        return False
    first = reasons[0]
    return sum(1 for r in reasons if r == first) >= 3


def _trait_badges(traits: dict[str, float], n: int = 2) -> list[str]:
    human = {
        "aggressiveness": "Aggressive",
        "risk_tolerance": "RiskTolerant",
        "adaptivity": "Adaptive",
        "exploration": "Exploratory",
        "resilience": "Resilient",
    }
    ranked = sorted(
        ((float(traits.get(k, 0.0)), k) for k in TRAIT_KEYS), key=lambda x: -x[0]
    )
    return [human.get(k, k) for _, k in ranked[: max(1, n)]]


def _breeder_reason_text(
    *,
    parent_a: str,
    parent_b: str,
    select_reason_a: str,
    select_reason_b: str,
    synergy_score: float,
    repeated_culls: bool,
    fitness_by_br: dict[str, float],
    parent_c: str | None = None,
    select_reason_c: str = "",
) -> tuple[str, str]:
    fa = float(fitness_by_br.get(parent_a, 0.0))
    fb = float(fitness_by_br.get(parent_b, 0.0))
    fc = float(fitness_by_br.get(parent_c, 0.0)) if parent_c else 0.0
    if repeated_culls:
        short = "diversity boost after repeated similar culls"
    elif synergy_score >= 72.0:
        short = "highest fitness synergy + complementary aggression trait"
    elif fa > 0 and fb > 0:
        short = "strong recent lineage momentum"
    else:
        short = "balanced replay fitness with diversity guardrails"
    if parent_c:
        short = short + " + tri-parent blend"
    trip = f", C={parent_c} fit={fc:.3f}" if parent_c else ""
    sel_c = f"; selectC={select_reason_c}" if parent_c and select_reason_c else ""
    full = (
        f"{short} (A={parent_a} fit={fa:.3f}, B={parent_b} fit={fb:.3f}{trip}, "
        f"synergy={synergy_score:.1f}/100; selectA={select_reason_a}; selectB={select_reason_b}{sel_c})"
    )
    return short, full


def _breed_child(
    *,
    victim_branch: str,
    parent_a: str,
    parent_b: str,
    cfg: dict[str, Any],
    rng: random.Random,
    competitive_traits: dict[str, float] | None = None,
    mutated_traits: list[str] | None = None,
    breeder_reason_short: str = "",
    breeder_reason_full: str = "",
    synergy_score: float = 0.0,
    parent_ids: list[str] | None = None,
    parent_fitness: dict[str, float] | None = None,
) -> dict[str, Any]:
    p1 = _lab_dict(cfg, parent_a)
    p2 = _lab_dict(cfg, parent_b)
    base_rules = cfg.get("rules") if isinstance(cfg.get("rules"), list) else []
    r1 = list(p1.get("rules") or base_rules or [])
    r2 = list(p2.get("rules") or base_rules or [])
    child = copy.deepcopy(p1)
    child["balance_fraction_per_window"] = _mutate_frac(
        rng,
        float(
            p1.get("balance_fraction_per_window")
            or cfg.get("balance_fraction_per_window")
            or 0.03
        ),
        float(
            p2.get("balance_fraction_per_window")
            or cfg.get("balance_fraction_per_window")
            or 0.03
        ),
    )
    child["window_minutes"] = _mutate_win(
        rng,
        int(p1.get("window_minutes") or cfg.get("window_minutes") or 15),
        int(p2.get("window_minutes") or cfg.get("window_minutes") or 15),
    )
    child["paper_balance_cents"] = _mutate_paper(
        rng,
        int(p1.get("paper_balance_cents") or cfg.get("paper_balance_cents") or 500_000),
        int(p2.get("paper_balance_cents") or cfg.get("paper_balance_cents") or 500_000),
    )
    child["rules"] = _blend_rules(r1, r2, rng)
    child = {**_blend_filters(p1, p2, rng), **child}
    child.pop("paper_lifetime_basis_cents", None)
    child["auto_reset_paper_on_tick_failure"] = bool(
        rng.random() < 0.5
        if p1.get("auto_reset_paper_on_tick_failure")
        != p2.get("auto_reset_paper_on_tick_failure")
        else p1.get("auto_reset_paper_on_tick_failure", False)
    )
    if competitive_traits is not None:
        traits = competitive_traits
    else:
        traits, auto_mut = _traits_from_two_parents(cfg, parent_a, parent_b, rng)
        if not mutated_traits:
            mutated_traits = auto_mut
    _apply_competitive_traits(child, traits)
    inherited_rules_count = (
        len(child.get("rules") or []) if isinstance(child.get("rules"), list) else 0
    )
    child["_labs_breeding_origin"] = {
        "victim": victim_branch,
        "parents": [parent_a, parent_b],
        "parent_ids": list(parent_ids or [parent_a, parent_b]),
        "parent_fitness": dict(parent_fitness or {}),
        "inherited_rules_count": int(inherited_rules_count),
        "mutated_traits": list(mutated_traits or []),
        "breeder_reason": breeder_reason_full or breeder_reason_short,
        "breeder_reason_short": breeder_reason_short,
        "synergy_score": float(synergy_score),
        "fitness_delta_vs_parents": None,  # computed after replay fitness is known
        "gen": rng.randint(1, 999_999),
    }
    return child


def append_breeding_log(
    oc: dict[str, Any], entry: dict[str, Any], cap: int = 64
) -> None:
    seq = int(oc.get("labs_breeding_event_seq") or 0) + 1
    oc["labs_breeding_event_seq"] = seq
    if "seq" not in entry:
        entry["seq"] = seq
    log = oc.get("labs_breeding_log")
    hist = list(log) if isinstance(log, list) else []
    hist.insert(0, entry)
    oc["labs_breeding_log"] = hist[:cap]


def _append_lineage_history(oc: dict[str, Any], row: dict[str, Any]) -> None:
    seq = int(oc.get("labs_breeding_event_seq") or 0) + 1
    oc["labs_breeding_event_seq"] = seq
    if "seq" not in row:
        row["seq"] = seq
    h = [
        x
        for x in (oc.get("labs_breeding_lineage_history") or [])
        if isinstance(x, dict)
    ]
    h.insert(0, row)
    oc["labs_breeding_lineage_history"] = h[:LINEAGE_HISTORY_CAP]


def _death_chamber_append(oc: dict[str, Any], row: dict[str, Any]) -> None:
    seq = int(oc.get("labs_breeding_event_seq") or 0) + 1
    oc["labs_breeding_event_seq"] = seq
    if "seq" not in row:
        row["seq"] = seq
    dc = [
        x for x in (oc.get("labs_breeding_death_chamber") or []) if isinstance(x, dict)
    ]
    dc.insert(0, row)
    oc["labs_breeding_death_chamber"] = dc[:DEATH_CHAMBER_CAP]


def build_labs_breeding_tree_snapshot(
    oc: dict[str, Any], cfg: dict[str, Any]
) -> dict[str, Any]:
    """
    Unified-version tree payload for the dashboard.
    Returns normalized family nodes + edges and recent event summary so the UI can render
    a stable growth view without guessing from loosely-typed log rows.
    """
    children = [
        x for x in (oc.get("labs_breeding_children") or []) if isinstance(x, dict)
    ]
    lineage = [
        x
        for x in (oc.get("labs_breeding_lineage_history") or [])
        if isinstance(x, dict)
    ]
    culls = [
        x for x in (oc.get("labs_breeding_death_chamber") or []) if isinstance(x, dict)
    ]
    logs = [x for x in (oc.get("labs_breeding_log") or []) if isinstance(x, dict)]
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    parent_meta: dict[str, dict[str, Any]] = {}
    for c in children:
        origin = c.get("origin") if isinstance(c.get("origin"), dict) else {}
        if (
            not origin
            and isinstance(c.get("lab"), dict)
            and isinstance(c["lab"].get("_labs_breeding_origin"), dict)
        ):
            origin = c["lab"]["_labs_breeding_origin"]
        pids = (
            origin.get("parent_ids")
            if isinstance(origin.get("parent_ids"), list)
            else []
        )
        for p in pids:
            ps = str(p).strip().lower()
            if ps in BRANCH_BREEDERS and ps not in parent_meta:
                parent_meta[ps] = {
                    "selection_reason": str(
                        origin.get("breeder_reason_short")
                        or origin.get("breeder_reason")
                        or ""
                    ),
                    "selection_reason_full": str(origin.get("breeder_reason") or ""),
                    "fitness": float((origin.get("parent_fitness") or {}).get(ps, 0.0))
                    if isinstance(origin.get("parent_fitness"), dict)
                    else 0.0,
                }

    # Parent hubs (visible labs) and child slot hubs.
    for p in BRANCH_BREEDERS:
        lab = _lab_dict(cfg, p)
        pf = parent_meta.get(p, {})
        nodes.append(
            {
                "id": p,
                "kind": "parent",
                "label": p.replace("_", " ").title(),
                "branch": p,
                "fitness": round(float(pf.get("fitness", 0.0)), 4),
                "selection_reason": str(pf.get("selection_reason") or ""),
                "selection_reason_full": str(pf.get("selection_reason_full") or ""),
                "engine_running": bool(lab.get("engine_running")),
            }
        )
    nodes.append(
        {
            "id": BRANCH_LAB_A,
            "kind": "staging",
            "label": "Lab A (adopt)",
            "branch": BRANCH_LAB_A,
        }
    )
    for slot in BRANCH_CHILD_LABS:
        nodes.append(
            {
                "id": slot,
                "kind": "slot",
                "label": slot.replace("_", " ").title(),
                "branch": slot,
            }
        )

    for c in children:
        cid = str(c.get("id") or "").strip()
        if not cid:
            continue
        nid = f"child:{cid}"
        parent = str(c.get("parent") or "").strip().lower()
        slot = str(c.get("engine_branch") or "").strip().lower()
        fit = float(c.get("replay_fitness") or 0.0)
        origin = c.get("origin") if isinstance(c.get("origin"), dict) else {}
        if (
            not origin
            and isinstance(c.get("lab"), dict)
            and isinstance(c["lab"].get("_labs_breeding_origin"), dict)
        ):
            origin = c["lab"]["_labs_breeding_origin"]
        parent_ids = (
            origin.get("parent_ids")
            if isinstance(origin.get("parent_ids"), list)
            else []
        )
        parent_labels = [
            str(x).replace("_", " ").title() for x in parent_ids[:3] if str(x).strip()
        ]
        inherited_summary = origin.get("inherited_traits_summary")
        if not isinstance(inherited_summary, list):
            traits = c.get("traits") if isinstance(c.get("traits"), dict) else {}
            inherited_summary = _trait_badges(traits, 2)
        fit_delta = origin.get("fitness_delta_vs_parents")
        try:
            fit_delta_f = float(fit_delta) if fit_delta is not None else 0.0
        except (TypeError, ValueError):
            fit_delta_f = 0.0
        nodes.append(
            {
                "id": nid,
                "kind": "child",
                "label": f"{cid[:8]}…",
                "child_id": cid,
                "parent": parent,
                "slot": slot,
                "born_at": str(c.get("born_at") or ""),
                "fitness": round(fit, 4),
                "fitness_delta": round(fit_delta_f, 4),
                "breeder_reason_short": str(
                    origin.get("breeder_reason_short")
                    or origin.get("breeder_reason")
                    or ""
                ),
                "breeder_reason_full": str(origin.get("breeder_reason") or ""),
                "synergy_score": float(origin.get("synergy_score") or 0.0),
                "inherited_traits_summary": inherited_summary[:4],
                "parent_labels": parent_labels[:3],
                "parent_ids": parent_ids[:3],
                "mutated_traits": list(origin.get("mutated_traits") or [])[:6]
                if isinstance(origin.get("mutated_traits"), list)
                else [],
                "inherited_rules_count": int(origin.get("inherited_rules_count") or 0),
                "traits": c.get("traits") if isinstance(c.get("traits"), dict) else {},
            }
        )
        if parent in BRANCH_BREEDERS:
            edges.append({"from": parent, "to": nid, "kind": "birth"})
        for pid in parent_ids[:3]:
            ps = str(pid).strip().lower()
            if ps in BRANCH_BREEDERS and ps != parent:
                edges.append({"from": ps, "to": nid, "kind": "birth"})
        if slot in BRANCH_CHILD_LABS:
            edges.append({"from": nid, "to": slot, "kind": "assignment"})

    # Adoption edges (child -> Lab A) from lineage / logs.
    for row in lineage[:80]:
        kind = str(row.get("kind") or "").lower()
        if "adopt" not in kind:
            continue
        cid = str(row.get("child_id") or "").strip()
        if not cid:
            continue
        edges.append(
            {
                "from": f"child:{cid}",
                "to": BRANCH_LAB_A,
                "kind": "adoption",
                "at": str(row.get("at") or ""),
                "seq": int(row.get("seq") or 0),
            }
        )

    return {
        "version": LABS_BREEDING_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "generation_index": int(oc.get("labs_breeding_generation_index") or 0),
        "event_seq": int(oc.get("labs_breeding_event_seq") or 0),
        "summary": {
            "children_in_pool": len(children),
            "death_chamber_n": len(culls),
            "lineage_n": len(lineage),
            "log_n": len(logs),
            "last_generation_iso": str(
                oc.get("labs_breeding_last_generation_iso") or ""
            ),
            "replace_cooldown_until": str(
                oc.get("labs_breeding_replace_cooldown_until") or ""
            ),
        },
        "nodes": nodes,
        "edges": edges,
        "recent_events": logs[:24],
    }


def _migrate_legacy_lineages(oc: dict[str, Any], *, end_iso: str) -> None:
    leg = oc.pop("labs_breeding_lineages", None)
    if not isinstance(leg, list) or not leg:
        return
    for row in leg[:24]:
        if not isinstance(row, dict):
            continue
        _death_chamber_append(
            oc,
            {
                "culled_at": end_iso,
                "reason": "legacy_lineage",
                "snapshot": {
                    k: row.get(k)
                    for k in ("from_parent", "birth_fitness", "id", "born_at")
                    if k in row
                },
            },
        )


def _child_row_effective_lab(
    c: dict[str, Any], cfg: dict[str, Any]
) -> dict[str, Any] | None:
    if isinstance(c.get("lab"), dict):
        return c["lab"]
    eb = str(c.get("engine_branch") or "").strip()
    if eb and isinstance(cfg.get(eb), dict):
        return cfg[eb]
    return None


def _sorted_child_pool(oc: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    for c in oc.get("labs_breeding_children") or []:
        if not isinstance(c, dict):
            continue
        if _child_row_effective_lab(c, cfg) is not None:
            pool.append(c)
    pool.sort(key=lambda x: -float(x.get("replay_fitness", 0.0)))
    return pool


def _engine_branches_in_pool(oc: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for c in oc.get("labs_breeding_children") or []:
        if not isinstance(c, dict):
            continue
        eb = str(c.get("engine_branch") or "").strip()
        if eb in BRANCH_CHILD_LABS:
            out.add(eb)
    return out


def _pick_child_slot(oc: dict[str, Any]) -> str | None:
    taken = _engine_branches_in_pool(oc)
    for sl in BRANCH_CHILD_LABS:
        if sl not in taken:
            return sl
    return None


async def _clear_child_engine_slot(
    store: Store, cfg: dict[str, Any], slot: str, end_iso: str
) -> None:
    from .persistence import default_bot_config, expand_partial_lab_branch

    if slot not in BRANCH_CHILD_LABS:
        return
    base = dict((default_bot_config() or {}).get(slot) or {})
    cfg[slot] = expand_partial_lab_branch(slot, base)
    try:
        await store.reset_trading_data(backup=False, branch=slot)
    except Exception as e:
        logger.warning("clear child slot reset failed slot=%s err=%s", slot, e)
    _ = end_iso


def _set_child_pool(oc: dict[str, Any], pool: list[dict[str, Any]]) -> None:
    oc["labs_breeding_children"] = pool


def _child_replay_fitness(
    *,
    child_lab: dict[str, Any],
    eval_branch: str,
    cfg: dict[str, Any],
    trades: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    include_fees: bool,
    replay_bundle: ReplayBundleFn,
    open_kw: ReplayOpenKwFn,
    at_iso: str,
    max_rows: int,
) -> float:
    st = [
        t
        for t in trades
        if str(t.get("status") or "").lower() == "settled"
        and t.get("pnl_cents") is not None
    ]
    _, rules = _rules_for_lab(cfg, child_lab)
    return _fitness_for_branch(
        settled=st,
        rules=rules,
        signals=signals,
        include_fees=include_fees,
        lab_overlay=child_lab,
        full_cfg=cfg,
        branch=eval_branch,
        replay_bundle=replay_bundle,
        open_kw=open_kw,
        at_iso=at_iso,
        trades=trades,
        max_rows=max_rows,
    )


def _pick_mate(parent: str, fitness_by_br: dict[str, float]) -> str:
    others = [b for b in BRANCH_BREEDERS if b != parent]
    return max(others, key=lambda b: float(fitness_by_br.get(b, 0.0)))


def _breeder_parent_candidates(victim: str, pending_dead: set[str]) -> list[str]:
    return [b for b in BRANCH_BREEDERS if b != victim and b not in pending_dead]


async def _breed_fallback_into_branch(
    store: Store,
    cfg: dict[str, Any],
    oc: dict[str, Any],
    *,
    victim: str,
    pending_dead: set[str],
    end_iso: str,
    max_rows: int,
    trades_by_branch: dict[str, list[dict[str, Any]]],
    signals_by_branch: dict[str, list[dict[str, Any]]],
    replay_bundle: ReplayBundleFn,
    open_kw: ReplayOpenKwFn,
    rng: random.Random,
    include_fees: bool,
    log_kind: str,
    record_cooldown: bool = True,
) -> dict[str, Any]:
    lk = _lab_key_for_branch(victim)
    if not lk:
        return {"kind": log_kind, "victim": victim, "via": "breed_skip"}
    include_fees_b = include_fees

    candidates = _breeder_parent_candidates(victim, pending_dead)
    if len(candidates) < 2:
        candidates = [b for b in BRANCH_BREEDERS if b != victim] or list(
            BRANCH_BREEDERS
        )
    settled_by_br: dict[str, list[dict[str, Any]]] = {}
    fitness_by_br: dict[str, float] = {}
    for br in candidates:
        tr = trades_by_branch.get(br) or []
        st = [
            t
            for t in tr
            if str(t.get("status") or "").lower() == "settled"
            and t.get("pnl_cents") is not None
        ]
        settled_by_br[br] = st
        sg = signals_by_branch.get(br) or []
        lab_o = _lab_dict(cfg, br)
        _, rules = _rules_for_lab(cfg, lab_o)
        fitness_by_br[br] = _fitness_for_branch(
            settled=st,
            rules=rules,
            signals=sg,
            include_fees=include_fees_b,
            lab_overlay=lab_o,
            full_cfg=cfg,
            branch=br,
            replay_bundle=replay_bundle,
            open_kw=open_kw,
            at_iso=end_iso,
            trades=tr,
            max_rows=max_rows,
        )

    pa, pa_sel_reason, _ = _tournament_select_parent(
        candidates=candidates,
        fitness_by_br=fitness_by_br,
        settled_by_br=settled_by_br,
        rng=rng,
    )
    pb_candidates = [b for b in candidates if b != pa] or [pa]
    pb, pb_sel_reason, _ = _tournament_select_parent(
        candidates=pb_candidates,
        fitness_by_br=fitness_by_br,
        settled_by_br=settled_by_br,
        rng=rng,
    )
    traits, mutated_traits = _traits_from_two_parents(cfg, pa, pb, rng)
    synergy_score = _trait_complementarity_score(cfg, pa, pb)
    reason_short, reason_full = _breeder_reason_text(
        parent_a=pa,
        parent_b=pb,
        select_reason_a=pa_sel_reason,
        select_reason_b=pb_sel_reason,
        synergy_score=synergy_score,
        repeated_culls=_has_repeated_similar_culls(oc),
        fitness_by_br=fitness_by_br,
    )
    child = _breed_child(
        victim_branch=victim,
        parent_a=pa,
        parent_b=pb,
        cfg=cfg,
        rng=rng,
        competitive_traits=traits,
        mutated_traits=mutated_traits,
        breeder_reason_short=reason_short,
        breeder_reason_full=reason_full,
        synergy_score=synergy_score,
        parent_ids=[pa, pb],
        parent_fitness={pa: fitness_by_br.get(pa, 0.0), pb: fitness_by_br.get(pb, 0.0)},
    )
    cfg[lk] = _expand_parent_lab_after_replacement(lk, dict(child))

    try:
        await store.reset_trading_data(backup=False, branch=victim)
    except Exception as e:
        logger.warning("lab breeding reset failed branch=%s err=%s", victim, e)
    entry = {
        "kind": log_kind,
        "at": end_iso,
        "victim": victim,
        "via": "breed_crossover",
        "parents": [pa, pb],
        "breeder_reason": reason_short,
        "breeder_reason_full": reason_full,
        "synergy_score": synergy_score,
        **_toast_fields(family="sad", victim=victim, reason=log_kind, via="breed"),
    }
    append_breeding_log(oc, entry)
    _append_lineage_history(oc, {**entry, "slot": victim})
    if record_cooldown:
        _record_replacement_cooldown(oc, end_iso)
    return entry


async def replace_branch_from_best_child_or_breed(
    store: Store,
    cfg: dict[str, Any],
    oc: dict[str, Any],
    *,
    victim: str,
    pending_dead: set[str],
    end_iso: str,
    max_rows: int,
    trades_by_branch: dict[str, list[dict[str, Any]]],
    signals_by_branch: dict[str, list[dict[str, Any]]],
    replay_bundle: ReplayBundleFn,
    open_kw: ReplayOpenKwFn,
    rng: random.Random,
    include_fees: bool,
    log_kind: str,
) -> dict[str, Any] | None:
    record_cooldown = log_kind != "hard_death"
    lk = _lab_key_for_branch(victim)
    if not lk:
        return None
    pool = _sorted_child_pool(oc, cfg)
    if pool:
        chosen = pool[0]
        cid = chosen.get("id")
        new_pool = [c for c in pool if c.get("id") != cid]
        _set_child_pool(oc, new_pool)
        slot = str(chosen.get("engine_branch") or "").strip()
        if slot in BRANCH_CHILD_LABS and isinstance(cfg.get(slot), dict):
            cfg[lk] = _expand_parent_lab_after_replacement(lk, copy.deepcopy(cfg[slot]))
            await _clear_child_engine_slot(store, cfg, slot, end_iso)
        else:
            lab_src = _child_row_effective_lab(chosen, cfg) or chosen.get("lab")
            cfg[lk] = _expand_parent_lab_after_replacement(
                lk, dict(lab_src) if isinstance(lab_src, dict) else {}
            )
        try:
            await store.reset_trading_data(backup=False, branch=victim)
        except Exception as e:
            logger.warning("lab breeding reset failed branch=%s err=%s", victim, e)
        entry = {
            "kind": f"{log_kind}_child",
            "at": end_iso,
            "victim": victim,
            "child_id": cid,
            "replay_fitness": chosen.get("replay_fitness"),
            **_toast_fields(family="sad", victim=victim, reason=log_kind, via="child"),
        }
        append_breeding_log(oc, entry)
        _append_lineage_history(oc, {**entry, "slot": victim})
        logger.info(
            "LABS BREEDING: %s replaced %s with child %s", log_kind, victim, cid
        )
        if record_cooldown:
            _record_replacement_cooldown(oc, end_iso)
        return entry
    return await _breed_fallback_into_branch(
        store,
        cfg,
        oc,
        victim=victim,
        pending_dead=pending_dead,
        end_iso=end_iso,
        max_rows=max_rows,
        trades_by_branch=trades_by_branch,
        signals_by_branch=signals_by_branch,
        replay_bundle=replay_bundle,
        open_kw=open_kw,
        rng=rng,
        include_fees=include_fees,
        log_kind=log_kind,
        record_cooldown=record_cooldown,
    )


async def maybe_breed_dead_labs(
    store: Store,
    cfg: dict[str, Any],
    oc: dict[str, Any],
    *,
    start_iso: str,
    end_iso: str,
    max_rows: int,
    trades_by_branch: dict[str, list[dict[str, Any]]],
    signals_by_branch: dict[str, list[dict[str, Any]]],
    replay_bundle: ReplayBundleFn,
    open_kw: ReplayOpenKwFn,
) -> list[dict[str, Any]]:
    """Hard equity ≤ 0: fill slot from best child, else breeder crossover."""
    _ = LAB_BREEDING_INTERNAL_MAX_SLOTS
    out_log: list[dict[str, Any]] = []
    rng = random.Random()
    include_fees = bool(oc.get("include_fees_in_score", True))

    dead_initial: list[str] = []
    for br in BRANCH_LABS:
        eq = await _last_equity_cents(store, br)
        if eq is None:
            continue
        if eq <= 0:
            dead_initial.append(br)

    if not dead_initial:
        return out_log

    pending_dead = set(dead_initial)
    for victim in sorted(pending_dead):
        row = await replace_branch_from_best_child_or_breed(
            store,
            cfg,
            oc,
            victim=victim,
            pending_dead=pending_dead,
            end_iso=end_iso,
            max_rows=max_rows,
            trades_by_branch=trades_by_branch,
            signals_by_branch=signals_by_branch,
            replay_bundle=replay_bundle,
            open_kw=open_kw,
            rng=rng,
            include_fees=include_fees,
            log_kind="hard_death",
        )
        if row:
            out_log.append(row)
        pending_dead.discard(victim)

    return out_log


def _soft_cull_pick(
    rows: list[tuple[str, float, dict[str, Any], int, int]], oc: dict[str, Any]
) -> str | None:
    alive = [r for r in rows if r[4] > 0 and r[3] >= MIN_SETTLED_FOR_SOFT_CULL]
    if len(alive) < 2:
        return None
    alive.sort(key=lambda x: x[1])
    worst_br, worst_f, worst_fb, _, _ = alive[0]
    fits = [x[1] for x in alive]
    med = float(median(fits))
    best_f = max(fits)
    spread = max(1e-9, best_f - min(fits))
    margin = 0.22 * spread
    adv = (
        worst_fb.get("advanced_metrics")
        if isinstance(worst_fb.get("advanced_metrics"), dict)
        else {}
    )
    sharpe = float(adv.get("sharpe") or 0.0)
    exp = float(adv.get("expectancy_dollars") or 0.0)
    floor_global = float(oc.get("paper_winner_fitness_min") or 0.0)
    weak_vs_median = spread > 0.12 and worst_f < med - margin
    weak_expectancy = exp < -0.02 and sharpe < -0.04
    weak_global = worst_f < floor_global and best_f > worst_f + 0.45
    if weak_vs_median or weak_expectancy or weak_global:
        return worst_br
    return None


async def maybe_soft_cull_lab_branches(
    store: Store,
    cfg: dict[str, Any],
    oc: dict[str, Any],
    *,
    end_iso: str,
    max_rows: int,
    trades_by_branch: dict[str, list[dict[str, Any]]],
    signals_by_branch: dict[str, list[dict[str, Any]]],
    replay_bundle: ReplayBundleFn,
    open_kw: ReplayOpenKwFn,
) -> list[dict[str, Any]]:
    """At most one soft-culled slot per optimizer tick (replay underperformance vs peers)."""
    out: list[dict[str, Any]] = []
    if _replacement_cooldown_active(oc, end_iso):
        logger.info(
            "[breeding] soft_cull_skip reason=replacement_cooldown until=%s grep=breeding_soft_cull",
            str(oc.get("labs_breeding_replace_cooldown_until") or "")[:32],
        )
        return out
    rng = random.Random()
    include_fees = bool(oc.get("include_fees_in_score", True))
    per_branch: list[tuple[str, float, dict[str, Any], int, int]] = []
    for br in BRANCH_LABS:
        tr = trades_by_branch.get(br) or []
        st = [
            t
            for t in tr
            if str(t.get("status") or "").lower() == "settled"
            and t.get("pnl_cents") is not None
        ]
        sg = signals_by_branch.get(br) or []
        lab_o = _lab_dict(cfg, br)
        _, rules = _rules_for_lab(cfg, lab_o)
        fb = _replay_metrics_for_branch(
            settled=st,
            rules=rules,
            signals=sg,
            include_fees=include_fees,
            lab_overlay=lab_o,
            full_cfg=cfg,
            branch=br,
            replay_bundle=replay_bundle,
            open_kw=open_kw,
            at_iso=end_iso,
            trades=tr,
            max_rows=max_rows,
        )
        fit = float(fb.get("score_dollars") or 0.0)
        eq = await _last_equity_cents(store, br)
        eq_i = int(eq) if eq is not None else 0
        per_branch.append((br, fit, fb, len(st), eq_i))

    victim = _soft_cull_pick(per_branch, oc)
    if not victim:
        return out

    row = await replace_branch_from_best_child_or_breed(
        store,
        cfg,
        oc,
        victim=victim,
        pending_dead=set(),
        end_iso=end_iso,
        max_rows=max_rows,
        trades_by_branch=trades_by_branch,
        signals_by_branch=signals_by_branch,
        replay_bundle=replay_bundle,
        open_kw=open_kw,
        rng=rng,
        include_fees=include_fees,
        log_kind="soft_cull",
    )
    if row:
        out.append(row)
    return out


async def run_lab_breeding_ga_cycle(
    store: Store,
    cfg: dict[str, Any],
    oc: dict[str, Any],
    *,
    start_iso: str,
    end_iso: str,
    max_rows: int,
    trades_by_branch: dict[str, list[dict[str, Any]]],
    signals_by_branch: dict[str, list[dict[str, Any]]],
    replay_bundle: ReplayBundleFn,
    open_kw: ReplayOpenKwFn,
) -> list[dict[str, Any]]:
    # LABS BREEDING — smarter tournament parenting + explainable lineage metadata.
    """30-minute tick: breeders bind offspring to ``lab_child_*`` engines; pool cap evicts weakest; Lab A may adopt."""
    _ = start_iso
    out_log: list[dict[str, Any]] = []
    now_dt = _parse_iso_utc(end_iso)
    if now_dt is None:
        return out_log

    _migrate_legacy_lineages(oc, end_iso=end_iso)

    last_iso = str(oc.get("labs_breeding_last_generation_iso") or "").strip()
    last_dt = _parse_iso_utc(last_iso)
    if last_dt is not None and (now_dt - last_dt) < LAB_BREEDING_GENERATION_INTERVAL:
        rem = LAB_BREEDING_GENERATION_INTERVAL - (now_dt - last_dt)
        rem_m = max(0, int(rem.total_seconds() // 60))
        logger.info(
            "[breeding] ga_skip reason=ga_generation_cooldown last_gen=%s minutes_until_next~=%d grep=breeding_ga_cooldown",
            last_iso or "(none)",
            rem_m,
        )
        return out_log

    rng = random.Random()
    include_fees = bool(oc.get("include_fees_in_score", True))

    fitness_by_br: dict[str, float] = {}
    settled_by_br: dict[str, list[dict[str, Any]]] = {}
    for br in BRANCH_LABS:
        tr = trades_by_branch.get(br) or []
        st = [
            t
            for t in tr
            if str(t.get("status") or "").lower() == "settled"
            and t.get("pnl_cents") is not None
        ]
        settled_by_br[br] = st
        sg = signals_by_branch.get(br) or []
        lab_o = _lab_dict(cfg, br)
        _, rules = _rules_for_lab(cfg, lab_o)
        fitness_by_br[br] = _fitness_for_branch(
            settled=st,
            rules=rules,
            signals=sg,
            include_fees=include_fees,
            lab_overlay=lab_o,
            full_cfg=cfg,
            branch=br,
            replay_bundle=replay_bundle,
            open_kw=open_kw,
            at_iso=end_iso,
            trades=tr,
            max_rows=max_rows,
        )

    from .persistence import expand_partial_lab_branch

    engine = BreedingEngine(
        cfg=cfg,
        oc=oc,
        rng=rng,
        tournament_select=_tournament_select_parent,
        replay_bundle=replay_bundle,
        open_kw=open_kw,
        lab_dict_fn=_lab_dict,
        rules_for_lab_fn=_rules_for_lab,
        replay_metrics_fn=_replay_metrics_for_branch,
        trait_read_fn=_read_traits,
        trait_complementarity_pair_fn=_trait_complementarity_score,
        competitive_trait_breed_fn=_competitive_trait_breed,
        apply_competitive_traits_fn=_apply_competitive_traits,
        blend_filters_fn=_blend_filters,
    )

    new_babies: list[dict[str, Any]] = []
    for parent in BRANCH_BREEDERS:
        eq = await _last_equity_cents(store, parent)
        if eq is None or eq <= 0:
            logger.info(
                "[breeding] parent_breed_skip reason=no_or_zero_equity parent=%s eq=%s grep=breeding_parent_equity",
                parent,
                "missing" if eq is None else int(eq),
            )
            continue
        while _pick_child_slot(oc) is None and _sorted_child_pool(oc, cfg):
            pool_tmp = _sorted_child_pool(oc, cfg)
            w = pool_tmp[-1]
            _set_child_pool(oc, [x for x in pool_tmp if x.get("id") != w.get("id")])
            eb = str(w.get("engine_branch") or "").strip()
            if eb in BRANCH_CHILD_LABS:
                await _clear_child_engine_slot(store, cfg, eb, end_iso)
            _death_chamber_append(
                oc,
                {
                    "culled_at": end_iso,
                    "reason": "slot_preempt",
                    "parent": w.get("parent"),
                    "replay_fitness": w.get("replay_fitness"),
                    "id": w.get("id"),
                },
            )
            _append_lineage_history(
                oc,
                {
                    "at": end_iso,
                    "kind": "child_death",
                    "id": w.get("id"),
                    "replay_fitness": w.get("replay_fitness"),
                    "reason": "slot_preempt",
                },
            )
            append_breeding_log(
                oc,
                {
                    "kind": "child_slot_preempt",
                    "at": end_iso,
                    "child_id": w.get("id"),
                    "parent": w.get("parent"),
                    "replay_fitness": w.get("replay_fitness"),
                    **_toast_fields(
                        family="sad", reason="child_slot_preempt", via="pool"
                    ),
                },
            )
        slot = _pick_child_slot(oc)
        if not slot:
            logger.warning("LABS BREEDING: no free child slot for parent=%s", parent)
            continue
        sel = engine.select_parents(
            slot_owner=parent,
            fitness_by_br=fitness_by_br,
            settled_by_br=settled_by_br,
        )
        pa, pb = sel.primary, sel.secondary
        pc = sel.tertiary
        pa_sel_reason, pb_sel_reason = sel.reason_primary, sel.reason_secondary
        pc_sel_reason = "tri_parent_exploration" if pc else ""
        parents_list = [pa, pb] + ([pc] if pc else [])
        synergy_score = float(sel.synergy_pair)
        if pc is not None and sel.synergy_triple is not None:
            synergy_score = (
                0.55 * float(sel.synergy_pair)
                + 0.225 * _trait_complementarity_score(cfg, pa, pc)
                + 0.225 * _trait_complementarity_score(cfg, pb, pc)
            )
        mutation_scale = engine.adaptive_mutation_scale(fitness_by_br)
        reason_short, reason_full = _breeder_reason_text(
            parent_a=pa,
            parent_b=pb,
            select_reason_a=pa_sel_reason,
            select_reason_b=pb_sel_reason,
            synergy_score=synergy_score,
            repeated_culls=_has_repeated_similar_culls(oc),
            fitness_by_br=fitness_by_br,
            parent_c=pc,
            select_reason_c=pc_sel_reason,
        )
        baby_lab = engine.crossover(
            victim_branch=parent,
            parents=parents_list,
            mutation_scale=mutation_scale,
            breeder_reason_short=reason_short,
            breeder_reason_full=reason_full,
            synergy_score=synergy_score,
            parent_fitness={p: float(fitness_by_br.get(p, 0.0)) for p in parents_list},
        )
        traits = _read_traits(baby_lab)
        mutated_traits = list(
            (
                baby_lab.get("_labs_breeding_origin") or {}
            ).get("mutated_traits")
            or []
        )
        tr_p = trades_by_branch.get(parent) or []
        sg_p = signals_by_branch.get(parent) or []
        baby_fit = _child_replay_fitness(
            child_lab=baby_lab,
            eval_branch=parent,
            cfg=cfg,
            trades=tr_p,
            signals=sg_p,
            include_fees=include_fees,
            replay_bundle=replay_bundle,
            open_kw=open_kw,
            at_iso=end_iso,
            max_rows=max_rows,
        )
        origin = (
            baby_lab.get("_labs_breeding_origin")
            if isinstance(baby_lab.get("_labs_breeding_origin"), dict)
            else {}
        )
        parent_fits = [float(fitness_by_br.get(p, 0.0)) for p in parents_list]
        avg_parent_fit = float(fmean(parent_fits)) if parent_fits else 0.0
        fit_delta = float(baby_fit) - avg_parent_fit
        origin["fitness_delta_vs_parents"] = round(fit_delta, 4)
        origin["inherited_traits_summary"] = _trait_badges(traits, 3)
        baby_lab["_labs_breeding_origin"] = origin
        merged_lab = {**baby_lab, "engine_running": True}
        cfg[slot] = expand_partial_lab_branch(slot, merged_lab)
        try:
            await store.reset_trading_data(backup=False, branch=slot)
        except Exception as e:
            logger.warning(
                "lab breeding child slot reset failed slot=%s err=%s", slot, e
            )
        cid = str(uuid4())
        baby_traits = _read_traits(baby_lab)
        trait_delta_vs_mid = {
            k: round(float(baby_traits.get(k, 0.5)) - float(_read_traits(_lab_dict(cfg, pa)).get(k, 0.5)), 4)
            for k in TRAIT_KEYS
        }
        new_babies.append(
            {
                "id": cid,
                "parent": parent,
                "parent_ids": parents_list,
                "parent_labels": [
                    p.replace("_", " ").title() for p in parents_list[:3]
                ],
                "born_at": end_iso,
                "traits": baby_traits,
                "replay_fitness": baby_fit,
                "fitness_delta_vs_parents": round(fit_delta, 4),
                "inherited_rules_count": int(
                    (origin.get("inherited_rules_count") or 0)
                ),
                "mutated_traits": list(origin.get("mutated_traits") or []),
                "breeder_reason": reason_full,
                "breeder_reason_short": reason_short,
                "synergy_score": float(synergy_score),
                "engine_branch": slot,
                "origin": copy.deepcopy(origin),
                "lab": copy.deepcopy(baby_lab),
            }
        )
        append_breeding_log(
            oc,
            {
                **_toast_fields(family="birth"),
                "kind": "child_born",
                "at": end_iso,
                "parent": parent,
                "parent_ids": parents_list,
                "parent_count": len(parents_list),
                "mutation_scale": round(mutation_scale, 4),
                "stagnation_boost": bool(sel.stagnation_boost),
                "trait_delta_vs_primary_parent": trait_delta_vs_mid,
                "confidence_pct": round(
                    min(
                        99.9,
                        max(
                            0.0,
                            52.0
                            + 120.0 * float(fit_delta)
                            + 8.0 * float(sel.synergy_pair or 0.0),
                        ),
                    ),
                    2,
                ),
                "child_id": cid,
                "replay_fitness": baby_fit,
                "fitness_delta_vs_parents": round(fit_delta, 4),
                "inherited_rules_count": int(
                    (origin.get("inherited_rules_count") or 0)
                ),
                "mutated_traits": list(origin.get("mutated_traits") or []),
                "breeder_reason": reason_short,
                "breeder_reason_full": reason_full,
                "synergy_score": float(synergy_score),
                "engine_branch": slot,
                "breeding_traits_phrase": _traits_birth_summary(baby_traits),
            },
        )
        _append_lineage_history(
            oc,
            {
                "at": end_iso,
                "kind": "birth",
                "parent": parent,
                "parent_ids": parents_list,
                "child_id": cid,
                "replay_fitness": baby_fit,
                "fitness_delta_vs_parents": round(fit_delta, 4),
                "breeder_reason": reason_short,
                "breeder_reason_full": reason_full,
                "synergy_score": float(synergy_score),
                "engine_branch": slot,
            },
        )
        nb_row = new_babies[-1]
        engine.update_elite_archive(nb_row, baby_lab)

    prev = _sorted_child_pool(oc, cfg)
    merged = new_babies + prev
    cap = max(1, int(LAB_BREEDING_MAX_CHILD_SLOTS))
    while len(merged) > cap:
        ev_i = engine.manage_diversity_eviction_index(merged)
        evicted = merged.pop(ev_i)
        eb = str(evicted.get("engine_branch") or "").strip()
        if eb in BRANCH_CHILD_LABS:
            await _clear_child_engine_slot(store, cfg, eb, end_iso)
        _death_chamber_append(
            oc,
            {
                "culled_at": end_iso,
                "reason": "child_pool_cap",
                "parent": evicted.get("parent"),
                "replay_fitness": evicted.get("replay_fitness"),
                "id": evicted.get("id"),
            },
        )
        _append_lineage_history(
            oc,
            {
                "at": end_iso,
                "kind": "child_death",
                "id": evicted.get("id"),
                "replay_fitness": evicted.get("replay_fitness"),
                "reason": "pool_cap",
            },
        )
        append_breeding_log(
            oc,
            {
                "kind": "child_pool_cull",
                "at": end_iso,
                "child_id": evicted.get("id"),
                "parent": evicted.get("parent"),
                "replay_fitness": evicted.get("replay_fitness"),
                **_toast_fields(family="sad", reason="child_pool_cull", via="pool"),
            },
        )
    _set_child_pool(oc, merged)

    fit_a = float(fitness_by_br.get(BRANCH_LAB_A, 0.0))
    st_a = settled_by_br.get(BRANCH_LAB_A) or []
    pool_after = _sorted_child_pool(oc, cfg)
    cool = _replacement_cooldown_active(oc, end_iso)
    pending_exists = isinstance(oc.get("labs_breeding_pending_adoption"), dict)
    if (
        len(st_a) >= MIN_SETTLED_FOR_ADOPTION_COMPARE
        and pool_after
        and not pending_exists
    ):
        best_child = max(pool_after, key=lambda x: float(x.get("replay_fitness", 0.0)))
        adoption = engine.adopt_to_lab_a(
            end_iso=end_iso,
            max_rows=max_rows,
            include_fees=include_fees,
            fitness_by_br=fitness_by_br,
            settled_by_br=settled_by_br,
            signals_by_branch=signals_by_branch,
            trades_by_branch=trades_by_branch,
            best_child=best_child,
            replacement_cooldown_active=cool,
        )
        if adoption.rejected_reason and adoption.rejected_reason not in (
            "replacement_cooldown",
            "lab_a_settled_lt_min",
        ):
            append_breeding_log(
                oc,
                {
                    "kind": "adoption_rejected",
                    "at": end_iso,
                    "reason": adoption.rejected_reason,
                    "report": adoption.report,
                    "child_id": best_child.get("id"),
                },
            )
        elif adoption.pending:
            append_breeding_log(
                oc,
                {
                    "kind": "adoption_pending_confirmation",
                    **_toast_fields(family="birth"),
                    "at": end_iso,
                    "child_id": best_child.get("id"),
                    "lab_a_fitness_before": fit_a,
                    "gate_report": adoption.report,
                    "dynamic_margin": adoption.dynamic_margin,
                    "z_score": adoption.z_score,
                },
            )
            out_log.append({"kind": "adoption_pending_confirmation", "at": end_iso})
        elif adoption.adopted:
            cid = best_child.get("id")
            slot_ad = str(best_child.get("engine_branch") or "").strip()
            if slot_ad in BRANCH_CHILD_LABS and isinstance(cfg.get(slot_ad), dict):
                cfg["lab_a"] = _expand_parent_lab_after_replacement(
                    "lab_a", copy.deepcopy(cfg[slot_ad])
                )
                await _clear_child_engine_slot(store, cfg, slot_ad, end_iso)
            else:
                lab_src = _child_row_effective_lab(best_child, cfg) or best_child.get(
                    "lab"
                )
                cfg["lab_a"] = _expand_parent_lab_after_replacement(
                    "lab_a", dict(lab_src) if isinstance(lab_src, dict) else {}
                )
            _set_child_pool(oc, [c for c in pool_after if c.get("id") != cid])
            try:
                await store.reset_trading_data(backup=False, branch=BRANCH_LAB_A)
            except Exception as e:
                logger.warning("lab adoption reset failed err=%s", e)
            append_breeding_log(
                oc,
                {
                    "kind": "adoption",
                    **_toast_fields(family="birth"),
                    "at": end_iso,
                    "child_id": cid,
                    "replay_fitness": best_child.get("replay_fitness"),
                    "lab_a_fitness_before": fit_a,
                    "gate_report": adoption.report,
                    "dynamic_margin": adoption.dynamic_margin,
                    "z_score": adoption.z_score,
                    "confidence_pct": adoption.report.get("confidence_pct"),
                },
            )
            _append_lineage_history(
                oc,
                {
                    "at": end_iso,
                    "kind": "adoption",
                    "child_id": cid,
                    "replay_fitness": best_child.get("replay_fitness"),
                    "gate_report": adoption.report,
                },
            )
            out_log.append({"kind": "adoption", "at": end_iso})
            _record_replacement_cooldown(oc, end_iso)

    oc["labs_breeding_last_generation_iso"] = end_iso
    oc["labs_breeding_generation_index"] = (
        int(oc.get("labs_breeding_generation_index") or 0) + 1
    )
    append_breeding_log(
        oc,
        {
            "kind": "generation",
            "at": end_iso,
            "new_children": len(new_babies),
            "children_total": len(_sorted_child_pool(oc, cfg)),
            "max_pool": cap,
        },
    )
    out_log.append({"kind": "generation", "at": end_iso})
    return out_log


async def resolve_lab_a_pending_adoption(
    store: Store,
    *,
    accept: bool,
) -> dict[str, Any]:
    """
    Operator confirmation path when ``optimizer.lab_a_adoption_requires_confirmation`` deferred adoption.

    **accept=False** clears pending without touching Lab A. **accept=True** promotes the pending child's genome
    into Lab A (same mechanics as automatic adoption) and clears pending.
    """
    cfg = await store.load_config()
    oc = cfg.setdefault("optimizer", {})
    if not isinstance(oc, dict):
        oc = {}
        cfg["optimizer"] = oc
    pend = oc.get("labs_breeding_pending_adoption")
    if not isinstance(pend, dict):
        return {"ok": False, "reason": "no_pending"}
    cid = pend.get("child_id")
    pool = [x for x in (oc.get("labs_breeding_children") or []) if isinstance(x, dict)]

    if not accept:
        report = copy.deepcopy(pend.get("report") or {})
        decline_pending_lab_a_adoption(oc)
        append_breeding_log(
            oc,
            {
                "kind": "adoption_pending_declined",
                "at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "child_id": cid,
                "gate_report": report,
            },
        )
        cfg["optimizer"] = oc
        await store.save_config(
            cfg,
            history_branch="global",
            history_changed_by="lab_a_adoption_pending",
            history_reason="pending_lab_a_declined",
        )
        return {"ok": True, "declined": True}

    chosen = next((x for x in pool if x.get("id") == cid), None)
    if not chosen:
        clear_pending_lab_a_adoption(oc)
        cfg["optimizer"] = oc
        await store.save_config(
            cfg,
            history_branch="global",
            history_changed_by="lab_a_adoption_pending",
            history_reason="pending_cleared_missing_child",
        )
        return {"ok": False, "reason": "child_missing"}

    pool_after = pool
    slot_ad = str(chosen.get("engine_branch") or "").strip()
    if slot_ad in BRANCH_CHILD_LABS and isinstance(cfg.get(slot_ad), dict):
        cfg["lab_a"] = _expand_parent_lab_after_replacement(
            "lab_a", copy.deepcopy(cfg[slot_ad])
        )
        await _clear_child_engine_slot(store, cfg, slot_ad, pend.get("proposed_at") or "")
    else:
        lab_src = _child_row_effective_lab(chosen, cfg) or chosen.get("lab")
        cfg["lab_a"] = _expand_parent_lab_after_replacement(
            "lab_a", dict(lab_src) if isinstance(lab_src, dict) else {}
        )
    _set_child_pool(oc, [c for c in pool_after if c.get("id") != cid])
    clear_pending_lab_a_adoption(oc)
    cfg["optimizer"] = oc
    try:
        await store.reset_trading_data(backup=False, branch=BRANCH_LAB_A)
    except Exception as e:
        logger.warning("manual pending lab_a adoption reset failed err=%s", e)
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    append_breeding_log(
        oc,
        {
            "kind": "adoption_manual_confirm",
            **_toast_fields(family="birth"),
            "at": now_iso,
            "child_id": cid,
            "replay_fitness": chosen.get("replay_fitness"),
            "pending_report": pend.get("report"),
        },
    )
    _append_lineage_history(
        oc,
        {
            "at": now_iso,
            "kind": "adoption_manual_confirm",
            "child_id": cid,
            "replay_fitness": chosen.get("replay_fitness"),
        },
    )
    cfg["optimizer"] = oc
    await store.save_config(
        cfg,
        history_branch="global",
        history_changed_by="lab_a_adoption_pending",
        history_reason="pending_lab_a_confirmed",
    )
    return {"ok": True, "confirmed": True}
