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
                f"I'm clipping risk on {tick}; waiting for a cleaner entry and tighter spread before size.",
                f"Capital-first posture on {tick}: if edge is marginal, I pass and protect bankroll.",
                f"Checked {scanned} rows and still cautious on {tick} — signal quality is mixed.",
                f"Not anti-trade, just anti-sloppy: {tick} needs better structure before I commit.",
            ]
        )
        conf = random.uniform(0.42, 0.62)
        return msg, _clamp01(conf), "heartbeat"
    if lab == BRANCH_LAB_C:
        msg = random.choice(
            [
                f"I'm stalking {tick} for momentum continuation — if the rule lights, I press.",
                f"{tick} still looks tradeable to me; aggression wins when microstructure confirms.",
                f"I like the tape shape on {tick}; ready to move fast if guards clear.",
                f"I'm not waiting forever on {tick} — if edge survives one more pass, I'm in.",
            ]
        )
        conf = random.uniform(0.58, 0.88)
        return msg, _clamp01(conf), "heartbeat"
    msg = random.choice(
        [
            f"I'm running an experimental angle on {tick}; ugly setups can still pay with disciplined exits.",
            f"{tick} is weird enough to like — I'm testing the non-consensus tail again.",
            f"Wildcard mode: probing {tick} for convexity even if it looks uncomfortable.",
            f"I'll take the strange side on {tick} when the crowd gets one-sided.",
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
                f"{peer}, I hear your edge call — I'm aligned directionally but sizing smaller.",
                f"I agree with {peer}'s read, but only after spread and slippage calm down.",
                f"{peer}'s point ({snippet[:52]}...) is fair; I'll wait one extra cycle before committing.",
                f"{peer}, that's bold — I'll fade speed, not necessarily direction.",
            ]
        )
        return text, random.uniform(0.45, 0.62)
    if lab == BRANCH_LAB_C:
        text = random.choice(
            [
                f"{peer} is on my wavelength here — if liquidity holds, I'm pressing this.",
                f"I back {peer}'s thesis; execution speed decides whether this prints.",
                f"{peer} called it early, I'm ready to amplify if the next check confirms.",
                f"I hear {peer}; this is where conviction should actually compound.",
            ]
        )
        return text, random.uniform(0.62, 0.86)
    text = random.choice(
        [
            f"{peer} might be right, but I'm stress-testing the opposite tail before I copy it.",
            f"I like {peer}'s angle; I'm adding chaos controls and taking the weirder variant.",
            f"{peer}, that setup is spicy — I'm running a higher-variance version in paper.",
            f"I disagree with {peer} on timing, not thesis; entering only on volatility expansion.",
        ]
    )
    return text, random.uniform(0.38, 0.78)


def publish_peer_reaction_if_due(engine: Any, branch: str, bus: LabCommunicationBus) -> None:
    if branch not in LAB_CHATTER_BRANCHES:
        return
    last_r = float(getattr(engine, "_lab_chatter_last_reaction_mono", 0.0) or 0.0)
    if time.monotonic() - last_r < 10.0:
        return
    if random.random() > 0.78:
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
    # Prime cadence without blasting all branches on first tick.
    if nxt <= 0.0:
        engine._lab_chatter_next_heartbeat_mono = now_m + random.uniform(8.0, 18.0)
        return
    if now_m < nxt:
        return
    engine._lab_chatter_next_heartbeat_mono = now_m + random.uniform(15.0, 35.0)
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
    if n >= 6:
        return
    tk = (ticker or "").strip()[:44] or "?"
    py = _clamp01(implied_yes)
    pct = int(round((py or 0.0) * 100)) if py is not None else None

    if idx == 0:
        if branch == BRANCH_LAB_B:
            msg = f"Top read is {tk}{f' (~{pct}% YES)' if pct is not None else ''}; cautious confirmation pass before any size."
        elif branch == BRANCH_LAB_C:
            msg = f"Lead candidate {tk}{f' (~{pct}% YES)' if pct is not None else ''}; if edge survives, I'm hitting this quickly."
        else:
            msg = f"I want to test a weird angle on {tk}{f' (~{pct}% YES vibe)' if pct is not None else ''}; this one has asymmetry."
        conf = py if py is not None else random.uniform(0.5, 0.75)
        bus.publish(branch, msg, confidence=_clamp01(conf), action="market_scan")
        engine._lab_chatter_msgs_this_tick = n + 1
        return

    if kind == "no_rule" and idx < 4 and random.random() < 0.72:
        if branch == BRANCH_LAB_B:
            msg = f"No rule match on {tk} @ YES ~{pct}% — skipping; edge isn't proved under my thresholds."
        elif branch == BRANCH_LAB_C:
            msg = f"Skipping {tk} for now — no aligned rule, even though YES ~{pct}% tempted a punt."
        else:
            msg = f"Pass on {tk} (YES ~{pct}%): I'll chase chaos elsewhere unless a rule lights up."
        bus.publish(branch, msg, confidence=_clamp01(py), action="skip_no_rule")
        engine._lab_chatter_msgs_this_tick = n + 1
    elif idx < 3 and random.random() < 0.48:
        peer = bus.last_from_other(branch)
        if peer:
            msg, conf = _peer_reaction(branch, peer)
            bus.publish(branch, msg, confidence=conf, action="peer_reaction", kind="reaction")
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
    # Often reply twice in one tick to keep the team chat feeling alive.
    if random.random() < 0.32:
        publish_peer_reaction_if_due(engine, branch, bus)
