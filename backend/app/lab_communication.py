"""
Breeding Council / Lab Think Tank — Labs B, C, D publish short lines with explicit conversational threading.

Rolling **last 6** bus lines drive prompts; each turn anchors to the latest **1–2 other labs**; optional ``reply_to`` UUID ties replies.
≤**75** chars; council **~2–9s** cadence; strategic pulse **~8–18s**; share cap relaxes after bootstrap so lines actually flow.

Not persisted. Observational only. ``GET /labs/chat`` unchanged contract (+ optional ``reply_to`` field).
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

LAB_THINK_TANK_BRANCHES = (BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D)
LAB_CHATTER_BRANCHES = LAB_THINK_TANK_BRANCHES

_slog = structlog.get_logger("kalshibot.think_tank")

_LAB_LABEL = {
    BRANCH_LAB_B: "Lab B",
    BRANCH_LAB_C: "Lab C",
    BRANCH_LAB_D: "Lab D",
}

_MSG_SOFT_MAX = 75
_CONV_MEMORY = 6  # tail scanned for “reply to last 1–2 other labs”
_RECENT_SHARE_WINDOW = 14  # shorter window — faster recovery from skew
_PROACTIVE_SHARE_CAP = 0.46  # old 0.31 caused long silent stretches (strategic pulse kept deferring)
_BOOTSTRAP_BUS_LINES = 16  # until this many rows exist, don’t throttle proactive voice (seed the thread)
_STRATEGIC_PULSE_GAP_S = (8.0, 18.0)
_INTRO_NEXT_STRATEGIC_GAP_S = (2.8, 7.5)  # first wave after intros — was tied to full pulse gap and felt dead
_COUNCIL_REPLY_GAP_S = (2.0, 9.0)
_SIM_BRANCH_PUBLISH_GAP_S = 12.0


class LabCommunicationBus:
    """Singleton ring buffer (read by ``GET /labs/chat``)."""

    _instance: LabCommunicationBus | None = None

    def __init__(self) -> None:
        self._dq: deque[dict[str, Any]] = deque(maxlen=96)

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
        reply_to: str | None = None,
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
        if reply_to:
            row["reply_to"] = reply_to
        self._dq.append(row)
        payload = {k: v for k, v in row.items() if v is not None}
        _slog.info("think_tank_message", **payload)
        return row

    def recent(self) -> list[dict[str, Any]]:
        return list(self._dq)

    def last_from_other(self, lab: str, *, max_scan: int = 40) -> dict[str, Any] | None:
        for row in reversed(list(self._dq)[-max_scan:]):
            if row.get("lab") and row["lab"] != lab:
                return row
        return None


def get_lab_communication_bus() -> LabCommunicationBus:
    return LabCommunicationBus.instance()


def conversation_tail(bus: LabCommunicationBus, limit: int = _CONV_MEMORY) -> list[dict[str, Any]]:
    """Last ``limit`` rows in the global thread (chronological)."""
    rows = list(bus._dq)
    if not rows:
        return []
    return rows[-limit:]


def thread_other_lines(bus: LabCommunicationBus, lab: str, limit: int = _CONV_MEMORY) -> list[dict[str, Any]]:
    """Recent rows in the tail from labs != ``lab``."""
    return [r for r in conversation_tail(bus, limit) if r.get("lab") and r["lab"] != lab]


def _voice_prefix(branch: str) -> str:
    """Inline speaker tag — reads like chat."""
    if branch == BRANCH_LAB_B:
        return "B:"
    if branch == BRANCH_LAB_C:
        return "C:"
    if branch == BRANCH_LAB_D:
        return "D:"
    return "?:"


def _clamp01(x: float | None) -> float | None:
    if x is None:
        return None
    return max(0.0, min(1.0, float(x)))


def _cap_msg(text: str, max_len: int = _MSG_SOFT_MAX) -> str:
    t = (text or "").strip().replace("\n", " ")
    if len(t) <= max_len:
        return t
    cut = t[: max_len - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(".,; ") + "…"


def _recent_lab_share(bus: LabCommunicationBus, lab: str, *, window: int = _RECENT_SHARE_WINDOW) -> float:
    rows = list(bus._dq)[-window:]
    if not rows:
        return 0.0
    hits = sum(1 for r in rows if r.get("lab") == lab)
    return hits / float(len(rows))


def _can_proactive_voice(bus: LabCommunicationBus, lab: str) -> bool:
    # Early thread: allow everyone to speak so the UI isn’t an empty box waiting on share math.
    if len(bus._dq) < _BOOTSTRAP_BUS_LINES:
        return True
    return _recent_lab_share(bus, lab) <= _PROACTIVE_SHARE_CAP


def _first_snapshot_ticker(snapshots: dict[str, dict[str, Any]]) -> str | None:
    for snap in snapshots.values():
        if isinstance(snap, dict):
            t = snap.get("ticker") or snap.get("market_ticker")
            if t:
                return str(t)
    return None


def _optimizer_breeding_enabled(full_cfg: dict[str, Any] | None) -> bool:
    if not full_cfg or not isinstance(full_cfg.get("optimizer"), dict):
        return False
    oc = full_cfg["optimizer"]
    return bool(oc.get("breeding_enabled", True))


def _peer_nick(peer_row: dict[str, Any]) -> str:
    lab = str(peer_row.get("lab") or "")
    if lab == BRANCH_LAB_B:
        return "B"
    if lab == BRANCH_LAB_C:
        return "C"
    if lab == BRANCH_LAB_D:
        return "D"
    return "?"


def _publish_tracked(engine: Any, bus: LabCommunicationBus, lab: str, message: str, **kw: Any) -> dict[str, Any]:
    capped = _cap_msg(message)
    row = bus.publish(lab, capped, **kw)
    engine._lab_think_tank_last_publish_mono = time.monotonic()
    return row


def _seconds_since_publish(engine: Any) -> float:
    return time.monotonic() - float(getattr(engine, "_lab_think_tank_last_publish_mono", 0.0) or 0.0)


def _tick_short(s: str | None, n: int = 10) -> str:
    return (s or "").strip()[:n] or "?"


def _contextual_strategic_pulse(
    branch: str,
    bus: LabCommunicationBus,
    *,
    ticker_hint: str | None,
    scanned: int,
    breeding_enabled: bool,
) -> tuple[str, float | None, str, str | None]:
    """
    Dialogue-first pulse: anchor to the latest 1–2 *other* labs in the rolling tail.
    Always reads like B/C/D reacting to each other; ``reply_to`` ties to the newest anchor line.
    """
    tk = _tick_short(ticker_hint, 8)
    vp = _voice_prefix(branch)
    others = thread_other_lines(bus, branch, _CONV_MEMORY)
    last_o = others[-1] if others else None
    prev_o = others[-2] if len(others) >= 2 else None
    reply_to: str | None = str(last_o["id"]) if last_o and last_o.get("id") else None

    team = ""
    if breeding_enabled and random.random() < 0.38:
        team = random.choice(
            [
                "Team—breed this for next kid.",
                "Team—edge worth child genome.",
                "Team—lock thread for crossover.",
                "",
            ]
        ).strip()

    nick_last = _peer_nick(last_o) if last_o else ""
    nick_prev = _peer_nick(prev_o) if prev_o else ""
    frag_last = _cap_msg(str((last_o or {}).get("message") or ""), 22)

    # Two distinct other voices in-thread → acknowledge both (conversation density).
    if last_o and prev_o and nick_last != nick_prev:
        pools = {
            BRANCH_LAB_B: [
                f"{vp} heard {nick_prev} then {nick_last}—{tk} still risky.",
                f"{vp} agree {nick_last} tempting—{nick_prev} also loud; passing.",
                f"{vp} interesting—{nick_prev} vs {nick_last}? Too thin for me.",
                f"{vp} yeah {nick_last} edge cute—{nick_prev} worried me too.",
            ],
            BRANCH_LAB_C: [
                f"{vp} that edge tempting—{nick_prev} cautious but I'm nibbling {tk}.",
                f"{vp} I'm with {nick_last} here—{nick_prev} fair but sizes tiny.",
                f"{vp} disagree {nick_prev} a bit—{nick_last} momentum wins {tk}.",
                f"{vp} interesting—splitting {nick_prev}/{nick_last}; small YES.",
            ],
            BRANCH_LAB_D: [
                f"{vp} wild lane—between {nick_prev} & {nick_last}, I probe tail.",
                f"{vp} I'm with {nick_last}—{nick_prev} worry noted; hybrid test.",
                f"{vp} chaos ok—{nick_prev}+{nick_last}? sandbox both views.",
                f"{vp} remix {nick_last} take—{nick_prev} keeps me honest.",
            ],
        }
        msg = random.choice(pools[branch])
    elif last_o:
        pools = {
            BRANCH_LAB_B: [
                f"{vp} responding {nick_last}—'{frag_last}' yeah but risky.",
                f"{vp} agree {nick_last} some—but {tk} too ugly for size.",
                f"{vp} interesting—I'll stay flat after {nick_last}.",
                f"{vp} hear you {nick_last}; I'm passing {tk} tho.",
                f"{vp} what do you think team? I'm NO‑tilt post-{nick_last}.",
            ],
            BRANCH_LAB_C: [
                f"{vp} that edge tempting—{nick_last} I'm still small {tk}.",
                f"{vp} agree w {nick_last} but sizing down—liquidity meh.",
                f"{vp} interesting—riding {nick_last}; tiny starter.",
                f"{vp} pushback gentle: {nick_last} ok—I clip risk.",
                f"{vp} hearing {nick_last}; momentum yes, cap tight.",
            ],
            BRANCH_LAB_D: [
                f"{vp} wild—since {nick_last}: test convex scratch.",
                f"{vp} building on {nick_last}—weird hedge worth paper.",
                f"{vp} I'm with {nick_last} on asymmetry—probe tails.",
                f"{vp} interesting {nick_last}; GA log this variant.",
                f"{vp} remix {nick_last}'s frame—sandbox ladder.",
            ],
        }
        msg = random.choice(pools[branch])
    else:
        # Cold thread — invite others so startup isn't a monologue box.
        cold = {
            BRANCH_LAB_B: [
                f"{vp} scanning {tk}—C+D what do you think?",
                f"{vp} cautious ping {tk}; waiting on team.",
                f"{vp} risk-first—need your reads.",
            ],
            BRANCH_LAB_C: [
                f"{vp} {tk} looks spicy—B+D agree?",
                f"{vp} hunting edge—talk to me team.",
                f"{vp} aggressive tiny—who else in?",
            ],
            BRANCH_LAB_D: [
                f"{vp} hypothesis {tk}—B+C poke holes?",
                f"{vp} chaos probe ready—need sane brakes.",
                f"{vp} experimental—team sanity-check me.",
            ],
        }
        msg = random.choice(cold[branch])
        reply_to = None

    if team:
        msg = _cap_msg(msg + " " + team)
    else:
        msg = _cap_msg(msg)

    conf_hi = 0.82 if branch == BRANCH_LAB_C else 0.78
    return msg, _clamp01(random.uniform(0.44, conf_hi)), "strategic_pulse", reply_to


def _council_reply_message(
    branch: str,
    peer_row: dict[str, Any],
    bus: LabCommunicationBus,
    *,
    breeding_enabled: bool,
) -> tuple[str, float | None]:
    voc = _voice_prefix(branch)
    nick = _peer_nick(peer_row)
    peer_lab = str(peer_row.get("lab") or "")
    tag = ""
    if breeding_enabled and random.random() < 0.28:
        tag = random.choice([" Breed it.", " Kid?", " GA?", ""])

    others = thread_other_lines(bus, branch, _CONV_MEMORY)
    nick2 = ""
    if len(others) >= 2:
        cand = others[-2]
        if cand.get("id") != peer_row.get("id"):
            nick2 = _peer_nick(cand)

    dual = ""
    if nick2 and nick2 != nick and random.random() < 0.42:
        dual = random.choice(
            [
                f" ({nick2}+{nick})",
                f" re {nick2}+{nick}",
                f" heard {nick2} too—",
            ]
        )

    if branch == BRANCH_LAB_B:
        opts = [
            f"{voc} hearing {nick}: thin—mosquito size.{tag}",
            f"{voc} {nick} loud—hedge first.{dual}{tag}",
            f"{voc} resp {nick}: weak tape—cooling.{tag}",
            f"{voc} agree {nick} some—but risk says wait.{tag}",
        ]
        if peer_lab == BRANCH_LAB_C:
            opts.extend([f"{voc} C hot—I'm flat til calm.{tag}", f"{voc} C rush—fade speed only.{tag}"])
        elif peer_lab == BRANCH_LAB_D:
            opts.extend([f"{voc} D wild—tiny stamp OK.{tag}", f"{voc} D chaos—leash tight.{tag}"])
        text = random.choice(opts).strip()
        return _cap_msg(text), random.uniform(0.44, 0.62)

    if branch == BRANCH_LAB_C:
        opts = [
            f"{voc} fair {nick}—still small.{tag}",
            f"{voc} piggyback {nick}—slow scale.{dual}{tag}",
            f"{voc} interesting {nick}—nibble only.{tag}",
            f"{voc} agree but clip size—edge real.{tag}",
        ]
        if peer_lab == BRANCH_LAB_B:
            opts.extend([f"{voc} B tight—heard; dip probe.{tag}", f"{voc} B worry—clip risk.{tag}"])
        elif peer_lab == BRANCH_LAB_D:
            opts.extend([f"{voc} D weird—pair momentum.{tag}", f"{voc} D chaos—stops on.{tag}"])
        text = random.choice(opts).strip()
        return _cap_msg(text), random.uniform(0.58, 0.82)

    opts = [
        f"{voc} vibes {nick}—remix tails.{tag}",
        f"{voc} {nick} noted—sandbox twist.{dual}{tag}",
        f"{voc} building on {nick}: hedge probe.{tag}",
        f"{voc} interesting—breed what survives.{tag}",
    ]
    text = random.choice(opts).strip()
    return _cap_msg(text), random.uniform(0.42, 0.78)


def publish_council_reply_if_due(
    engine: Any,
    branch: str,
    bus: LabCommunicationBus,
    *,
    breeding_enabled: bool,
) -> None:
    """Prefer answering another lab — chains unfold across B→C→D loop ticks."""
    if branch not in LAB_THINK_TANK_BRANCHES:
        return
    peer = bus.last_from_other(branch)
    if not peer:
        return
    gap_lo, gap_hi = _COUNCIL_REPLY_GAP_S
    need = random.uniform(gap_lo, gap_hi)
    if _seconds_since_publish(engine) < need:
        return

    msg, conf = _council_reply_message(branch, peer, bus, breeding_enabled=breeding_enabled)
    pid = peer.get("id")
    _publish_tracked(
        engine,
        bus,
        branch,
        msg,
        confidence=conf,
        action="council_reply",
        kind="say",
        reply_to=str(pid) if pid else None,
    )


def publish_strategic_pulse_if_due(
    engine: Any,
    branch: str,
    bus: LabCommunicationBus,
    *,
    snapshots: dict[str, dict[str, Any]],
    scanned: int,
    breeding_enabled: bool,
) -> None:
    if branch not in LAB_THINK_TANK_BRANCHES:
        return
    now_m = time.monotonic()
    nxt = float(getattr(engine, "_lab_think_tank_next_pulse_mono", 0.0) or 0.0)

    if nxt <= 0.0:
        engine._lab_think_tank_next_pulse_mono = now_m + random.uniform(2.0, 6.0)
        return

    if now_m < nxt:
        return

    if not _can_proactive_voice(bus, branch):
        engine._lab_think_tank_next_pulse_mono = now_m + random.uniform(4.0, 11.0)
        return

    engine._lab_think_tank_next_pulse_mono = now_m + random.uniform(*_STRATEGIC_PULSE_GAP_S)

    hint = _first_snapshot_ticker(snapshots)

    msg, conf, kind, reply_to = _contextual_strategic_pulse(
        branch,
        bus,
        ticker_hint=hint or "BOOK",
        scanned=max(1, scanned),
        breeding_enabled=breeding_enabled,
    )
    _publish_tracked(engine, bus, branch, msg, confidence=conf, action=kind, reply_to=reply_to)


def publish_think_tank_break_silence_if_due(
    engine: Any,
    branch: str,
    bus: LabCommunicationBus,
    *,
    snapshots: dict[str, dict[str, Any]],
    scanned: int,
    breeding_enabled: bool,
) -> None:
    """
    Share-cap can defer strategic pulses forever for one lab (mostly C). If this branch has been quiet
    awhile while still ``over quota``, emit one contextual line anyway so B/C/D stay visible.
    """
    if branch not in LAB_THINK_TANK_BRANCHES:
        return
    if len(bus._dq) < _BOOTSTRAP_BUS_LINES:
        return
    if _can_proactive_voice(bus, branch):
        return
    if _seconds_since_publish(engine) < 14.0:
        return
    if random.random() > 0.42:
        return

    now_m = time.monotonic()
    hint = _first_snapshot_ticker(snapshots)
    msg, conf, _, reply_to = _contextual_strategic_pulse(
        branch,
        bus,
        ticker_hint=hint or "BOOK",
        scanned=max(1, scanned),
        breeding_enabled=breeding_enabled,
    )
    _publish_tracked(engine, bus, branch, msg, confidence=conf, action="strategic_pulse_break", reply_to=reply_to)
    engine._lab_think_tank_next_pulse_mono = now_m + random.uniform(*_STRATEGIC_PULSE_GAP_S)


def think_tank_on_ranked_market(
    engine: Any,
    branch: str,
    *,
    idx: int,
    kind: str | None,
    ticker: str,
    implied_yes: float | None,
    bus: LabCommunicationBus,
) -> None:
    if branch not in LAB_THINK_TANK_BRANCHES:
        return
    if idx != 0:
        return
    if random.random() > 0.22:
        return
    if bool(getattr(engine, "_lab_think_tank_market_note_sent", False)):
        return
    if _seconds_since_publish(engine) < 4.0:
        return

    tk = _tick_short(ticker, 12)
    py = _clamp01(implied_yes)
    pct = int(round((py or 0.0) * 100)) if py is not None else None
    ys = f"{pct}" if pct is not None else "?"

    peer = bus.last_from_other(branch)
    pid = peer.get("id") if peer else None
    nk = _peer_nick(peer) if peer else ""

    if branch == BRANCH_LAB_B:
        core = random.choice(
            [
                f"{tk}@{ys}¢ thin edge—skip.",
                f"top {tk}: fragile book—wait.",
                f"{tk}: cautious ping.",
            ]
        )
    elif branch == BRANCH_LAB_C:
        core = random.choice(
            [
                f"{tk}@{ys}¢ tempting tiny.",
                f"leader {tk}: starter YES.",
                f"{tk} rank hot—nip.",
            ]
        )
    else:
        core = random.choice(
            [
                f"{tk}@{ys}¢ weird tail—log.",
                f"{tk}: chaos EV note.",
                f"D poke {tk}; paper.",
            ]
        )

    if peer and nk and random.random() < 0.55:
        msg = _cap_msg(f"After {nk}: {core}")
    else:
        msg = _cap_msg(core)

    engine._lab_think_tank_market_note_sent = True
    _publish_tracked(
        engine,
        bus,
        branch,
        msg,
        confidence=py if py is not None else random.uniform(0.5, 0.72),
        action="market_ping",
        reply_to=str(pid) if pid else None,
    )


def think_tank_on_sim_open(
    engine: Any,
    branch: str,
    *,
    ticker: str,
    side: str,
    implied_yes: float | None,
    rule_name: str,
    bus: LabCommunicationBus,
) -> None:
    if branch not in LAB_THINK_TANK_BRANCHES:
        return
    if _seconds_since_publish(engine) < _SIM_BRANCH_PUBLISH_GAP_S:
        return
    tk = _tick_short(ticker, 10)
    py = _clamp01(implied_yes)
    pct = int(round((py or 0.0) * 100)) if py is not None else None
    rn = _tick_short(rule_name, 14)
    ys = f"{pct}" if pct is not None else "?"

    peer = bus.last_from_other(branch)
    pid = peer.get("id") if peer and random.random() < 0.35 else None

    if branch == BRANCH_LAB_B:
        msg = _cap_msg(f"Sim {side.upper()} {tk} @{ys}—{rn}; tiny.")
    elif branch == BRANCH_LAB_C:
        msg = _cap_msg(f"Fill {side.upper()} {tk} @{ys}—{rn}; press.")
    else:
        msg = _cap_msg(f"Sandbox {side.upper()} {tk} @{ys}—{rn}; GA.")

    _publish_tracked(engine, bus, branch, msg, confidence=py, action=f"open_sim_{side}", reply_to=str(pid) if pid else None)


def finalize_think_tank_tick(
    engine: Any,
    branch: str,
    snapshots: dict[str, dict[str, Any]],
    scanned: int,
    *,
    full_cfg: dict[str, Any] | None = None,
) -> None:
    """Reply lane first (fast chain), then contextual pulse."""
    if branch not in LAB_THINK_TANK_BRANCHES:
        return
    bus = get_lab_communication_bus()
    breeding_enabled = _optimizer_breeding_enabled(full_cfg)

    if not getattr(engine, "_lab_think_tank_intro_done", False):
        engine._lab_think_tank_intro_done = True
        vp = _voice_prefix(branch)
        intro = _cap_msg(
            random.choice(
                [
                    f"{vp} live—talk to me team.",
                    f"{vp} online—react to each other.",
                    f"{vp} here—B+C+D ping this tick.",
                ]
            )
        )
        _publish_tracked(engine, bus, branch, intro, confidence=0.55, action="council_intro")
        engine._lab_think_tank_next_pulse_mono = time.monotonic() + random.uniform(*_INTRO_NEXT_STRATEGIC_GAP_S)

    publish_council_reply_if_due(engine, branch, bus, breeding_enabled=breeding_enabled)
    publish_strategic_pulse_if_due(
        engine,
        branch,
        bus,
        snapshots=snapshots,
        scanned=scanned,
        breeding_enabled=breeding_enabled,
    )
    publish_think_tank_break_silence_if_due(
        engine,
        branch,
        bus,
        snapshots=snapshots,
        scanned=scanned,
        breeding_enabled=breeding_enabled,
    )

    tc = int(getattr(engine, "_tick_count", 0) or 0)
    lab_ord = {BRANCH_LAB_B: 0, BRANCH_LAB_C: 1, BRANCH_LAB_D: 2}.get(branch, 0)
    if breeding_enabled and (tc + lab_ord) % 19 == 0 and random.random() < 0.26:
        tail = conversation_tail(bus, 2)
        anchor_id = str(tail[-1]["id"]) if tail else None
        msg = _cap_msg(
            random.choice(
                [
                    "Team—strong edge for next child genome.",
                    "Council sync: breed this thread.",
                    "Lock meme—crossover next.",
                ]
            )
        )
        if _seconds_since_publish(engine) >= 10.0:
            _publish_tracked(engine, bus, branch, msg, confidence=0.62, action="breeding_whisper", reply_to=anchor_id)


finalize_lab_chatter_tick = finalize_think_tank_tick
chatter_on_ranked_market = think_tank_on_ranked_market
chatter_on_sim_open = think_tank_on_sim_open
