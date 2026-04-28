"""
In-process lab hive chat: Labs B / C / D continuously publish short analyst-style lines for the dashboard.

Does **not** persist to SQLite; optional heartbeat + reaction traffic only.
"""

from __future__ import annotations

import random
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

import structlog

from .branch_config import BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D

LAB_CHATTER_BRANCHES = (BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D)

_slog = structlog.get_logger("kalshibot.lab_chat")

_LAB_LABEL = {
    BRANCH_LAB_B: "Lab B",
    BRANCH_LAB_C: "Lab C",
    BRANCH_LAB_D: "Lab D",
}


class LabCommunicationBus:
    """Singleton ring buffer of recent hive messages (read by ``GET /labs/chat``)."""

    _instance: LabCommunicationBus | None = None

    def __init__(self) -> None:
        self._dq: deque[dict[str, Any]] = deque(maxlen=80)

    @classmethod
    def instance(cls) -> LabCommunicationBus:
        if cls._instance is None:
            cls._instance = LabCommunicationBus()
        return cls._instance

    def publish(
        self,
        lab: str,
        message: str,
        *,
        confidence: float | None = None,
        action: str | None = None,
        kind: str = "say",
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "ts_iso": datetime.now(timezone.utc).isoformat(),
            "lab": lab,
            "label": _LAB_LABEL.get(lab, lab),
            "message": message,
            "kind": kind,
        }
        if confidence is not None:
            row["confidence"] = round(float(confidence), 4)
        if action:
            row["action"] = action
        self._dq.append(row)
        payload = {k: v for k, v in row.items() if v is not None}
        _slog.info("lab_chat_message", **payload)
        return row

    def recent(self) -> list[dict[str, Any]]:
        return list(self._dq)

    def last_from_other(self, lab: str, *, max_scan: int = 40) -> dict[str, Any] | None:
        """Most recent message from a different lab (for reactions)."""
        for row in reversed(list(self._dq)[-max_scan:]):
            if row.get("lab") and row["lab"] != lab and row.get("kind") != "reaction":
                return row
        return None


def get_lab_communication_bus() -> LabCommunicationBus:
    return LabCommunicationBus.instance()


def _clamp01(x: float | None) -> float | None:
    if x is None:
        return None
    return max(0.0, min(1.0, float(x)))


def _heartbeat_message(lab: str, *, ticker_hint: str | None, scanned: int) -> tuple[str, float | None, str]:
    tick = (ticker_hint or "SCAN").strip()[:44]
    if lab == BRANCH_LAB_B:
        msg = random.choice(
            [
                f"Still treating {tick} as fragile — waiting for cleaner edge before size.",
                f"Holding discipline on {tick}: capital preservation beats FOMO.",
                f"Risk budget check: open interest context on {tick} looks noisy; staying patient.",
                f"Correlation risk is on my mind — not chasing {tick} until structure improves.",
            ]
        )
        conf = random.uniform(0.42, 0.62)
        return msg, _clamp01(conf), "heartbeat"
    if lab == BRANCH_LAB_C:
        msg = random.choice(
            [
                f"Pushing tempo on {tick} — implied looks exploitable if liquidity cooperates.",
                f"I want this tape on {tick}: aggression pays when rules align.",
                f"{tick}: sizing up mentally; microstructure still needs to confirm.",
                f"Heat check on {tick} — prepared to engage fast if skip guards clear.",
            ]
        )
        conf = random.uniform(0.58, 0.88)
        return msg, _clamp01(conf), "heartbeat"
    msg = random.choice(
        [
            f"Treating {tick} as a sandbox — testing a weird thesis that breaks normal priors.",
            f"{tick}: I'm hunting convexity even if it looks ugly on first pass.",
            f"Wildcard read on {tick} — happy to be wrong quickly and rotate.",
            f"Experimental lane on {tick}: hypothesis over elegance.",
        ]
    )
    conf = random.uniform(0.35, 0.92)
    return msg, _clamp01(conf), "heartbeat"


def _peer_reaction(lab: str, peer_row: dict[str, Any]) -> tuple[str, float | None]:
    peer = str(peer_row.get("label") or peer_row.get("lab") or "peer")
    snippet = str(peer_row.get("message") or "")[:120]
    if lab == BRANCH_LAB_B:
        text = random.choice(
            [
                f"@{peer}: hear you — I'm trimming conviction until that thesis ages a minute.",
                f"{peer}'s last take ({snippet[:48]}…) sounds spicy; I'm staying flat until spread tightens.",
                f"Respectfully disagree with {peer} on tone — I'd rather miss than force size here.",
            ]
        )
        return text, random.uniform(0.45, 0.62)
    if lab == BRANCH_LAB_C:
        text = random.choice(
            [
                f"@{peer} yes — momentum agrees; I'm leaning in if fees stay sane.",
                f"{peer} flagged it first; I'm watching the same skew.",
                f"Piggybacking {peer}: if that line holds, I'm pressing.",
            ]
        )
        return text, random.uniform(0.62, 0.86)
    text = random.choice(
        [
            f"{peer} — I'm remixing your idea with a weirder prior; let's see who bleeds less.",
            f"I'll fade {peer} politely unless vol confirms; chaos is data.",
            f"Interesting from {peer}; I'm stress-testing the opposite tail too.",
        ]
    )
    return text, random.uniform(0.38, 0.78)


def publish_peer_reaction_if_due(engine: Any, branch: str, bus: LabCommunicationBus) -> None:
    if branch not in LAB_CHATTER_BRANCHES:
        return
    last_r = float(getattr(engine, "_lab_chatter_last_reaction_mono", 0.0) or 0.0)
    if time.monotonic() - last_r < 18.0:
        return
    if random.random() > 0.34:
        return
    peer = bus.last_from_other(branch)
    if not peer:
        return
    msg, conf = _peer_reaction(branch, peer)
    bus.publish(branch, msg, confidence=conf, kind="reaction")
    engine._lab_chatter_last_reaction_mono = time.monotonic()


def publish_heartbeat_if_due(
    engine: Any,
    branch: str,
    *,
    snapshots: dict[str, dict[str, Any]],
    scanned: int,
    bus: LabCommunicationBus,
) -> None:
    if branch not in LAB_CHATTER_BRANCHES:
        return
    now_m = time.monotonic()
    nxt = float(getattr(engine, "_lab_chatter_next_heartbeat_mono", 0.0) or 0.0)
    # Prime cadence without blasting three heartbeats on the very first tick.
    if nxt <= 0.0:
        engine._lab_chatter_next_heartbeat_mono = now_m + random.uniform(20.0, 38.0)
        return
    if now_m < nxt:
        return
    engine._lab_chatter_next_heartbeat_mono = now_m + random.uniform(25.0, 45.0)
    hint = None
    for snap in snapshots.values():
        if isinstance(snap, dict):
            t = snap.get("ticker") or snap.get("market_ticker")
            if t:
                hint = str(t)
                break
    msg, conf, kind = _heartbeat_message(branch, ticker_hint=hint or "markets", scanned=scanned)
    bus.publish(branch, msg, confidence=conf, action=kind)


def chatter_on_ranked_market(
    engine: Any,
    branch: str,
    *,
    idx: int,
    kind: str | None,
    ticker: str,
    implied_yes: float | None,
    bus: LabCommunicationBus,
) -> None:
    """Fire immediate chatter on ranked-market evaluation (throttled per tick)."""
    if branch not in LAB_CHATTER_BRANCHES:
        return
    n = int(getattr(engine, "_lab_chatter_msgs_this_tick", 0) or 0)
    if n >= 4:
        return
    tk = (ticker or "").strip()[:44] or "?"
    py = _clamp01(implied_yes)
    pct = int(round((py or 0.0) * 100)) if py is not None else None

    if idx == 0:
        if branch == BRANCH_LAB_B:
            msg = f"Scanning top candidate {tk}{f' — YES ~{pct}%' if pct is not None else ''}; verifying liquidity + rule fit before sizing."
        elif branch == BRANCH_LAB_C:
            msg = f"Front-running my queue on {tk}{f': YES ~{pct}%' if pct is not None else ''} — if edge holds I'm deploying fast."
        else:
            msg = f"Weird-first look at {tk}{f' ({pct}% YES vibe)' if pct is not None else ''} — probing a non-obvious angle."
        conf = py if py is not None else random.uniform(0.5, 0.75)
        bus.publish(branch, msg, confidence=_clamp01(conf), action="market_scan")
        engine._lab_chatter_msgs_this_tick = n + 1
        return

    if kind == "no_rule" and idx < 3 and random.random() < 0.55:
        if branch == BRANCH_LAB_B:
            msg = f"No rule match on {tk} @ YES ~{pct}% — skipping; edge isn't proved under my thresholds."
        elif branch == BRANCH_LAB_C:
            msg = f"Skipping {tk} for now — no aligned rule, even though YES ~{pct}% tempted a punt."
        else:
            msg = f"Pass on {tk} (YES ~{pct}%): I'll chase chaos elsewhere unless a rule lights up."
        bus.publish(branch, msg, confidence=_clamp01(py), action="skip_no_rule")
        engine._lab_chatter_msgs_this_tick = n + 1


def chatter_on_sim_open(engine: Any, branch: str, *, ticker: str, side: str, implied_yes: float | None, rule_name: str, bus: LabCommunicationBus) -> None:
    if branch not in LAB_CHATTER_BRANCHES:
        return
    tk = (ticker or "").strip()[:44]
    py = _clamp01(implied_yes)
    pct = int(round((py or 0.0) * 100)) if py is not None else None
    rn = (rule_name or "").strip()[:40]
    if branch == BRANCH_LAB_B:
        msg = f"Hedge mindset: opened sim {side.upper()} on {tk} (~{pct}% YES) via “{rn}” — small, reversible risk."
    elif branch == BRANCH_LAB_C:
        msg = f"Locked sim {side.upper()} on {tk} (~{pct}% YES) — rule “{rn}”; pressing edge while flow permits."
    else:
        msg = f"Sandbox fill {side.upper()} on {tk} (~{pct}% YES) — rule “{rn}”; testing a funky hypothesis live in paper."
    bus.publish(branch, msg, confidence=py, action=f"open_sim_{side}")


def finalize_lab_chatter_tick(engine: Any, branch: str, snapshots: dict[str, dict[str, Any]], scanned: int) -> None:
    """Heartbeat + optional peer reactions at end of ``tick_once`` for Labs B/C/D."""
    if branch not in LAB_CHATTER_BRANCHES:
        return
    bus = get_lab_communication_bus()
    publish_heartbeat_if_due(engine, branch, snapshots=snapshots, scanned=scanned, bus=bus)
    publish_peer_reaction_if_due(engine, branch, bus)
