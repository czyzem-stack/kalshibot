# LABS BREEDING v0.1 REVAMP — fully automatic, invisible, continuous replacement (4 active slots only)
"""
Invisible internal GA for paper labs (no Claude, no UI, no extra SQLite branches).

Only **lab_a–lab_d** trade. A virtual **child pool** (cap ``LAB_BREEDING_MAX_VIRTUAL_POOL``) holds genomes
spawned by breeders **B/C/D** every 30 minutes. **Lab A** never breeds; it may adopt the strongest child on
schedule. Whenever any lab slot is **hard-dead** (equity ≤ 0) or **soft-culled** (weak replay vs peers), it is
**immediately** filled from the best available child if any, otherwise from breeder crossover.

**Lineage / death** caps (10) and ``labs_breeding_log`` are exposed via full config (dashboard) and ``GET /api/optimizer/status``.
Some log rows include ``toast_id`` / ``toast_family`` for ephemeral client toasts (birth vs death/cull).
"""
from __future__ import annotations

import copy
import datetime as dt
import logging
import random
from statistics import median
from typing import TYPE_CHECKING, Any, Callable
from uuid import uuid4

from .api_models import normalize_rules_list
from .branch_config import (
    BRANCH_BREEDERS,
    BRANCH_LAB_A,
    BRANCH_LAB_B,
    BRANCH_LAB_C,
    BRANCH_LAB_D,
    BRANCH_LABS,
    LAB_BREEDING_INTERNAL_MAX_SLOTS,
    LAB_BREEDING_MAX_VIRTUAL_POOL,
    _lab_key_for_branch,
    clamp_balance_fraction_per_window,
)

if TYPE_CHECKING:
    from .persistence import Store

logger = logging.getLogger("kalshibot.lab_breeding")


def _toast_fields(*, family: str, **kwargs: Any) -> dict[str, Any]:
    # LABS BREEDING v0.1 — special toasts for birth and death/cull
    out: dict[str, Any] = {"toast_id": str(uuid4()), "toast_family": family}
    for k, v in kwargs.items():
        if v is not None and v != "":
            out[k] = v
    return out


def _signals_sorted_desc(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(signals, key=lambda s: int(s.get("id") or 0), reverse=True)


ReplayBundleFn = Callable[..., dict[str, Any]]
ReplayOpenKwFn = Callable[..., dict[str, Any]]

LAB_BREEDING_GENERATION_INTERVAL = dt.timedelta(minutes=30)
MIN_SETTLED_FOR_ADOPTION_COMPARE = 4
MIN_SETTLED_FOR_SOFT_CULL = 5
TRAIT_KEYS = ("aggressiveness", "risk_tolerance", "adaptivity", "exploration", "resilience")
DEATH_CHAMBER_CAP = 10
LINEAGE_HISTORY_CAP = 10


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


def _rules_for_lab(cfg: dict[str, Any], lab_o: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base = cfg.get("rules") if isinstance(cfg.get("rules"), list) else []
    lr = lab_o.get("rules") if isinstance(lab_o.get("rules"), list) and len(lab_o["rules"]) > 0 else base
    try:
        rules = normalize_rules_list(lr)
    except Exception:
        rules = normalize_rules_list(base or [])
    return lab_o, rules


def _default_traits() -> dict[str, float]:
    return {k: 0.55 for k in TRAIT_KEYS}


def _read_traits(lab_o: dict[str, Any]) -> dict[str, float]:
    raw = lab_o.get("_labs_breeding_traits")
    if not isinstance(raw, dict):
        return _default_traits()
    out: dict[str, float] = {}
    for k in TRAIT_KEYS:
        try:
            out[k] = max(0.05, min(0.98, float(raw.get(k, 0.55))))
        except (TypeError, ValueError):
            out[k] = 0.55
    return out


def _competitive_trait_breed(rng: random.Random, parent: dict[str, float], elite: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for k in TRAIT_KEYS:
        base = 0.5 * float(parent.get(k, 0.55)) + 0.5 * float(elite.get(k, 0.55))
        skew = rng.uniform(0.05, 0.16)
        noise = rng.uniform(-0.05, 0.11)
        out[k] = max(0.05, min(0.98, base + skew + noise))
    return out


def _apply_competitive_traits(child: dict[str, Any], traits: dict[str, float]) -> None:
    child["_labs_breeding_traits"] = {k: float(traits.get(k, 0.55)) for k in TRAIT_KEYS}
    ag = float(traits.get("aggressiveness", 0.55))
    rt = float(traits.get("risk_tolerance", 0.55))
    res = float(traits.get("resilience", 0.55))
    try:
        bf = float(child.get("balance_fraction_per_window") or 0.03)
        child["balance_fraction_per_window"] = clamp_balance_fraction_per_window(bf * (0.86 + 0.28 * ag))
    except (TypeError, ValueError):
        child["balance_fraction_per_window"] = clamp_balance_fraction_per_window(0.03 * (0.86 + 0.28 * ag))
    try:
        wm = int(child.get("window_minutes") or 15)
        child["window_minutes"] = max(1, min(1440, wm - int((1.0 - rt) * 6)))
    except (TypeError, ValueError):
        pass
    try:
        st = float(child.get("stop_loss_trigger_pct") or -8.0)
        adj = -1.2 * (1.0 - res) + 0.8 * (ag - 0.5)
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
                    c[key] = round(max(0.0, min(1.0, 0.5 * (va + vb) + rng.uniform(-0.02, 0.02))), 4)
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


def _blend_filters(p1: dict[str, Any], p2: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    o = copy.deepcopy(p1)
    if rng.random() < 0.35:
        o["only_yes_subtitle_contains"] = p2.get("only_yes_subtitle_contains") or p1.get("only_yes_subtitle_contains") or ""
    elif rng.random() < 0.2:
        s1 = str(p1.get("exclude_yes_subtitle_contains") or "").strip()
        s2 = str(p2.get("exclude_yes_subtitle_contains") or "").strip()
        o["exclude_yes_subtitle_contains"] = ",".join({x.strip() for x in (s1 + "," + s2).split(",") if x.strip()})[:400]
    return o


def _traits_from_two_parents(cfg: dict[str, Any], pa: str, pb: str, rng: random.Random) -> dict[str, float]:
    t1 = _read_traits(_lab_dict(cfg, pa))
    t2 = _read_traits(_lab_dict(cfg, pb))
    elite = {k: 0.5 * (t1[k] + t2[k]) for k in TRAIT_KEYS}
    return _competitive_trait_breed(rng, t1, elite)


def _breed_child(
    *,
    victim_branch: str,
    parent_a: str,
    parent_b: str,
    cfg: dict[str, Any],
    rng: random.Random,
    competitive_traits: dict[str, float] | None = None,
) -> dict[str, Any]:
    p1 = _lab_dict(cfg, parent_a)
    p2 = _lab_dict(cfg, parent_b)
    base_rules = cfg.get("rules") if isinstance(cfg.get("rules"), list) else []
    r1 = list(p1.get("rules") or base_rules or [])
    r2 = list(p2.get("rules") or base_rules or [])
    child = copy.deepcopy(p1)
    child["balance_fraction_per_window"] = _mutate_frac(
        rng,
        float(p1.get("balance_fraction_per_window") or cfg.get("balance_fraction_per_window") or 0.03),
        float(p2.get("balance_fraction_per_window") or cfg.get("balance_fraction_per_window") or 0.03),
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
        if p1.get("auto_reset_paper_on_tick_failure") != p2.get("auto_reset_paper_on_tick_failure")
        else p1.get("auto_reset_paper_on_tick_failure", False)
    )
    traits = competitive_traits if competitive_traits is not None else _traits_from_two_parents(cfg, parent_a, parent_b, rng)
    _apply_competitive_traits(child, traits)
    child["_labs_breeding_origin"] = {
        "victim": victim_branch,
        "parents": [parent_a, parent_b],
        "gen": rng.randint(1, 999_999),
    }
    return child


def append_breeding_log(oc: dict[str, Any], entry: dict[str, Any], cap: int = 64) -> None:
    log = oc.get("labs_breeding_log")
    hist = list(log) if isinstance(log, list) else []
    hist.insert(0, entry)
    oc["labs_breeding_log"] = hist[:cap]


def _append_lineage_history(oc: dict[str, Any], row: dict[str, Any]) -> None:
    h = [x for x in (oc.get("labs_breeding_lineage_history") or []) if isinstance(x, dict)]
    h.insert(0, row)
    oc["labs_breeding_lineage_history"] = h[:LINEAGE_HISTORY_CAP]


def _death_chamber_append(oc: dict[str, Any], row: dict[str, Any]) -> None:
    dc = [x for x in (oc.get("labs_breeding_death_chamber") or []) if isinstance(x, dict)]
    dc.insert(0, row)
    oc["labs_breeding_death_chamber"] = dc[:DEATH_CHAMBER_CAP]


def _migrate_legacy_lineages(oc: dict[str, Any], *, end_iso: str) -> None:
    leg = oc.pop("labs_breeding_lineages", None)
    if not isinstance(leg, list) or not leg:
        return
    for row in leg[:24]:
        if not isinstance(row, dict):
            continue
        _death_chamber_append(
            oc,
            {"culled_at": end_iso, "reason": "legacy_lineage", "snapshot": {k: row.get(k) for k in ("from_parent", "birth_fitness", "id", "born_at") if k in row}},
        )


def _sorted_child_pool(oc: dict[str, Any]) -> list[dict[str, Any]]:
    pool = [c for c in (oc.get("labs_breeding_children") or []) if isinstance(c, dict) and isinstance(c.get("lab"), dict)]
    pool.sort(key=lambda x: -float(x.get("replay_fitness", 0.0)))
    return pool


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
    st = [t for t in trades if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
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
) -> dict[str, Any]:
    lk = _lab_key_for_branch(victim)
    if not lk:
        return {"kind": log_kind, "victim": victim, "via": "breed_skip"}
    include_fees_b = include_fees

    if victim == BRANCH_LAB_A:
        breeders = _breeder_parent_candidates(victim, pending_dead) or list(BRANCH_BREEDERS)
        scores: list[tuple[float, str]] = []
        for br in breeders:
            tr = trades_by_branch.get(br) or []
            st = [t for t in tr if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
            sg = signals_by_branch.get(br) or []
            lab_o = _lab_dict(cfg, br)
            _, rules = _rules_for_lab(cfg, lab_o)
            sc = _fitness_for_branch(
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
            scores.append((sc, br))
        scores.sort(key=lambda x: -x[0])
        if len(scores) >= 2:
            pa, pb = scores[0][1], scores[1][1]
        elif len(scores) == 1:
            pa = pb = scores[0][1]
        else:
            pa, pb = BRANCH_LAB_B, BRANCH_LAB_C
        traits = _traits_from_two_parents(cfg, pa, pb, rng)
        child = _breed_child(victim_branch=victim, parent_a=pa, parent_b=pb, cfg=cfg, rng=rng, competitive_traits=traits)
        cfg["lab_a"] = child
    else:
        candidates = _breeder_parent_candidates(victim, pending_dead)
        if len(candidates) < 2:
            candidates = [b for b in BRANCH_BREEDERS if b != victim]
        scores = []
        for br in candidates:
            tr = trades_by_branch.get(br) or []
            st = [t for t in tr if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
            sg = signals_by_branch.get(br) or []
            lab_o = _lab_dict(cfg, br)
            _, rules = _rules_for_lab(cfg, lab_o)
            sc = _fitness_for_branch(
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
            scores.append((sc, br))
        scores.sort(key=lambda x: -x[0])
        if len(scores) >= 2:
            pa, pb = scores[0][1], scores[1][1]
        elif len(scores) == 1:
            pa = pb = scores[0][1]
        else:
            others = [b for b in BRANCH_BREEDERS if b != victim]
            pa, pb = others[0], others[-1]
        traits = _traits_from_two_parents(cfg, pa, pb, rng)
        child = _breed_child(victim_branch=victim, parent_a=pa, parent_b=pb, cfg=cfg, rng=rng, competitive_traits=traits)
        cfg[lk] = child

    try:
        await store.reset_trading_data(backup=False, branch=victim)
    except Exception as e:
        logger.warning("lab breeding reset failed branch=%s err=%s", victim, e)
    entry = {
        "kind": log_kind,
        "at": end_iso,
        "victim": victim,
        "via": "breed_crossover",
        **_toast_fields(family="sad", victim=victim, reason=log_kind, via="breed"),
    }
    append_breeding_log(oc, entry)
    _append_lineage_history(oc, {**entry, "slot": victim})
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
    lk = _lab_key_for_branch(victim)
    if not lk:
        return None
    pool = _sorted_child_pool(oc)
    if pool:
        chosen = pool[0]
        cid = chosen.get("id")
        new_pool = [c for c in pool if c.get("id") != cid]
        _set_child_pool(oc, new_pool)
        cfg[lk] = copy.deepcopy(chosen["lab"])
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
        logger.info("LABS BREEDING: %s replaced %s with child %s", log_kind, victim, cid)
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


def _soft_cull_pick(rows: list[tuple[str, float, dict[str, Any], int, int]], oc: dict[str, Any]) -> str | None:
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
    adv = worst_fb.get("advanced_metrics") if isinstance(worst_fb.get("advanced_metrics"), dict) else {}
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
    rng = random.Random()
    include_fees = bool(oc.get("include_fees_in_score", True))
    per_branch: list[tuple[str, float, dict[str, Any], int, int]] = []
    for br in BRANCH_LABS:
        tr = trades_by_branch.get(br) or []
        st = [t for t in tr if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
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
    # LABS BREEDING v0.1 REVAMP — fully automatic, invisible, continuous replacement (4 active slots only)
    """30-minute tick: breeders spawn children; pool cap evicts weak virtuals; Lab A may adopt strongest child."""
    _ = start_iso
    out_log: list[dict[str, Any]] = []
    now_dt = _parse_iso_utc(end_iso)
    if now_dt is None:
        return out_log

    _migrate_legacy_lineages(oc, end_iso=end_iso)

    last_iso = str(oc.get("labs_breeding_last_generation_iso") or "").strip()
    last_dt = _parse_iso_utc(last_iso)
    if last_dt is not None and (now_dt - last_dt) < LAB_BREEDING_GENERATION_INTERVAL:
        return out_log

    rng = random.Random()
    include_fees = bool(oc.get("include_fees_in_score", True))

    fitness_by_br: dict[str, float] = {}
    settled_by_br: dict[str, list[dict[str, Any]]] = {}
    for br in BRANCH_LABS:
        tr = trades_by_branch.get(br) or []
        st = [t for t in tr if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
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

    new_babies: list[dict[str, Any]] = []
    for parent in BRANCH_BREEDERS:
        eq = await _last_equity_cents(store, parent)
        if eq is None or eq <= 0:
            continue
        mate = _pick_mate(parent, fitness_by_br)
        traits = _traits_from_two_parents(cfg, parent, mate, rng)
        baby_lab = _breed_child(
            victim_branch=parent,
            parent_a=parent,
            parent_b=mate,
            cfg=cfg,
            rng=rng,
            competitive_traits=traits,
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
        cid = str(uuid4())
        new_babies.append(
            {
                "id": cid,
                "parent": parent,
                "born_at": end_iso,
                "traits": _read_traits(baby_lab),
                "replay_fitness": baby_fit,
                "lab": baby_lab,
            }
        )
        append_breeding_log(
            oc,
            {
                **_toast_fields(family="birth"),
                "kind": "child_born",
                "at": end_iso,
                "parent": parent,
                "child_id": cid,
                "replay_fitness": baby_fit,
            },
        )
        _append_lineage_history(
            oc,
            {"at": end_iso, "kind": "birth", "parent": parent, "child_id": cid, "replay_fitness": baby_fit},
        )

    prev = _sorted_child_pool(oc)
    merged = new_babies + prev
    cap = max(1, int(LAB_BREEDING_MAX_VIRTUAL_POOL))
    while len(merged) > cap:
        merged.sort(key=lambda x: float(x.get("replay_fitness", 0.0)))
        evicted = merged.pop(0)
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
    adopt_margin = 0.04
    pool_after = _sorted_child_pool(oc)
    if len(st_a) >= MIN_SETTLED_FOR_ADOPTION_COMPARE and pool_after:
        best_child = max(pool_after, key=lambda x: float(x.get("replay_fitness", 0.0)))
        if float(best_child.get("replay_fitness", 0.0)) > fit_a + adopt_margin:
            cid = best_child.get("id")
            cfg["lab_a"] = copy.deepcopy(best_child["lab"])
            _set_child_pool(oc, [c for c in pool_after if c.get("id") != cid])
            try:
                await store.reset_trading_data(backup=False, branch=BRANCH_LAB_A)
            except Exception as e:
                logger.warning("lab adoption reset failed err=%s", e)
            append_breeding_log(
                oc,
                {
                    "kind": "adoption",
                    "at": end_iso,
                    "child_id": cid,
                    "replay_fitness": best_child.get("replay_fitness"),
                    "lab_a_fitness_before": fit_a,
                },
            )
            _append_lineage_history(oc, {"at": end_iso, "kind": "adoption", "child_id": cid, "replay_fitness": best_child.get("replay_fitness")})
            out_log.append({"kind": "adoption", "at": end_iso})

    oc["labs_breeding_last_generation_iso"] = end_iso
    append_breeding_log(
        oc,
        {
            "kind": "generation",
            "at": end_iso,
            "new_children": len(new_babies),
            "children_total": len(_sorted_child_pool(oc)),
            "max_pool": cap,
        },
    )
    out_log.append({"kind": "generation", "at": end_iso})
    return out_log
