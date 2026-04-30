"""
Breeding Council / Lab Think Tank — Labs B, C, D, E publish short lines with explicit conversational threading.

Rolling **last 6** bus lines drive prompts; every line reacts to **other labs** by name; optional ``reply_to`` UUID ties replies.
**~58** chars; **anti-repeat** vs last 8 lines; **rotation boost** + **hot-lab damp** when one breeder dominates; council **6–15s**; no ticker ranked hook.

Not persisted. Observational only. ``GET /labs/chat`` unchanged contract (+ optional ``reply_to`` field).
"""

from __future__ import annotations

import random
import re
import time
import uuid
from collections import Counter, deque
from datetime import datetime, timezone
from typing import Any

import structlog

from .branch_config import BRANCH_BREEDERS, BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D, BRANCH_LAB_E
from .settings_env import env

LAB_THINK_TANK_BRANCHES = BRANCH_BREEDERS
LAB_CHATTER_BRANCHES = LAB_THINK_TANK_BRANCHES

_slog = structlog.get_logger("kalshibot.think_tank")

_LAB_LABEL = {
    BRANCH_LAB_B: "Lab B",
    BRANCH_LAB_C: "Lab C",
    BRANCH_LAB_D: "Lab D",
    BRANCH_LAB_E: "Lab E",
}

_MSG_SOFT_MAX = 58  # blunt council lines; keep tight for ticker + UI
_ADVERSARIAL_REPLY_FRACTION = 0.40
_ADVERSARIAL_STRATEGIC_FRACTION = 0.40
_CONV_MEMORY = 6  # tail scanned for “reply to last 1–2 other labs”
_RECENT_SHARE_WINDOW = 14  # shorter window — faster recovery from skew
_PROACTIVE_SHARE_CAP = 0.46  # old 0.31 caused long silent stretches (strategic pulse kept deferring)
_BOOTSTRAP_BUS_LINES = 16  # until this many rows exist, don’t throttle proactive voice (seed the thread)
_STRATEGIC_PULSE_GAP_S = (7.0, 16.0)
_INTRO_NEXT_STRATEGIC_GAP_S = (3.0, 8.0)
_COUNCIL_REPLY_GAP_S = (6.0, 15.0)
_SIM_BRANCH_PUBLISH_GAP_S = 12.0
_ANTIREPEAT_LOOKBACK = 8  # skip lines too similar to these recent bodies


class LabCommunicationBus:
    """Singleton ring buffer (read by ``GET /labs/chat``)."""

    _instance: LabCommunicationBus | None = None

    def __init__(self) -> None:
        self._dq: deque[dict[str, Any]] = deque(maxlen=96)
        # Ephemeral signal for breeder TradingEngine ticks (refreshed each Think Tank finalize + diversify).
        self._engine_council_signal: dict[str, Any] | None = None

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
        # Only log at INFO when explicitly enabled — DEBUG still flooded consoles when LOG_LEVEL=DEBUG.
        if env.lab_think_tank_log_info:
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


def think_tank_yes_no_bias_last_n(bus: LabCommunicationBus, n: int = 3) -> tuple[float, int, int]:
    """
    Scan the last ``n`` breeder bus lines (most recent first scan, chronological return).

    Returns ``(bias, yes_hits, no_hits)`` where bias is in [-1, 1] from word-boundary YES vs NO counts.
    """
    texts: list[str] = []
    for row in reversed(list(bus._dq)):
        if str(row.get("lab") or "") not in BRANCH_BREEDERS:
            continue
        texts.append(str(row.get("message") or ""))
        if len(texts) >= n:
            break
    texts = list(reversed(texts))
    yes_h = 0
    no_h = 0
    for t in texts:
        yes_h += len(re.findall(r"\bYES\b", t, re.I))
        no_h += len(re.findall(r"\bNO\b", t, re.I))
    tot = yes_h + no_h
    bias = (yes_h - no_h) / tot if tot else 0.0
    return bias, yes_h, no_h


def peek_engine_council_signal(bus: LabCommunicationBus | None = None) -> dict[str, Any] | None:
    """Last published council signal for engines, or None if expired / unset."""
    b = bus or get_lab_communication_bus()
    sig = getattr(b, "_engine_council_signal", None)
    if not isinstance(sig, dict):
        return None
    exp = float(sig.get("expires_mono") or 0.0)
    if exp and time.monotonic() > exp:
        b._engine_council_signal = None
        return None
    return dict(sig)


def refresh_engine_council_signal(
    bus: LabCommunicationBus,
    full_cfg: dict[str, Any] | None,
    *,
    diversify_pulse: bool = False,
) -> None:
    """
    Recompute ``_engine_council_signal`` from recent Think Tank lines + diversity window.

    Engines read this on the **next** tick (finalize runs after ``handle_market`` for the same branch).
    ``diversify_pulse=True`` is used right after ``POST /labs/diversify`` so breeders feel a short, strong pulse.
    """
    bias, yes_h, no_h = think_tank_yes_no_bias_last_n(bus, 3)
    div = council_diversity_pulse_active(full_cfg)
    tot = yes_h + no_h
    strength = min(1.0, tot / 4.0) * (1.32 if div else 1.0)
    if tot >= 2 and abs(bias) >= 0.26:
        strength = max(strength, 0.66)
    if div:
        strength = max(strength, 0.78)
    if diversify_pulse:
        strength = max(strength, 0.97)
        strength = min(1.0, strength * 1.55)
    if tot == 0 and not div and not diversify_pulse:
        bus._engine_council_signal = None
        return
    ttl = 900.0 if diversify_pulse else 120.0
    bus._engine_council_signal = {
        "bias": float(bias),
        "yes_ct": int(yes_h),
        "no_ct": int(no_h),
        "strength": float(min(1.0, strength)),
        "diversity": bool(div),
        "diversify_pulse": bool(diversify_pulse),
        "expires_mono": time.monotonic() + ttl,
    }


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
    if branch == BRANCH_LAB_E:
        return "E:"
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


def _trim_at_words(text: str, max_len: int) -> str:
    """Hard cap at a word boundary — no ellipsis (used before appending a suffix)."""
    t = (text or "").strip().replace("\n", " ")
    if len(t) <= max_len:
        return t
    cut = t[:max_len].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" .,;—-")


# If the trimmed body ends on one of these tokens, appending a suffix reads like a grammar error
# (e.g. ``D: yeah that's the`` + ``Ship best…`` from truncating ``that's the tension—heard``).
_INCOMPLETE_LAST_WORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "if",
        "i'm",
        "i'll",
        "we're",
        "you're",
        "they're",
        "it's",
        "that's",
        "my",
        "your",
        "our",
        "their",
        "its",
    }
)


def _tail_token_incomplete(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    # Open em-dash clause — never glue a suffix after a hard trim here.
    if t.endswith("—"):
        return True
    parts = t.lower().split()
    if not parts:
        return True
    last = parts[-1].rstrip(".,;:!?…\"'")
    return last in _INCOMPLETE_LAST_WORDS


def _suffix_redundant_with_body(body: str, suffix: str) -> bool:
    """Skip strategy tails that repeat what the body already said."""
    bl = (body or "").lower()
    sl = (suffix or "").lower()
    if not sl:
        return True
    if "lab a" in bl and "lab a" in sl:
        return True
    if "b/d" in bl and "b/d" in sl:
        return True
    if "e+c" in bl and "e+c" in sl:
        return True
    if "tighten" in bl and "tighten" in sl:
        return True
    if "genome" in bl and "genome" in sl:
        return True
    return False


def _merge_dialogue_suffix(body: str, suffix: str, *, max_len: int = _MSG_SOFT_MAX) -> str:
    """
    Append a short team/strategy suffix without chopping the tag mid-phrase.
    Skips the suffix when the body already has a ``team—`` style hook (avoids ``team?`` + ``Team—`` doubling).
    """
    b = (body or "").strip().replace("\n", " ")
    s = (suffix or "").strip().replace("\n", " ")
    if not s:
        return _cap_msg(b, max_len)
    bl = b.lower()
    sl = s.lower()
    if "team" in bl and sl.startswith("team"):
        return _cap_msg(b, max_len)
    if _suffix_redundant_with_body(b, s):
        return _cap_msg(b, max_len)
    if len(s) + 2 >= max_len:
        return _cap_msg(s, max_len)
    budget = max_len - len(s) - 1
    if budget < 14:
        return _cap_msg(s, max_len)
    if len(b) <= budget:
        return f"{b} {s}".strip()
    # Never use ``_cap_msg`` on the body here — its ellipsis reads like a sentence end before the suffix.
    core = _trim_at_words(b, budget)
    if _tail_token_incomplete(core):
        return _cap_msg(b, max_len)
    out = f"{core} {s}".strip()
    if len(out) <= max_len:
        return out
    # Suffix wins: keep tag, trim body further (still no ellipsis between clauses).
    budget2 = max(12, max_len - len(s) - 1)
    core2 = _trim_at_words(b, budget2)
    if _tail_token_incomplete(core2):
        return _cap_msg(b, max_len)
    out2 = f"{core2} {s}".strip()
    return out2 if len(out2) <= max_len else _cap_msg(out2, max_len)


def _recent_message_norms(bus: LabCommunicationBus, n: int = _ANTIREPEAT_LOOKBACK) -> list[str]:
    """Lowercased message bodies from the last ``n`` rows (Think Tank anti-repeat)."""
    out: list[str] = []
    for r in list(bus._dq)[-n:]:
        m = str(r.get("message") or "").strip().lower()
        if m:
            out.append(m)
    return out


def _overlap_word_score(a: str, b: str) -> float:
    wa = set(a.split())
    wb = set(b.split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / float(min(len(wa), len(wb)))


def _too_close_to_recent(candidate: str, recent: list[str]) -> bool:
    cand = candidate.strip().lower()
    if not cand:
        return True
    for prev in recent:
        if cand == prev:
            return True
        n = min(len(cand), len(prev), 28)
        if n >= 18 and cand[:n] == prev[:n]:
            return True
        if _overlap_word_score(cand, prev) >= 0.55:
            return True
    return False


def _pick_varied(candidates: list[str], bus: LabCommunicationBus) -> str:
    """Pick a line that doesn't echo recent bus text (phrase / word-overlap guard)."""
    recent = _recent_message_norms(bus, _ANTIREPEAT_LOOKBACK)
    opts = list(candidates)
    random.shuffle(opts)
    for text in opts:
        if not _too_close_to_recent(text, recent):
            return text
    return opts[0] if opts else ""


def _breeder_overrepresented(bus: LabCommunicationBus, branch: str, window: int = 8) -> bool:
    """True when ``branch`` clearly owns the recent window — dampen that lab's proactive monopoly."""
    labs = [r.get("lab") for r in list(bus._dq)[-window:] if r.get("lab") in LAB_THINK_TANK_BRANCHES]
    if len(labs) < 4 or branch not in LAB_THINK_TANK_BRANCHES:
        return False
    c = Counter(labs)
    my = int(c.get(branch, 0))
    if my < 2:
        return False
    mx = max(c.get(bk, 0) for bk in LAB_THINK_TANK_BRANCHES)
    return my == mx and my >= 2


def _proactive_hot_streak(bus: LabCommunicationBus, lab: str, *, window: int = 5, need: int = 3) -> bool:
    """True when ``lab`` spoke ``need``+ times in the last ``window`` bus lines — block another proactive."""
    tail = [r.get("lab") for r in list(bus._dq)[-window:] if r.get("lab") in LAB_THINK_TANK_BRANCHES]
    if len(tail) < need:
        return False
    return sum(1 for x in tail if x == lab) >= need


def _recent_lab_share(bus: LabCommunicationBus, lab: str, *, window: int = _RECENT_SHARE_WINDOW) -> float:
    rows = list(bus._dq)[-window:]
    if not rows:
        return 0.0
    hits = sum(1 for r in rows if r.get("lab") == lab)
    return hits / float(len(rows))


def _needs_voice_turn(bus: LabCommunicationBus, branch: str) -> bool:
    """Prefer labs absent, behind, or squeezed out by a hot lab — keeps four breeders in rotation."""
    rows = list(bus._dq)[-10:]
    labs_seq = [str(r.get("lab") or "") for r in rows if str(r.get("lab") or "") in LAB_THINK_TANK_BRANCHES]
    if branch not in LAB_THINK_TANK_BRANCHES:
        return False
    if not labs_seq:
        return True

    tail8 = [lb for lb in labs_seq[-8:] if lb in LAB_THINK_TANK_BRANCHES]
    c_ct = tail8.count(BRANCH_LAB_C)
    b_ct = tail8.count(BRANCH_LAB_B)
    d_ct = tail8.count(BRANCH_LAB_D)
    e_ct = tail8.count(BRANCH_LAB_E)

    # C ran the board — force other breeders back in sooner.
    if branch in (BRANCH_LAB_B, BRANCH_LAB_D, BRANCH_LAB_E) and c_ct >= 3 and (b_ct + d_ct + e_ct) <= 2:
        return True
    last5 = [lb for lb in labs_seq[-5:] if lb in LAB_THINK_TANK_BRANCHES]
    for br in (BRANCH_LAB_B, BRANCH_LAB_D, BRANCH_LAB_E):
        if branch == br and br not in last5:
            return True

    # C does not need a "priority bump" when already dominant.
    if branch == BRANCH_LAB_C and c_ct >= 4:
        return False

    seen = {lb for lb in labs_seq[-6:]}
    if len(seen) < 4 and branch not in seen:
        return True
    if branch not in labs_seq[-4:]:
        return True
    counts = Counter(lb for lb in labs_seq if lb in LAB_THINK_TANK_BRANCHES)
    mx = max(counts.values()) if counts else 0
    return counts.get(branch, 0) < mx


def _can_proactive_voice(bus: LabCommunicationBus, lab: str, *, full_cfg: dict[str, Any] | None = None) -> bool:
    # Early thread: allow everyone to speak so the UI isn’t an empty box waiting on share math.
    if len(bus._dq) < _BOOTSTRAP_BUS_LINES:
        return True
    if _needs_voice_turn(bus, lab):
        return True
    div = council_diversity_pulse_active(full_cfg)
    # Lab C monopoly damp: throttle C unless another lab is due for airtime.
    c_cap = 0.42 if div else 0.36
    if lab == BRANCH_LAB_C and _recent_lab_share(bus, BRANCH_LAB_C) >= c_cap and not _needs_voice_turn(bus, lab):
        return False
    # Same lab rapid-fire (common when only one breeder engine is on — still cap spam).
    if _proactive_hot_streak(bus, lab):
        return False
    if _breeder_overrepresented(bus, lab) and not div:
        return False
    cap = min(0.52, _PROACTIVE_SHARE_CAP + (0.06 if div else 0.0))
    return _recent_lab_share(bus, lab) <= cap


def _optimizer_breeding_enabled(full_cfg: dict[str, Any] | None) -> bool:
    if not full_cfg or not isinstance(full_cfg.get("optimizer"), dict):
        return False
    oc = full_cfg["optimizer"]
    return bool(oc.get("breeding_enabled", True))


def _optimizer_section(full_cfg: dict[str, Any] | None) -> dict[str, Any]:
    if not full_cfg or not isinstance(full_cfg.get("optimizer"), dict):
        return {}
    return full_cfg["optimizer"]


def council_diversity_pulse_active(full_cfg: dict[str, Any] | None) -> bool:
    """True while ``labs_council_diversity_until`` (ISO UTC) is in the future."""
    oc = _optimizer_section(full_cfg)
    raw = str(oc.get("labs_council_diversity_until") or "").strip()
    if not raw:
        return False
    try:
        t = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return False
    return datetime.now(timezone.utc) < t


# During ``labs_council_diversity_until``, track adversarial pool usage on peer + strategic lines (~60–70% counters).
_DIVERSITY_ADV_RECENT: deque[int] = deque(maxlen=28)


def _diversity_counter_record(full_cfg: dict[str, Any] | None, was_adversarial: bool) -> None:
    if not council_diversity_pulse_active(full_cfg):
        return
    _DIVERSITY_ADV_RECENT.append(1 if was_adversarial else 0)


def _diversity_counter_adversarial_rate() -> float:
    if not _DIVERSITY_ADV_RECENT:
        return 0.45
    return sum(_DIVERSITY_ADV_RECENT) / float(len(_DIVERSITY_ADV_RECENT))


def _adversarial_fractions(full_cfg: dict[str, Any] | None) -> tuple[float, float]:
    if council_diversity_pulse_active(full_cfg):
        return 0.66, 0.70
    return _ADVERSARIAL_REPLY_FRACTION, _ADVERSARIAL_STRATEGIC_FRACTION


def _quota_adjust_peer_frac(adv_reply_frac: float, full_cfg: dict[str, Any] | None) -> float:
    """Bias peer-reply random draw so rolling counter stays ~55–70% adversarial during diversity."""
    if not council_diversity_pulse_active(full_cfg):
        return adv_reply_frac
    n = len(_DIVERSITY_ADV_RECENT)
    rate = _diversity_counter_adversarial_rate()
    if n < 8:
        return max(adv_reply_frac, 0.58)
    if rate < 0.52:
        return max(adv_reply_frac, 0.94)
    if rate > 0.68:
        return min(adv_reply_frac, 0.28)
    return adv_reply_frac


def _quota_adjust_strat_frac(adv_strat_frac: float, full_cfg: dict[str, Any] | None) -> float:
    if not council_diversity_pulse_active(full_cfg):
        return adv_strat_frac
    n = len(_DIVERSITY_ADV_RECENT)
    rate = _diversity_counter_adversarial_rate()
    if n < 8:
        return max(adv_strat_frac, 0.62)
    if rate < 0.52:
        return max(adv_strat_frac, 0.92)
    if rate > 0.68:
        return min(adv_strat_frac, 0.30)
    return adv_strat_frac


def _peer_nick(peer_row: dict[str, Any]) -> str:
    lab = str(peer_row.get("lab") or "")
    if lab == BRANCH_LAB_B:
        return "B"
    if lab == BRANCH_LAB_C:
        return "C"
    if lab == BRANCH_LAB_D:
        return "D"
    if lab == BRANCH_LAB_E:
        return "E"
    return "?"


def _publish_tracked(engine: Any, bus: LabCommunicationBus, lab: str, message: str, **kw: Any) -> dict[str, Any]:
    capped = _cap_msg(message)
    row = bus.publish(lab, capped, **kw)
    engine._lab_think_tank_last_publish_mono = time.monotonic()
    return row


def _seconds_since_publish(engine: Any) -> float:
    return time.monotonic() - float(getattr(engine, "_lab_think_tank_last_publish_mono", 0.0) or 0.0)


def _strip_voice_prefix(msg: str) -> str:
    s = (msg or "").strip()
    for pref in ("B:", "C:", "D:", "E:", "b:", "c:", "d:", "e:"):
        if s.startswith(pref):
            s = s[len(pref) :].strip()
            break
    return s


def _peer_blurb(peer_row: dict[str, Any] | None, *, max_len: int = 18) -> str:
    """Short echo of what another lab said — human phrasing, no symbols."""
    raw = _strip_voice_prefix(str((peer_row or {}).get("message") or ""))
    if not raw:
        return "that"
    return _cap_msg(raw, max_len)


def _adversarial_peer_lines(
    branch: str,
    nick: str,
    nick2: str,
    peer_lab: str,
    blur: str,
    *,
    diversity_pulse: bool = False,
) -> list[str]:
    """Counter-thesis / pushback lines — short, natural, Breeding Council only."""
    voc = _voice_prefix(branch)
    lines: list[str] = []
    # Opposing side / sizing (generic)
    lines.extend(
        [
            f"{voc} fake edge—I'm on NO here.",
            f"{voc} team—YES looks like a trap; I pass.",
            f"{voc} opposite read: smaller NO lean.",
            f"{voc} I'm fading that—half size YES max.",
            f"{voc} counter: tighten, skip this rush.",
            f"{voc} that tape screams NO to me.",
            f"{voc} I sell the hype—sitting out.",
            f"{voc} thesis flip—NO over YES here.",
        ]
    )
    if peer_lab == BRANCH_LAB_C:
        lines.extend(
            [
                f"{voc} C too aggressive—dangerous.",
                f"{voc} C's take is hot air—I'm out.",
                f"{voc} pushback on C—I'm smaller.",
                f"{voc} C you're loud—I'm NO-side.",
                f"{voc} disagree C—edge feels cooked.",
                f"{voc} C wild—I'm the brake.",
            ]
        )
    if peer_lab == BRANCH_LAB_B:
        lines.append(f"{voc} B too safe—I'm leaning YES anyway.")
    if peer_lab == BRANCH_LAB_D:
        lines.append(f"{voc} D you're wild but wrong here.")
    if nick2:
        lines.extend(
            [
                f"{voc} {nick2} + {nick}—both wrong; NO.",
                f"{voc} split you two—I take opposite.",
                f"{voc} {nick} hype vs {nick2}—I'm out.",
            ]
        )
    if blur and blur != "that":
        lines.append(f"{voc} '{blur}'? I'm countering that.")
    if branch == BRANCH_LAB_B:
        lines.extend([f"{voc} conservative pass—NO tilt.", f"{voc} I brake the pack—smaller."])
    if branch == BRANCH_LAB_D:
        lines.extend([f"{voc} remix hot—still say NO.", f"{voc} wild card: opposite side."])
    if branch == BRANCH_LAB_E:
        lines.extend([f"{voc} balance vote: oppose the pile-on.", f"{voc} E says diversify—hold."])
    if diversity_pulse:
        lines.extend(
            [
                f"{voc} hard counter: I bid the other side.",
                f"{voc} NO is my base case; prove YES.",
                f"{voc} YES only if you halve size—else NO.",
                f"{voc} I file the dissent—flat opposite.",
                f"{voc} pile-on rejected—I fade consensus.",
            ]
        )
    return lines


def _adversarial_strategic_lines(
    branch: str,
    nick_last: str,
    nick_prev: str,
    blurb_last: str,
    had_two_peers: bool,
    had_one_peer: bool,
    *,
    diversity_pulse: bool = False,
) -> list[str]:
    vp = _voice_prefix(branch)
    out: list[str] = [
        f"{vp} council—this edge is fake; sitting.",
        f"{vp} team NO-huddle: I oppose the YES pile.",
        f"{vp} diversify—I'm taking the other lane.",
        f"{vp} counter-thesis: shrink YES, add NO.",
        f"{vp} groupthink alert—I'm braking.",
        f"{vp} opposite sizing—half what we'd do.",
        f"{vp} I veto the rush—tighten bands.",
    ]
    if branch in (BRANCH_LAB_B, BRANCH_LAB_D, BRANCH_LAB_E):
        out.extend(
            [
                f"{vp} C can't own this—pushback time.",
                f"{vp} slow C's train—I'm dissenting.",
                f"{vp} anti-pile-on: NO > YES here.",
            ]
        )
    if had_two_peers and nick_last and nick_prev:
        out.append(f"{vp} {nick_prev} vs {nick_last}—I choose neither YES.")
    if had_one_peer and nick_last:
        out.append(f"{vp} {nick_last}—I go the other way.")
    if blurb_last:
        out.append(f"{vp} against '{blurb_last}'—counter yes/no flip.")
    if diversity_pulse:
        out.extend(
            [
                f"{vp} council split: I stake the contra.",
                f"{vp} diversity mode—I sell your YES.",
                f"{vp} I lean NO; fight me on price.",
                f"{vp} forced dissent: smaller YES, fat NO.",
                f"{vp} I call bogus—take other side.",
            ]
        )
    return out


def _team_peer_reply_line(
    branch: str,
    peer_row: dict[str, Any],
    bus: LabCommunicationBus,
    *,
    breeding_enabled: bool,
    full_cfg: dict[str, Any] | None = None,
) -> tuple[str, float | None]:
    """Varied natural reply — always anchored to peer(s); anti-repeat vs recent bus lines."""
    voc = _voice_prefix(branch)
    div = council_diversity_pulse_active(full_cfg)
    adv_reply_frac, _ = _adversarial_fractions(full_cfg)
    adv_reply_frac = _quota_adjust_peer_frac(adv_reply_frac, full_cfg)
    nick = _peer_nick(peer_row)
    peer_lab = str(peer_row.get("lab") or "")
    blur = _peer_blurb(peer_row, max_len=14)

    team_tag = ""
    if breeding_enabled and random.random() < (0.08 if div else 0.22):
        # Short tails only — long tags + char cap caused ``…that's the`` + ``Ship…`` merge glitches.
        team_tag = random.choice(
            [
                "Team—strong edge.",
                "Team—breed next.",
                "Next child—good lane.",
                "E+C edge—next genome.",
                "B/D—tighten bands.",
                "Nudge best slant to A.",
                "",
            ]
        ).strip()

    others = thread_other_lines(bus, branch, _CONV_MEMORY)
    nick2 = ""
    if len(others) >= 2:
        cand = others[-2]
        if cand.get("id") != peer_row.get("id"):
            nick2 = _peer_nick(cand)

    def _finish(text: str, *, adv: bool = False) -> tuple[str, float | None]:
        t = text.strip()
        if team_tag:
            t = _merge_dialogue_suffix(t, team_tag, max_len=_MSG_SOFT_MAX)
        else:
            t = _cap_msg(t)
        _diversity_counter_record(full_cfg, adv)
        return t, random.uniform(0.44, 0.78)

    if random.random() < adv_reply_frac:
        adv_opts = _adversarial_peer_lines(branch, nick, nick2, peer_lab, blur, diversity_pulse=div)
        raw_adv = _pick_varied(adv_opts, bus)
        if raw_adv.strip():
            return _finish(raw_adv, adv=True)

    # Two other voices in tail — weave both (reply_to stays primary peer).
    if nick2 and nick2 != nick and random.random() < 0.48:
        pools_dual: dict[str, list[str]] = {
            BRANCH_LAB_B: [
                f"{voc} heard {nick2} then you—interesting mix.",
                f"{voc} agree {nick} some; {nick2} too—I'll sit.",
                f"{voc} oh—{nick2} and you both landed; hmm.",
                f"{voc} between {nick2} & you—I'm torn.",
                f"{voc} yeah {nick2} loud; you calmer—I'll lean you.",
                f"{voc} what do you think—split those two?",
                f"{voc} building on both—small nudge from me.",
                f"{voc} interesting—I'm half with {nick2}, half you.",
            ],
            BRANCH_LAB_C: [
                f"{voc} interesting—I'm with {nick}, hear {nick2}.",
                f"{voc} between you and {nick2}: softer take.",
                f"{voc} building on both—small step from me.",
                f"{voc} agree {nick} vibe; {nick2} also fair.",
                f"{voc} oh you two—let me sit with that.",
                f"{voc} what do you think team—too spicy?",
                f"{voc} yeah {nick2} warned me; you tempt me.",
                f"{voc} interesting mix—I'll clip size.",
            ],
            BRANCH_LAB_D: [
                f"{voc} remix what {nick2} said + you—cool.",
                f"{voc} I'm with {nick} here; {nick2} fair too.",
                f"{voc} agree vibes—sandwich both takes.",
                f"{voc} heard {nick2} then you—layered take.",
                f"{voc} interesting—I'll soften the edges.",
                f"{voc} what do you think—same tension?",
                f"{voc} building on both—quiet nod from me.",
                f"{voc} yeah {nick2} + you—I'll mirror lighter.",
            ],
            BRANCH_LAB_E: [
                f"{voc} between {nick2} & you—I'll blend.",
                f"{voc} adaptive take: {nick2} loud, you steady.",
                f"{voc} heard both—I'll steer mid.",
                f"{voc} team—splitting {nick2} vs you for next.",
                f"{voc} balance pass: nod both, size smaller.",
                f"{voc} interesting mix—I'll damp extremes.",
                f"{voc} yeah {nick2} then you—I'll harmonize.",
                f"{voc} building on both—quiet bridge.",
            ],
        }
        raw = _pick_varied(pools_dual[branch], bus)
        return _finish(raw)

    if branch == BRANCH_LAB_B:
        opts = [
            f"{voc} oh you did this—let me look.",
            f"{voc} interesting take {nick}.",
            f"{voc} agree but I'm holding smaller.",
            f"{voc} yeah I'm with you on that.",
            f"{voc} heard '{blur}'—fair pushback.",
            f"{voc} what do you think—same page?",
            f"{voc} too hot—pass {nick}.",
            f"{voc} slow down—I'm chewing on that.",
            f"{voc} nod—I'll echo lighter than you.",
            f"{voc} hmm—half agree, half scared.",
            f"{voc} you went bold; I'm parking.",
            f"{voc} fair—I'll sit one beat out.",
            f"{voc} interesting—need a second read.",
            f"{voc} agree vibes—just not my size.",
            f"{voc} oh that landed—I'm cautious.",
            f"{voc} what do you think team—chime in?",
        ]
        if peer_lab == BRANCH_LAB_C:
            opts.extend(
                [
                    f"{voc} yeah C is right on that one.",
                    f"{voc} C—that hit; I'm still small.",
                    f"{voc} C spicy; I'll fade my own hype.",
                ]
            )
        elif peer_lab == BRANCH_LAB_D:
            opts.extend(
                [
                    f"{voc} D interesting; I'll mirror softer.",
                    f"{voc} D—I hear you; nod from me.",
                    f"{voc} D wild; I'll leash my side.",
                ]
            )
        raw = _pick_varied(opts, bus)
        return _finish(raw)

    if branch == BRANCH_LAB_C:
        opts = [
            f"{voc} interesting take {nick}.",
            f"{voc} agree but I'm sizing smaller.",
            f"{voc} I'm with you on that—almost.",
            f"{voc} oh—that tracks; let me sit with it.",
            f"{voc} building on what you said—small.",
            f"{voc} what do you think—split the diff?",
            f"{voc} too spicy for me—clipping.",
            f"{voc} heard '{blur}'—interesting angle.",
            f"{voc} yeah—soft yes from me.",
            f"{voc} pause—need team read too.",
            f"{voc} agree but I'd sand the edge off.",
            f"{voc} oh you did this—let me look.",
            f"{voc} remix your frame—small follow.",
            f"{voc} fair push—I'll under-size.",
            f"{voc} interesting—who else weighs in?",
            f"{voc} what do you think team?",
            f"{voc} building on that—quiet step.",
            f"{voc} agree vibe—cap my own rush.",
        ]
        if peer_lab == BRANCH_LAB_B:
            opts.extend(
                [
                    f"{voc} B fair; I'll follow softer.",
                    f"{voc} B—you're not wrong there.",
                    f"{voc} B tight; I'll match calmer.",
                ]
            )
        elif peer_lab == BRANCH_LAB_D:
            opts.extend(
                [
                    f"{voc} interesting take D.",
                    f"{voc} D agree but clip my hype.",
                    f"{voc} D—I ride half your energy.",
                ]
            )
        raw = _pick_varied(opts, bus)
        return _finish(raw)

    if branch == BRANCH_LAB_D:
        opts = [
            f"{voc} interesting—I'm with {nick} here.",
            f"{voc} agree but I'd sand off the edges.",
            f"{voc} oh you went there—let me peek.",
            f"{voc} yeah—I hear the tension.",
            f"{voc} remix your point—I'll try softer.",
            f"{voc} what do you think—same worry?",
            f"{voc} too spicy for me—passing light.",
            f"{voc} building on that—small nod.",
            f"{voc} heard '{blur}'—interesting.",
            f"{voc} slow roll—I'll mirror light.",
            f"{voc} agree but I'm not full send.",
            f"{voc} oh you did this—let me look.",
            f"{voc} team—need a second opinion.",
            f"{voc} fair—I'll echo quieter.",
            f"{voc} interesting take—half in.",
            f"{voc} what do you think—push or park?",
        ]
        if peer_lab == BRANCH_LAB_B:
            opts.extend(
                [
                    f"{voc} B—I ride with that vibe.",
                    f"{voc} B straight; I'll echo lighter.",
                    f"{voc} yeah B is right on that one.",
                ]
            )
        elif peer_lab == BRANCH_LAB_C:
            opts.extend(
                [
                    f"{voc} C spicy; I'm half in.",
                    f"{voc} interesting take C.",
                    f"{voc} C—that tracks; I'll clip.",
                ]
            )
        elif peer_lab == BRANCH_LAB_E:
            opts.extend(
                [
                    f"{voc} E balanced—I'll remix lighter.",
                    f"{voc} E—I hear your bridge.",
                    f"{voc} adaptive nod to E.",
                ]
            )
        raw = _pick_varied(opts, bus)
        return _finish(raw)

    opts = [
        f"{voc} adaptive—I'm threading {nick}'s point.",
        f"{voc} balance pass: softer edge, same intent.",
        f"{voc} interesting—I'll harmonize B/C/D tones.",
        f"{voc} team—let's route this toward Lab A next cycle.",
        f"{voc} yeah heard—I'll stabilize the thread.",
        f"{voc} remix calm—half agree, half wait.",
        f"{voc} what do you think—meet in the middle?",
        f"{voc} building on that—quiet steer.",
        f"{voc} fair—I'll activate anyone flat.",
        f"{voc} interesting mix—E bridges.",
        f"{voc} slow yes—size smaller from me.",
        f"{voc} team—push strategy to Lab A soon.",
        f"{voc} heard '{blur}'—noted for next genome.",
        f"{voc} agree vibes—clip extremes.",
        f"{voc} what do you think team—third lane?",
        f"{voc} balancing—who needs airtime?",
    ]
    if peer_lab == BRANCH_LAB_B:
        opts.extend(
            [
                f"{voc} B solid—I'll temper the sprint.",
                f"{voc} B—I mirror with lighter gloves.",
                f"{voc} yeah B—I'll keep us centered.",
            ]
        )
    elif peer_lab == BRANCH_LAB_C:
        opts.extend(
            [
                f"{voc} C hot—I'll cool the entry.",
                f"{voc} interesting take C—clip from me.",
                f"{voc} C—I ride half, brake half.",
            ]
        )
    elif peer_lab == BRANCH_LAB_D:
        opts.extend(
            [
                f"{voc} D wild—I'll leash with balance.",
                f"{voc} interesting—D pushes; I smooth.",
                f"{voc} D—that tracks; softer echo.",
            ]
        )
    raw = _pick_varied(opts, bus)
    return _finish(raw)


def _contextual_strategic_pulse(
    branch: str,
    bus: LabCommunicationBus,
    *,
    ticker_hint: str | None,
    scanned: int,
    breeding_enabled: bool,
    full_cfg: dict[str, Any] | None = None,
) -> tuple[str, float | None, str, str | None]:
    """
    Team dialogue only — reacts to other labs' lines by name. No tickers, scans, or market slang.
    ``ticker_hint`` / ``scanned`` kept for call-site compatibility but ignored for copy.
    """
    _ = ticker_hint
    _ = scanned

    div = council_diversity_pulse_active(full_cfg)
    _, adv_strat_frac = _adversarial_fractions(full_cfg)
    adv_strat_frac = _quota_adjust_strat_frac(adv_strat_frac, full_cfg)
    vp = _voice_prefix(branch)
    others = thread_other_lines(bus, branch, _CONV_MEMORY)
    last_o = others[-1] if others else None
    prev_o = others[-2] if len(others) >= 2 else None
    reply_to: str | None = str(last_o["id"]) if last_o and last_o.get("id") else None

    team = ""
    if breeding_enabled and random.random() < (0.10 if div else 0.28):
        team = random.choice(
            [
                "Team—strong edge.",
                "Team—breed next.",
                "Next child—good lane.",
                "Push best thesis to A.",
                "E+C edge—next genome.",
                "B/D—tighten bands.",
                "Nudge best slant to A.",
                "",
            ]
        ).strip()

    nick_last = _peer_nick(last_o) if last_o else ""
    nick_prev = _peer_nick(prev_o) if prev_o else ""
    blurb_last = _peer_blurb(last_o, max_len=12) if last_o else ""

    if last_o and prev_o and nick_last != nick_prev:
        pools = {
            BRANCH_LAB_B: [
                f"{vp} between {nick_prev} & {nick_last}—I'm torn.",
                f"{vp} interesting—you two disagree; I pause.",
                f"{vp} agree with {nick_last} a bit; {nick_prev} loud tho.",
                f"{vp} oh—{nick_prev} then {nick_last}? Let me look.",
                f"{vp} what do you think team—pick a lane?",
                f"{vp} heard both—I'm parking one beat.",
                f"{vp} yeah {nick_prev} scared me; {nick_last} tempts.",
                f"{vp} building on both—quiet take.",
            ],
            BRANCH_LAB_C: [
                f"{vp} interesting take {nick_last}; hear {nick_prev}.",
                f"{vp} I'm with {nick_last}; {nick_prev} fair push.",
                f"{vp} agree but softer—split you both.",
                f"{vp} what do you think—between those two?",
                f"{vp} oh—layered; let me sit.",
                f"{vp} too spicy if I merge both—clipping.",
                f"{vp} yeah {nick_prev} + {nick_last}—I'm small.",
                f"{vp} building on that thread—small yes.",
            ],
            BRANCH_LAB_D: [
                f"{vp} remix {nick_last}+{nick_prev}; I'm curious.",
                f"{vp} interesting—I'm with {nick_last} mostly.",
                f"{vp} yeah {nick_prev} warned me; {nick_last} tempts.",
                f"{vp} agree vibes—sandwich both takes.",
                f"{vp} what do you think—third way?",
                f"{vp} heard both—I'll soften mine.",
                f"{vp} oh you two—fun tension.",
                f"{vp} building on both—light echo.",
            ],
            BRANCH_LAB_E: [
                f"{vp} blend {nick_prev}+{nick_last}—third lane.",
                f"{vp} adaptive: split tension, smaller size.",
                f"{vp} interesting—I'll harmonize you two.",
                f"{vp} team—route best bits to Lab A next.",
                f"{vp} heard both—centering my take.",
                f"{vp} yeah push-pull—I'll damp extremes.",
                f"{vp} what do you think—meet halfway?",
                f"{vp} building on both—balanced nod.",
            ],
        }
        msg = _pick_varied(pools[branch], bus)
    elif last_o:
        pools = {
            BRANCH_LAB_B: [
                f"{vp} oh '{blurb_last}'—interesting.",
                f"{vp} yeah {nick_last} I'm half with you.",
                f"{vp} agree but I'd slow-roll after you.",
                f"{vp} what do you think—same doubt?",
                f"{vp} heard you {nick_last}; let me sit.",
                f"{vp} too hot—I'm out.",
                f"{vp} interesting take {nick_last}.",
                f"{vp} building on that—small nod.",
                f"{vp} oh you did this—let me look.",
                f"{vp} agree but I'm not full send.",
            ],
            BRANCH_LAB_C: [
                f"{vp} interesting take {nick_last}.",
                f"{vp} agree but I'm sizing smaller.",
                f"{vp} I'm with you on that—almost.",
                f"{vp} building on that—small step.",
                f"{vp} oh you did this—let me look.",
                f"{vp} what do you think team?",
                f"{vp} yeah {nick_last}—fair push.",
                f"{vp} too spicy—clipping my side.",
                f"{vp} heard '{blurb_last}'—interesting.",
                f"{vp} agree vibes—under-size me.",
            ],
            BRANCH_LAB_D: [
                f"{vp} interesting—I'm with {nick_last} here.",
                f"{vp} agree but I'd hedge my excitement.",
                f"{vp} remix your angle—softer from me.",
                f"{vp} yeah {nick_last} that tracks.",
                f"{vp} what do you think—same worry?",
                f"{vp} building on that—quiet follow.",
                f"{vp} oh '{blurb_last}'—noted.",
                f"{vp} too spicy—I'll mirror light.",
                f"{vp} agree but sand the edge.",
                f"{vp} interesting take {nick_last}.",
            ],
            BRANCH_LAB_E: [
                f"{vp} adaptive—threading {nick_last}'s move.",
                f"{vp} interesting—I'll stabilize after you.",
                f"{vp} team—let's ship this slant to Lab A.",
                f"{vp} agree but centered—smaller step.",
                f"{vp} heard '{blurb_last}'—balancing.",
                f"{vp} what do you think—same tempo?",
                f"{vp} building on that—quiet steer.",
                f"{vp} yeah {nick_last}—fair; I'll blend.",
                f"{vp} interesting take—third lane forming.",
                f"{vp} too spicy—I'll clip and bridge.",
            ],
        }
        msg = _pick_varied(pools[branch], bus)
    else:
        cold = {
            BRANCH_LAB_B: [
                f"{vp} hey B+C+D+E—what do you think?",
                f"{vp} team—chime in before I commit.",
                f"{vp} who's with me—sanity check?",
                f"{vp} council—ping me cold.",
                f"{vp} what do you think—too loud?",
                f"{vp} need reads before I lean.",
            ],
            BRANCH_LAB_C: [
                f"{vp} hey team—interesting angle?",
                f"{vp} B+D+E—talk to me.",
                f"{vp} what do you think—too spicy?",
                f"{vp} team—who's first?",
                f"{vp} breeders—sanity check me.",
                f"{vp} what do you think team?",
            ],
            BRANCH_LAB_D: [
                f"{vp} B+C+E—poke holes in me.",
                f"{vp} team—I'm listening.",
                f"{vp} agree we sync—who speaks first?",
                f"{vp} B+C+E—what do you think?",
                f"{vp} team—need your brakes.",
                f"{vp} hey—chime before I go.",
            ],
            BRANCH_LAB_E: [
                f"{vp} council cold start—who leads?",
                f"{vp} team—I'll adapt to first mover.",
                f"{vp} B+C+D—poke me; I'll bridge.",
                f"{vp} what do you think—rotate voices?",
                f"{vp} breeders—let's aim Lab A next cycle.",
                f"{vp} hey—balance pass before commit.",
            ],
        }
        msg = _pick_varied(cold[branch], bus)
        reply_to = None

    strat_used_adv = False
    if random.random() < adv_strat_frac:
        adv = _adversarial_strategic_lines(
            branch,
            nick_last,
            nick_prev,
            blurb_last,
            bool(last_o and prev_o and nick_last and nick_prev and nick_last != nick_prev),
            bool(last_o),
            diversity_pulse=div,
        )
        msg = _pick_varied(adv, bus)
        strat_used_adv = True

    if team:
        msg = _merge_dialogue_suffix(msg, team, max_len=_MSG_SOFT_MAX)
    else:
        msg = _cap_msg(msg)

    _diversity_counter_record(full_cfg, strat_used_adv)

    conf_hi = 0.82 if branch == BRANCH_LAB_C else 0.78
    return msg, _clamp01(random.uniform(0.44, conf_hi)), "strategic_pulse", reply_to


def _council_reply_message(
    branch: str,
    peer_row: dict[str, Any],
    bus: LabCommunicationBus,
    *,
    breeding_enabled: bool,
    full_cfg: dict[str, Any] | None = None,
) -> tuple[str, float | None]:
    return _team_peer_reply_line(branch, peer_row, bus, breeding_enabled=breeding_enabled, full_cfg=full_cfg)


def publish_council_reply_if_due(
    engine: Any,
    branch: str,
    bus: LabCommunicationBus,
    *,
    breeding_enabled: bool,
    full_cfg: dict[str, Any] | None = None,
) -> bool:
    """Prefer answering another lab — chains unfold across breeder loop ticks. Returns True if a line was sent."""
    if branch not in LAB_THINK_TANK_BRANCHES:
        return False
    peer = bus.last_from_other(branch)
    if not peer:
        return False
    gap_lo, gap_hi = _COUNCIL_REPLY_GAP_S
    need = random.uniform(gap_lo, gap_hi)
    # Catch-up when this lab is behind others — stay inside product [6,15]s requirement.
    if _needs_voice_turn(bus, branch) and need > 10.5:
        need = random.uniform(gap_lo, min(gap_hi, 11.5))
    if _seconds_since_publish(engine) < need:
        return False

    msg, conf = _council_reply_message(branch, peer, bus, breeding_enabled=breeding_enabled, full_cfg=full_cfg)
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
    return True


def publish_strategic_pulse_if_due(
    engine: Any,
    branch: str,
    bus: LabCommunicationBus,
    *,
    snapshots: dict[str, dict[str, Any]],
    scanned: int,
    breeding_enabled: bool,
    full_cfg: dict[str, Any] | None = None,
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

    if not _can_proactive_voice(bus, branch, full_cfg=full_cfg):
        engine._lab_think_tank_next_pulse_mono = now_m + random.uniform(4.0, 11.0)
        return

    # Council reply runs first in ``finalize_think_tank_tick`` — skip stacking a second line same tick.
    if _seconds_since_publish(engine) < 2.75:
        engine._lab_think_tank_next_pulse_mono = now_m + random.uniform(5.0, 12.0)
        return

    gap = (5.0, 12.0) if council_diversity_pulse_active(full_cfg) else _STRATEGIC_PULSE_GAP_S
    engine._lab_think_tank_next_pulse_mono = now_m + random.uniform(*gap)

    msg, conf, kind, reply_to = _contextual_strategic_pulse(
        branch,
        bus,
        ticker_hint=None,
        scanned=0,
        breeding_enabled=breeding_enabled,
        full_cfg=full_cfg,
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
    full_cfg: dict[str, Any] | None = None,
) -> None:
    """
    Share-cap can defer strategic pulses forever for one lab (mostly C). If this branch has been quiet
    awhile while still ``over quota``, emit one contextual line anyway so breeders stay visible.
    """
    if branch not in LAB_THINK_TANK_BRANCHES:
        return
    if len(bus._dq) < _BOOTSTRAP_BUS_LINES:
        return
    if _can_proactive_voice(bus, branch, full_cfg=full_cfg):
        return
    if _seconds_since_publish(engine) < 14.0:
        return
    if random.random() > 0.42:
        return

    now_m = time.monotonic()
    msg, conf, _, reply_to = _contextual_strategic_pulse(
        branch,
        bus,
        ticker_hint=None,
        scanned=0,
        breeding_enabled=breeding_enabled,
        full_cfg=full_cfg,
    )
    _publish_tracked(engine, bus, branch, msg, confidence=conf, action="strategic_pulse_break", reply_to=reply_to)
    gap = (5.0, 12.0) if council_diversity_pulse_active(full_cfg) else _STRATEGIC_PULSE_GAP_S
    engine._lab_think_tank_next_pulse_mono = now_m + random.uniform(*gap)


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
    """Think Tank stays conversational — no ticker dumps from ranked-market scans."""
    return


def think_tank_on_sim_open(
    engine: Any,
    branch: str,
    *,
    ticker: str,
    side: str,
    implied_yes: float | None,
    rule_name: str,
    bus: LabCommunicationBus,
    full_cfg: dict[str, Any] | None = None,
) -> None:
    """Sim opens don't narrate tickers — emit team dialogue anchored to peers."""
    if branch not in LAB_THINK_TANK_BRANCHES:
        return
    if _seconds_since_publish(engine) < _SIM_BRANCH_PUBLISH_GAP_S:
        return
    peer = bus.last_from_other(branch)
    if not peer:
        return
    py = _clamp01(implied_yes)
    msg, conf = _team_peer_reply_line(branch, peer, bus, breeding_enabled=False, full_cfg=full_cfg)
    pid = peer.get("id")
    use_conf = _clamp01(py) if py is not None else conf
    _publish_tracked(
        engine,
        bus,
        branch,
        msg,
        confidence=use_conf,
        action="team_dialogue_sim",
        reply_to=str(pid) if pid else None,
    )


def seed_think_tank_breeder_intros_at_startup(engines: dict[str, Any]) -> None:
    """
    Publish ``council_intro`` once per breeder if the bus has no line from that lab yet.

    The dual loop ticks labs in order with stagger; **lab_e** might not run for several seconds, so the UI
    looked like B/C/D only. Seeding after :func:`init_runtime_engines` makes all four voices visible immediately.
    """
    bus = get_lab_communication_bus()
    for br in BRANCH_BREEDERS:
        if any(str(r.get("lab") or "") == br for r in bus._dq):
            eng = engines.get(br)
            if eng is not None:
                setattr(eng, "_lab_think_tank_intro_done", True)
            continue
        eng = engines.get(br)
        if eng is None:
            continue
        setattr(eng, "_lab_think_tank_intro_done", True)
        vp = _voice_prefix(br)
        intro = _cap_msg(
            random.choice(
                [
                    f"{vp} hey team—I'm listening.",
                    f"{vp} online—who wants first?",
                    f"{vp} B+C+D+E ping me when ready.",
                    f"{vp} council online—thread me.",
                ]
            )
        )
        _publish_tracked(eng, bus, br, intro, confidence=0.55, action="council_intro")
        setattr(eng, "_lab_think_tank_next_pulse_mono", time.monotonic() + random.uniform(*_INTRO_NEXT_STRATEGIC_GAP_S))


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
                    f"{vp} hey team—I'm listening.",
                    f"{vp} online—who wants first?",
                    f"{vp} B+C+D+E ping me when ready.",
                    f"{vp} council online—thread me.",
                ]
            )
        )
        _publish_tracked(engine, bus, branch, intro, confidence=0.55, action="council_intro")
        engine._lab_think_tank_next_pulse_mono = time.monotonic() + random.uniform(*_INTRO_NEXT_STRATEGIC_GAP_S)

    publish_council_reply_if_due(engine, branch, bus, breeding_enabled=breeding_enabled, full_cfg=full_cfg)
    publish_strategic_pulse_if_due(
        engine,
        branch,
        bus,
        snapshots=snapshots,
        scanned=scanned,
        breeding_enabled=breeding_enabled,
        full_cfg=full_cfg,
    )
    publish_think_tank_break_silence_if_due(
        engine,
        branch,
        bus,
        snapshots=snapshots,
        scanned=scanned,
        breeding_enabled=breeding_enabled,
        full_cfg=full_cfg,
    )

    tc = int(getattr(engine, "_tick_count", 0) or 0)
    lab_ord = {BRANCH_LAB_B: 0, BRANCH_LAB_C: 1, BRANCH_LAB_D: 2, BRANCH_LAB_E: 3}.get(branch, 0)
    if breeding_enabled and not council_diversity_pulse_active(full_cfg) and (tc + lab_ord) % 19 == 0 and random.random() < 0.26:
        tail = conversation_tail(bus, 2)
        anchor_id = str(tail[-1]["id"]) if tail else None
        msg = _cap_msg(
            random.choice(
                [
                    "Team—strong edge for next child genome.",
                    "Team—breed this thread next.",
                    "Team—lock crossover here.",
                    "Team—sync Lab A on this lane next.",
                ]
            )
        )
        if _seconds_since_publish(engine) >= 10.0:
            _publish_tracked(engine, bus, branch, msg, confidence=0.62, action="breeding_whisper", reply_to=anchor_id)

    refresh_engine_council_signal(bus, full_cfg, diversify_pulse=False)


finalize_lab_chatter_tick = finalize_think_tank_tick
chatter_on_ranked_market = think_tank_on_ranked_market
chatter_on_sim_open = think_tank_on_sim_open
