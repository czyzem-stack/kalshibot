"""
BreedingEngine — evolutionary operators + safer Lab A adoption.

Orchestrates multi-parent selection, adaptive mutation, diversity-aware eviction,
elite archive, and gated adoption. ``lab_breeding`` keeps thin wrappers and SQLite I/O.
"""

from __future__ import annotations

import copy
import datetime as dt
import logging
import math
import random
from dataclasses import dataclass, field
from statistics import fmean, pstdev
from typing import Any, Callable

from .api_models import normalize_rules_list
from .branch_config import (
    BRANCH_BREEDERS,
    BRANCH_LAB_A,
    BRANCH_LABS,
    BREEDING_ADOPTION_MARGIN_BASE_DEFAULT,
    BREEDING_AGGRESSIVENESS_DEFAULT,
    BREEDING_ELITE_ARCHIVE_CAP,
    BREEDING_STAGNATION_VARIANCE_THRESHOLD,
    BREEDING_VOLATILITY_MARGIN_SCALE_DEFAULT,
    LAB_A_ADOPTION_MULTIMETRIC_MIN_WINS,
    LAB_A_ADOPTION_NO_REGRESS_DD_TOL_PCT,
    LAB_A_ADOPTION_NO_REGRESS_SHARPE_TOL,
    LAB_BREEDING_TRAIT_KEYS,
    MIN_ADOPTION_CONFIDENCE_Z_DEFAULT,
    MIN_SETTLED_FOR_ADOPTION_COMPARE,
    clamp_balance_fraction_per_window,
)

logger = logging.getLogger("kalshibot.breeding_engine")

ReplayBundleFn = Callable[..., dict[str, Any]]
ReplayOpenKwFn = Callable[..., dict[str, Any]]
TournamentSelectFn = Callable[..., tuple[str, str, list[dict[str, Any]]]]


def _signals_sorted_desc(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(signals, key=lambda s: int(s.get("id") or 0), reverse=True)


@dataclass
class ParentSelection:
    """Up to three breeder parents for crossover."""

    primary: str
    secondary: str
    tertiary: str | None
    reason_primary: str
    reason_secondary: str
    synergy_pair: float
    synergy_triple: float | None = None
    stagnation_boost: bool = False


@dataclass
class AdoptionEvaluation:
    """Outcome of Lab A adoption gate + optional pending payload."""

    adopted: bool = False
    pending: bool = False
    rejected_reason: str = ""
    report: dict[str, Any] = field(default_factory=dict)
    dynamic_margin: float = 0.0
    z_score: float = 0.0


class BreedingEngine:
    """
    Evolutionary operators for Kalshibot labs breeding.

    Methods are intentionally explicit so ``run_lab_breeding_ga_cycle`` can delegate
    without restructuring the dual-loop / SQLite boundaries.
    """

    def __init__(
        self,
        *,
        cfg: dict[str, Any],
        oc: dict[str, Any],
        rng: random.Random,
        tournament_select: TournamentSelectFn,
        replay_bundle: ReplayBundleFn,
        open_kw: ReplayOpenKwFn,
        lab_dict_fn: Callable[[dict[str, Any], str], dict[str, Any]],
        rules_for_lab_fn: Callable[
            [dict[str, Any], dict[str, Any]],
            tuple[dict[str, Any], list[dict[str, Any]]],
        ],
        replay_metrics_fn: Callable[..., dict[str, Any]],
        trait_read_fn: Callable[[dict[str, Any]], dict[str, float]],
        trait_complementarity_pair_fn: Callable[[dict[str, Any], str, str], float],
        competitive_trait_breed_fn: Callable[
            [random.Random, dict[str, float], dict[str, float]], dict[str, float]
        ],
        apply_competitive_traits_fn: Callable[[dict[str, Any], dict[str, float]], None],
        blend_filters_fn: Callable[
            [dict[str, Any], dict[str, Any], random.Random], dict[str, Any]
        ],
    ) -> None:
        self.cfg = cfg
        self.oc = oc
        self.rng = rng
        self._tournament_select = tournament_select
        self._replay_bundle = replay_bundle
        self._open_kw = open_kw
        self._lab_dict = lab_dict_fn
        self._rules_for_lab = rules_for_lab_fn
        self._replay_metrics = replay_metrics_fn
        self._read_traits = trait_read_fn
        self._trait_complementarity_pair = trait_complementarity_pair_fn
        self._competitive_trait_breed = competitive_trait_breed_fn
        self._apply_competitive_traits = apply_competitive_traits_fn
        self._blend_filters = blend_filters_fn

    # --- configuration helpers (optimizer JSON override branch_config defaults) ---

    def aggressiveness(self) -> float:
        try:
            v = float(self.oc.get("breeding_aggressiveness"))
        except (TypeError, ValueError):
            v = BREEDING_AGGRESSIVENESS_DEFAULT
        return max(0.0, min(1.0, v))

    def min_adoption_z(self) -> float:
        try:
            z = float(self.oc.get("min_adoption_confidence_z"))
        except (TypeError, ValueError):
            z = MIN_ADOPTION_CONFIDENCE_Z_DEFAULT
        return max(0.5, min(4.0, z))

    def adoption_requires_confirmation(self) -> bool:
        return bool(self.oc.get("lab_a_adoption_requires_confirmation"))

    # --- population dynamics ---

    def fitness_variance_breeders(self, fitness_by_br: dict[str, float]) -> float:
        vals = [float(fitness_by_br.get(b, 0.0)) for b in BRANCH_BREEDERS]
        if len(vals) < 2:
            return 1.0
        m = fmean(vals)
        var = sum((x - m) ** 2 for x in vals) / len(vals)
        return float(var)

    def stagnation(self, fitness_by_br: dict[str, float]) -> bool:
        return self.fitness_variance_breeders(fitness_by_br) < BREEDING_STAGNATION_VARIANCE_THRESHOLD

    def adaptive_mutation_scale(self, fitness_by_br: dict[str, float]) -> float:
        """>1.0 widens trait / numeric jitter when the population looks flat."""
        base = 1.0
        if self.stagnation(fitness_by_br):
            base += 0.35 + 0.5 * self.aggressiveness()
        return base

    def select_parents(
        self,
        *,
        slot_owner: str,
        fitness_by_br: dict[str, Any],
        settled_by_br: dict[str, list[dict[str, Any]]],
    ) -> ParentSelection:
        """
        Tournament picks primary + secondary (existing behavior), optionally a third parent
        when variance is low or RNG favors exploration.
        """
        candidates = [b for b in BRANCH_BREEDERS if b != slot_owner]
        pool = [slot_owner, *candidates]
        pa, ra, _ = self._tournament_select(
            candidates=pool,
            fitness_by_br=fitness_by_br,
            settled_by_br=settled_by_br,
            rng=self.rng,
        )
        others = [b for b in BRANCH_BREEDERS if b != pa] or [pa]
        pb, rb, _ = self._tournament_select(
            candidates=others,
            fitness_by_br=fitness_by_br,
            settled_by_br=settled_by_br,
            rng=self.rng,
        )
        syn2 = self._trait_complementarity_pair(self.cfg, pa, pb)
        stag = self.stagnation(fitness_by_br)
        third_prob = 0.12 + self.aggressiveness() * 0.28 + (0.18 if stag else 0.0)
        pc: str | None = None
        syn3: float | None = None
        if len(BRANCH_BREEDERS) >= 3 and self.rng.random() < third_prob:
            rest = [b for b in BRANCH_BREEDERS if b not in (pa, pb)]
            if rest:
                pc = self.rng.choice(rest)
                syn3 = (
                    self._trait_complementarity_pair(self.cfg, pa, pc)
                    + self._trait_complementarity_pair(self.cfg, pb, pc)
                ) / 2.0
        return ParentSelection(
            primary=pa,
            secondary=pb,
            tertiary=pc,
            reason_primary=ra,
            reason_secondary=rb,
            synergy_pair=syn2,
            synergy_triple=syn3,
            stagnation_boost=stag,
        )

    def trait_vector(self, lab_o: dict[str, Any]) -> list[float]:
        t = self._read_traits(lab_o)
        return [float(t.get(k, 0.5)) for k in LAB_BREEDING_TRAIT_KEYS]

    def trait_distance(self, a: dict[str, Any], b: dict[str, Any]) -> float:
        va = self.trait_vector(a)
        vb = self.trait_vector(b)
        return float(math.sqrt(sum((x - y) ** 2 for x, y in zip(va, vb))))

    def correlation_penalty_traits(self, traits: dict[str, float]) -> dict[str, float]:
        """
        Down-weight contradictory combos (e.g. high aggressiveness + extreme patience proxy).
        Returns adjusted traits (same keys).
        """
        out = dict(traits)
        ag = float(out.get("aggressiveness", 0.5))
        # patience proxy uses inverse exploration + resilience
        patience = 0.5 * (
            float(out.get("resilience", 0.5)) + (1.0 - float(out.get("exploration", 0.5)))
        )
        clash = max(0.0, ag + patience - 1.35)
        if clash > 0:
            damp = 1.0 - min(0.45, clash * 0.9)
            out["aggressiveness"] = max(0.08, min(0.99, ag * damp))
            out["exploration"] = max(0.08, min(0.99, float(out.get("exploration", 0.5)) * (1.0 + clash * 0.08)))
        return out

    def traits_from_parents(
        self,
        parents: list[str],
        *,
        mutation_scale: float,
    ) -> tuple[dict[str, float], list[str]]:
        """Blend 2–3 parents into competitive traits with correlation guard."""
        labs = [self._lab_dict(self.cfg, p) for p in parents if p]
        t_vecs = [self._read_traits(L) for L in labs if L]
        if not t_vecs:
            t_vecs = [{k: 0.9 for k in LAB_BREEDING_TRAIT_KEYS}]
        elite = {
            k: fmean(float(tv.get(k, 0.9)) for tv in t_vecs)
            for k in LAB_BREEDING_TRAIT_KEYS
        }
        base_parent = t_vecs[0]
        raw = self._competitive_trait_breed(self.rng, base_parent, elite)
        mutated: list[str] = []
        for k in LAB_BREEDING_TRAIT_KEYS:
            base_v = elite[k]
            if abs(float(raw.get(k, 0.9)) - base_v) >= 0.06 * mutation_scale:
                mutated.append(k)
        adj = self.correlation_penalty_traits(raw)
        # Extra jitter under stagnation / aggressiveness
        j = 0.04 * mutation_scale * (0.5 + self.aggressiveness())
        for k in LAB_BREEDING_TRAIT_KEYS:
            adj[k] = max(0.08, min(0.99, float(adj[k]) + self.rng.uniform(-j, j)))
        return adj, mutated

    def maybe_sample_elite_third_parent(self) -> dict[str, Any] | None:
        """Return a lab-like dict from elite archive for extra genetic material."""
        arch = [
            x
            for x in (self.oc.get("labs_breeding_elite_archive") or [])
            if isinstance(x, dict)
        ]
        if not arch or self.rng.random() > 0.14 + 0.2 * self.aggressiveness():
            return None
        pick = max(arch, key=lambda r: float(r.get("replay_fitness") or -1e9))
        snap = pick.get("lab_snapshot")
        return dict(snap) if isinstance(snap, dict) else None

    def crossover(
        self,
        *,
        victim_branch: str,
        parents: list[str],
        mutation_scale: float,
        breeder_reason_short: str,
        breeder_reason_full: str,
        synergy_score: float,
        parent_fitness: dict[str, float],
    ) -> dict[str, Any]:
        """Build a child genome from 2–3 breeders + optional elite injection."""
        parents = [p for p in parents if p]
        if len(parents) < 2:
            parents = list(BRANCH_BREEDERS[:2])
        p1 = self._lab_dict(self.cfg, parents[0])
        p2 = self._lab_dict(self.cfg, parents[1])
        p3 = (
            self._lab_dict(self.cfg, parents[2])
            if len(parents) > 2
            else self.maybe_sample_elite_third_parent()
        )
        if p3 is None:
            p3 = {}
        base_rules = self.cfg.get("rules") if isinstance(self.cfg.get("rules"), list) else []
        r1 = list(p1.get("rules") or base_rules or [])
        r2 = list(p2.get("rules") or base_rules or [])
        r3 = list(p3.get("rules") or base_rules or []) if p3 else []

        child = copy.deepcopy(p1)
        # Numeric crossovers — average 2–3 with adaptive jitter
        def tri(fn_a: float, fn_b: float, fn_c: float | None) -> float:
            vals = [fn_a, fn_b]
            if fn_c is not None:
                vals.append(fn_c)
            m = fmean(vals)
            return m * (1.0 + self.rng.uniform(-0.07, 0.07) * mutation_scale)

        child["balance_fraction_per_window"] = clamp_balance_fraction_per_window(
            tri(
                float(p1.get("balance_fraction_per_window") or self.cfg.get("balance_fraction_per_window") or 0.03),
                float(p2.get("balance_fraction_per_window") or self.cfg.get("balance_fraction_per_window") or 0.03),
                float(p3.get("balance_fraction_per_window"))
                if p3.get("balance_fraction_per_window") is not None
                else None,
            )
        )
        child["window_minutes"] = max(
            1,
            min(
                1440,
                int(
                    round(
                        tri(
                            float(p1.get("window_minutes") or 15),
                            float(p2.get("window_minutes") or 15),
                            float(p3.get("window_minutes")) if p3.get("window_minutes") is not None else None,
                        )
                    )
                )
                + self.rng.randint(-2, 2),
            ),
        )
        pb_a = int(p1.get("paper_balance_cents") or self.cfg.get("paper_balance_cents") or 500_000)
        pb_b = int(p2.get("paper_balance_cents") or self.cfg.get("paper_balance_cents") or 500_000)
        pb_c = int(p3.get("paper_balance_cents") or pb_a) if p3 else pb_a
        base_pb = max(pb_a, pb_b, pb_c, 50_000)
        child["paper_balance_cents"] = max(
            100_000,
            min(5_000_000, base_pb + self.rng.randint(-25_000, 50_000)),
        )

        child["rules"] = self._blend_rules_multi(r1, r2, r3, self.rng)
        bfilt = self._blend_filters(p1, p2, self.rng)
        if p3:
            bfilt = {**self._blend_filters(p1, p3, self.rng), **bfilt}
        child = {**bfilt, **child}

        # Extra evolved knobs (patient stop / swing / YES floor)
        for key, spread in (
            ("swing_exit_implied_drop_pct", 8.0),
            ("no_bet_when_yes_below_pct", 12.0),
        ):
            va = float(p1.get(key) if p1.get(key) is not None else self.cfg.get(key) or 0)
            vb = float(p2.get(key) if p2.get(key) is not None else self.cfg.get(key) or 0)
            vc = float(p3.get(key)) if p3 and p3.get(key) is not None else None
            vals = [va, vb]
            if vc is not None:
                vals.append(vc)
            mid = fmean(vals)
            jitter = self.rng.uniform(-1.0, 1.0) * spread * 0.05 * mutation_scale
            if key == "no_bet_when_yes_below_pct":
                child[key] = max(1.0, min(98.0, mid + jitter))
            else:
                child[key] = max(5.0, min(90.0, mid + jitter))

        stops = [
            float(p1.get("stop_loss_trigger_pct") or -8.0),
            float(p2.get("stop_loss_trigger_pct") or -8.0),
        ]
        if p3.get("stop_loss_trigger_pct") is not None:
            stops.append(float(p3["stop_loss_trigger_pct"]))
        st_m = fmean(stops)
        child["stop_loss_trigger_pct"] = max(
            -35.0,
            min(-2.0, st_m + self.rng.uniform(-1.2, 1.2) * mutation_scale),
        )
        holds = [
            float(p1.get("min_hold_minutes_before_stop") or 30),
            float(p2.get("min_hold_minutes_before_stop") or 30),
        ]
        if p3.get("min_hold_minutes_before_stop") is not None:
            holds.append(float(p3["min_hold_minutes_before_stop"]))
        child["min_hold_minutes_before_stop"] = max(
            1.0,
            min(240.0, fmean(holds) + self.rng.uniform(-6.0, 6.0) * mutation_scale),
        )
        pe = [
            bool(p1.get("enable_patient_stop_loss", True)),
            bool(p2.get("enable_patient_stop_loss", True)),
        ]
        if p3.get("enable_patient_stop_loss") is not None:
            pe.append(bool(p3["enable_patient_stop_loss"]))
        child["enable_patient_stop_loss"] = (
            self.rng.random() < (sum(1 for x in pe if x) / len(pe))
            if pe
            else True
        )

        # Regime rule variants — inherit from majority parent then light mix
        for rk in ("rules_high_vol", "rules_low_vol", "rules_event"):
            a1, a2 = p1.get(rk), p2.get(rk)
            pick = a2 if self.rng.random() < 0.5 else a1
            if isinstance(p3.get(rk), list) and self.rng.random() < 0.22:
                pick = p3.get(rk)
            if isinstance(pick, list) and pick:
                child[rk] = copy.deepcopy(pick[:24])

        traits, mut_traits = self.traits_from_parents(parents, mutation_scale=mutation_scale)
        self._apply_competitive_traits(child, traits)

        child.pop("paper_lifetime_basis_cents", None)
        child["auto_reset_paper_on_tick_failure"] = bool(
            self.rng.random() < 0.5
            if p1.get("auto_reset_paper_on_tick_failure")
            != p2.get("auto_reset_paper_on_tick_failure")
            else p1.get("auto_reset_paper_on_tick_failure", False)
        )

        combo_syn = synergy_score
        if len(parents) > 2:
            combo_syn = float(combo_syn) * 1.02

        child["_labs_breeding_origin"] = {
            "victim": victim_branch,
            "parents": list(parents),
            "parent_ids": list(parents),
            "parent_fitness": dict(parent_fitness),
            "inherited_rules_count": len(child.get("rules") or [])
            if isinstance(child.get("rules"), list)
            else 0,
            "mutated_traits": mut_traits,
            "breeder_reason": breeder_reason_full or breeder_reason_short,
            "breeder_reason_short": breeder_reason_short,
            "synergy_score": float(combo_syn),
            "fitness_delta_vs_parents": None,
            "gen": self.rng.randint(1, 999_999),
            "mutation_scale": round(mutation_scale, 4),
            "parent_count": len(parents),
        }
        return child

    def _blend_rules_multi(
        self,
        r1: list[dict[str, Any]],
        r2: list[dict[str, Any]],
        r3: list[dict[str, Any]],
        rng: random.Random,
    ) -> list[dict[str, Any]]:
        """Crossover up to three rule lists."""
        srcs = [r for r in (r1, r2, r3) if r]
        if not srcs:
            return normalize_rules_list([])
        if len(srcs) == 1:
            return normalize_rules_list(copy.deepcopy(srcs[0][:24]))
        out: list[dict[str, Any]] = []
        n = min(len(r1), len(r2), 24)
        if r3:
            n = min(n, len(r3))
        for i in range(n):
            pick = rng.choice([x for x in (r1, r2, r3) if i < len(x)])
            other = r2 if pick is r1 else r1
            a, b = dict(pick[i]), dict(other[i] if i < len(other) else pick[i])
            if rng.random() < 0.45:
                out.append(copy.deepcopy(b if rng.random() < 0.5 else a))
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
            out.append(c)
        if not out and r1:
            out = copy.deepcopy(r1[:24])
        try:
            return normalize_rules_list(out)
        except Exception:
            return normalize_rules_list(r1 or r2 or [])

    def evaluate_adjusted_pool_score(
        self,
        row: dict[str, Any],
        pool_traits: list[dict[str, float]],
        *,
        now_iso: str,
    ) -> float:
        """Raw replay fitness + novelty bonus − age penalty (for retention messaging / tie-break)."""
        raw = float(row.get("replay_fitness") or 0.0)
        traits = row.get("traits") if isinstance(row.get("traits"), dict) else {}
        bonus = 0.0
        if pool_traits:
            dists = []
            for otr in pool_traits:
                d = math.sqrt(
                    sum(
                        (float(traits.get(k, 0.5)) - float(otr.get(k, 0.5))) ** 2
                        for k in LAB_BREEDING_TRAIT_KEYS
                    )
                )
                dists.append(d)
            if dists:
                bonus = 0.018 * min(dists)  # reward moderate novelty
        age_penalty = 0.0
        born = str(row.get("born_at") or "").strip()
        try:
            now_clean = now_iso.replace("Z", "+00:00") if now_iso.endswith("Z") else now_iso
            now_dt = dt.datetime.fromisoformat(now_clean)
            if now_dt.tzinfo is None:
                now_dt = now_dt.replace(tzinfo=dt.timezone.utc)
        except Exception:
            now_dt = dt.datetime.now(dt.timezone.utc)
        try:
            b = born.replace("Z", "+00:00") if born.endswith("Z") else born
            bd = dt.datetime.fromisoformat(b)
            if bd.tzinfo is None:
                bd = bd.replace(tzinfo=dt.timezone.utc)
            age_h = max(
                0.0,
                (now_dt.astimezone(dt.timezone.utc) - bd.astimezone(dt.timezone.utc)).total_seconds()
                / 3600.0,
            )
            age_penalty = min(0.12, age_h * 0.0008)
        except Exception:
            pass
        return raw + bonus - age_penalty

    def manage_diversity_eviction_index(self, merged: list[dict[str, Any]]) -> int:
        """
        Among the weakest quarter by replay fitness, evict the most crowded (minimum avg trait distance).
        Falls back to absolute weakest when trait data is thin.
        """
        if len(merged) <= 1:
            return 0
        idx_sorted = sorted(range(len(merged)), key=lambda i: float(merged[i].get("replay_fitness") or 0.0))
        n_cand = max(1, len(merged) // 4)
        candidates = idx_sorted[:n_cand]
        trait_rows: list[dict[str, float]] = []
        for m in merged:
            tr = m.get("traits")
            trait_rows.append(dict(tr) if isinstance(tr, dict) else {})
        worst_dist = -1.0
        worst_i = candidates[0]
        for i in candidates:
            ti = trait_rows[i]
            if not ti:
                return idx_sorted[0]
            dists = []
            for j, tj in enumerate(trait_rows):
                if i == j or not tj:
                    continue
                dists.append(
                    math.sqrt(
                        sum(
                            (float(ti.get(k, 0.5)) - float(tj.get(k, 0.5))) ** 2
                            for k in LAB_BREEDING_TRAIT_KEYS
                        )
                    )
                )
            md = fmean(dists) if dists else 1.0
            if worst_dist < 0 or md < worst_dist:
                worst_dist = md
                worst_i = i
        return worst_i

    def update_elite_archive(self, row: dict[str, Any], lab_snapshot: dict[str, Any]) -> None:
        arch = [
            x
            for x in (self.oc.get("labs_breeding_elite_archive") or [])
            if isinstance(x, dict)
        ]
        fit = float(row.get("replay_fitness") or 0.0)
        entry = {
            "at": row.get("born_at"),
            "replay_fitness": fit,
            "lab_snapshot": copy.deepcopy(lab_snapshot),
            "parent_ids": list(row.get("parent_ids") or []),
            "traits": dict(row.get("traits") or {}),
            "child_id": row.get("id"),
        }
        arch.append(entry)
        arch.sort(key=lambda x: float(x.get("replay_fitness") or -1e9), reverse=True)
        self.oc["labs_breeding_elite_archive"] = arch[:BREEDING_ELITE_ARCHIVE_CAP]

    # --- Lab A adoption ---

    def adopt_dynamic_margin(self, fitness_by_br: dict[str, float]) -> float:
        vals = [float(fitness_by_br.get(b, 0.0)) for b in BRANCH_LABS if b != BRANCH_LAB_A]
        try:
            sigma = pstdev(vals) if len(vals) > 1 else 0.0
        except Exception:
            sigma = 0.0
        base = float(self.oc.get("adoption_margin_base", BREEDING_ADOPTION_MARGIN_BASE_DEFAULT))
        try:
            scale = float(
                self.oc.get("adoption_volatility_margin_scale", BREEDING_VOLATILITY_MARGIN_SCALE_DEFAULT)
            )
        except (TypeError, ValueError):
            scale = BREEDING_VOLATILITY_MARGIN_SCALE_DEFAULT
        return base + scale * min(1.5, sigma)

    def _metrics_bundle(
        self,
        *,
        settled: list[dict[str, Any]],
        rules: list[dict[str, Any]],
        signals: list[dict[str, Any]],
        include_fees: bool,
        lab_overlay: dict[str, Any],
        branch: str,
        at_iso: str,
        trades: list[dict[str, Any]],
        max_rows: int,
    ) -> dict[str, Any]:
        return self._replay_metrics(
            settled=settled,
            rules=rules,
            signals=signals,
            include_fees=include_fees,
            lab_overlay=lab_overlay,
            full_cfg=self.cfg,
            branch=branch,
            replay_bundle=self._replay_bundle,
            open_kw=self._open_kw,
            at_iso=at_iso,
            trades=trades,
            max_rows=max_rows,
        )

    @staticmethod
    def win_rate(settled: list[dict[str, Any]]) -> float:
        if not settled:
            return 0.0
        wins = sum(1 for t in settled if int(t.get("pnl_cents") or 0) > 0)
        return wins / len(settled)

    def adopt_to_lab_a(
        self,
        *,
        end_iso: str,
        max_rows: int,
        include_fees: bool,
        fitness_by_br: dict[str, float],
        settled_by_br: dict[str, list[dict[str, Any]]],
        signals_by_branch: dict[str, list[dict[str, Any]]],
        trades_by_branch: dict[str, list[dict[str, Any]]],
        best_child: dict[str, Any],
        replacement_cooldown_active: bool,
    ) -> AdoptionEvaluation:
        """
        Safer Lab A gate: sample depth, multi-metric dominance, z-score, no-regression on risk.
        Optional confirmation stores ``labs_breeding_pending_adoption`` instead of applying.
        """
        out = AdoptionEvaluation()
        if replacement_cooldown_active:
            out.rejected_reason = "replacement_cooldown"
            return out

        st_a = settled_by_br.get(BRANCH_LAB_A) or []
        if len(st_a) < MIN_SETTLED_FOR_ADOPTION_COMPARE:
            out.rejected_reason = "lab_a_settled_lt_min"
            out.report = {"min_required": MIN_SETTLED_FOR_ADOPTION_COMPARE, "have": len(st_a)}
            return out

        lab_a_o = self._lab_dict(self.cfg, BRANCH_LAB_A)
        _, rules_a = self._rules_for_lab(self.cfg, lab_a_o)
        tr_a = trades_by_branch.get(BRANCH_LAB_A) or []
        sg_a = signals_by_branch.get(BRANCH_LAB_A) or []
        fb_a = self._metrics_bundle(
            settled=st_a,
            rules=rules_a,
            signals=sg_a,
            include_fees=include_fees,
            lab_overlay=lab_a_o,
            branch=BRANCH_LAB_A,
            at_iso=end_iso,
            trades=tr_a,
            max_rows=max_rows,
        )
        adv_a = fb_a.get("advanced_metrics") if isinstance(fb_a.get("advanced_metrics"), dict) else {}

        # Child metrics: evaluate using child's overlay at Lab A branch for apples-to-apples replay window
        lab_c_src = (
            best_child.get("lab") if isinstance(best_child.get("lab"), dict) else {}
        )
        if not lab_c_src:
            eb = str(best_child.get("engine_branch") or "").strip()
            if eb and isinstance(self.cfg.get(eb), dict):
                lab_c_src = dict(self.cfg[eb])
        _, rules_c = self._rules_for_lab(self.cfg, lab_c_src)
        # Replay uses Lab A's trade path for comparison fairness (same branch history)
        fb_c = self._metrics_bundle(
            settled=st_a,
            rules=rules_c,
            signals=sg_a,
            include_fees=include_fees,
            lab_overlay=lab_c_src,
            branch=BRANCH_LAB_A,
            at_iso=end_iso,
            trades=tr_a,
            max_rows=max_rows,
        )
        adv_c = fb_c.get("advanced_metrics") if isinstance(fb_c.get("advanced_metrics"), dict) else {}

        score_a = float(fb_a.get("score_dollars") or 0.0)
        score_c = float(fb_c.get("score_dollars") or 0.0)
        margin = self.adopt_dynamic_margin(fitness_by_br)

        sharpe_a = float(adv_a.get("sharpe") or 0.0)
        sharpe_c = float(adv_c.get("sharpe") or 0.0)
        exp_a = float(adv_a.get("expectancy_dollars") or 0.0)
        exp_c = float(adv_c.get("expectancy_dollars") or 0.0)
        calmar_a = float(adv_a.get("calmar") or 0.0)
        calmar_c = float(adv_c.get("calmar") or 0.0)
        dd_a = float(adv_a.get("max_drawdown_pct") or 0.0)
        dd_c = float(adv_c.get("max_drawdown_pct") or 0.0)
        pf_a = float(adv_a.get("profit_factor") or 0.0)
        pf_c = float(adv_c.get("profit_factor") or 0.0)
        wr_a = self.win_rate(st_a)

        metrics_win = 0
        if score_c > score_a + margin:
            metrics_win += 1
        if sharpe_c > sharpe_a:
            metrics_win += 1
        if exp_c > exp_a:
            metrics_win += 1
        if calmar_c > calmar_a:
            metrics_win += 1
        if pf_c > pf_a:
            metrics_win += 1
        _dd_win = dd_c <= dd_a + 1e-9

        labs_sigma_raw = [float(fitness_by_br.get(b, 0.0)) for b in BRANCH_LABS]
        try:
            sigma = pstdev(labs_sigma_raw) if len(labs_sigma_raw) > 1 else 0.0
        except Exception:
            sigma = 0.0
        sigma = max(1e-6, sigma)
        z = (score_c - score_a) / sigma
        out.z_score = float(z)
        out.dynamic_margin = float(margin)

        no_regress = (
            sharpe_c >= sharpe_a - LAB_A_ADOPTION_NO_REGRESS_SHARPE_TOL
            and dd_c <= dd_a + LAB_A_ADOPTION_NO_REGRESS_DD_TOL_PCT
        )

        passed = (
            metrics_win >= LAB_A_ADOPTION_MULTIMETRIC_MIN_WINS
            and z >= self.min_adoption_z()
            and no_regress
            and _dd_win
        )

        confidence_pct = max(
            0.0, min(99.9, 50.0 + 18.0 * float(z) + 5.0 * (metrics_win - 3)))
        out.report = {
            "child_id": best_child.get("id"),
            "metrics_wins": metrics_win,
            "metrics_needed": LAB_A_ADOPTION_MULTIMETRIC_MIN_WINS,
            "z_score": round(z, 4),
            "z_required": self.min_adoption_z(),
            "margin": round(margin, 5),
            "score_lab_a": round(score_a, 5),
            "score_child_on_lab_a_history": round(score_c, 5),
            "sharpe_lab_a": round(sharpe_a, 5),
            "sharpe_child": round(sharpe_c, 5),
            "expectancy_lab_a": round(exp_a, 5),
            "expectancy_child": round(exp_c, 5),
            "calmar_lab_a": round(calmar_a, 5),
            "calmar_child": round(calmar_c, 5),
            "max_dd_pct_lab_a": round(dd_a, 5),
            "max_dd_pct_child": round(dd_c, 5),
            "win_rate_lab_a_settled": round(wr_a, 5),
            "profit_factor_lab_a": round(pf_a, 5),
            "profit_factor_child": round(pf_c, 5),
            "no_regression_ok": no_regress,
            "confidence_pct": round(confidence_pct, 2),
        }

        if not passed:
            reasons = []
            if metrics_win < LAB_A_ADOPTION_MULTIMETRIC_MIN_WINS:
                reasons.append("multimetric")
            if z < self.min_adoption_z():
                reasons.append("z_score")
            if not no_regress:
                reasons.append("no_regression")
            out.rejected_reason = ",".join(reasons) or "gate_failed"
            return out

        if self.adoption_requires_confirmation():
            out.pending = True
            self.oc["labs_breeding_pending_adoption"] = {
                "proposed_at": end_iso,
                "child_id": best_child.get("id"),
                "engine_branch": best_child.get("engine_branch"),
                "report": copy.deepcopy(out.report),
                "replay_fitness_pool": float(best_child.get("replay_fitness") or 0.0),
            }
            return out

        out.adopted = True
        return out


def decline_pending_lab_a_adoption(oc: dict[str, Any]) -> bool:
    """Clear optional confirmation gate without promoting."""
    if not isinstance(oc.get("labs_breeding_pending_adoption"), dict):
        return False
    oc["labs_breeding_pending_adoption"] = None
    return True


def clear_pending_lab_a_adoption(oc: dict[str, Any]) -> None:
    """Remove pending payload after successful manual promotion."""
    oc["labs_breeding_pending_adoption"] = None
