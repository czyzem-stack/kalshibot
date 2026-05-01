"""
Kalshi quadratic trading fees (General Trading Fees table + optional fee_multiplier).

References:
  https://kalshi.com/docs/kalshi-fee-schedule.pdf
  https://docs.kalshi.com/getting_started/fee_rounding
  OpenAPI ``Series.fee_type`` / ``fee_multiplier`` (quadratic, quadratic_with_maker_fees).
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any

# Base coefficients from the General Trading Fees table (before ``fee_multiplier``).
_TAKER_BASE = Decimal("0.07")
_MAKER_BASE = Decimal("0.0175")  # maker ≈ 25% of taker rate
_CENTICENT = Decimal("0.0001")


def ceil_trade_fee_to_centicent(amount_usd: Decimal) -> Decimal:
    """Kalshi rounds the model trade fee up to the next $0.0001 (centicent)."""
    if amount_usd <= 0:
        return Decimal(0)
    units = (amount_usd / _CENTICENT).to_integral_value(rounding=ROUND_CEILING)
    return units * _CENTICENT


def kalshi_quadratic_trade_fee_usd(
    contracts: float,
    price: float,
    *,
    maker: bool,
    fee_multiplier: float = 1.0,
) -> Decimal:
    """
    Trade fee in USD before balance / rounding fees.

    ``price`` is the executed contract price in dollars on the traded side
    (YES price when buying YES, NO price when buying NO), in (0, 1).
    """
    c = Decimal(str(max(0.0, float(contracts))))
    p = Decimal(str(float(price)))
    if c <= 0 or p <= 0 or p >= 1:
        return Decimal(0)
    m = Decimal(str(max(0.0, min(10.0, float(fee_multiplier)))))
    coeff = (_MAKER_BASE if maker else _TAKER_BASE) * m
    raw = coeff * c * p * (Decimal(1) - p)
    return ceil_trade_fee_to_centicent(raw)


def kalshi_buy_debit_cents(
    contracts: float,
    price: float,
    *,
    maker: bool,
    fee_multiplier: float = 1.0,
) -> tuple[int, dict[str, Any]]:
    """
    Total cash debited from the buyer's wallet for one fill (whole cents),
    including trade fee and cent alignment per Kalshi fee rounding overview.

    Returns ``(debit_cents, breakdown)``.
    """
    c = Decimal(str(max(0.0, float(contracts))))
    p = Decimal(str(float(price)))
    premium = c * p
    fee = kalshi_quadratic_trade_fee_usd(
        float(c), float(p), maker=maker, fee_multiplier=fee_multiplier
    )
    revenue = -premium
    balance_change = revenue - fee
    cents = (balance_change * Decimal(100)).to_integral_value(rounding=ROUND_FLOOR)
    debit = -int(cents)
    breakdown = {
        "kalshi_fee_usd": str(fee),
        "kalshi_premium_usd": str(premium),
        "kalshi_balance_change_usd": str(balance_change),
        "kalshi_maker": maker,
        "kalshi_fee_multiplier": float(fee_multiplier),
    }
    return max(0, debit), breakdown


def kalshi_sell_credit_cents(
    contracts: float,
    price: float,
    *,
    maker: bool,
    fee_multiplier: float = 1.0,
) -> tuple[int, dict[str, Any]]:
    """Cash credited to the seller after trade fee (whole cents)."""
    c = Decimal(str(max(0.0, float(contracts))))
    p = Decimal(str(float(price)))
    proceeds = c * p
    fee = kalshi_quadratic_trade_fee_usd(
        float(c), float(p), maker=maker, fee_multiplier=fee_multiplier
    )
    balance_change = proceeds - fee
    cents = (balance_change * Decimal(100)).to_integral_value(rounding=ROUND_FLOOR)
    credit = int(cents)
    breakdown = {
        "kalshi_fee_usd": str(fee),
        "kalshi_proceeds_usd": str(proceeds),
        "kalshi_balance_change_usd": str(balance_change),
        "kalshi_maker": maker,
        "kalshi_fee_multiplier": float(fee_multiplier),
    }
    return max(0, credit), breakdown


def kalshi_settlement_credit_cents(
    contracts: float, payout_per_contract_usd: float
) -> tuple[int, dict[str, Any]]:
    """
    Posted settlement credit in whole cents (floors sub-cent payout).

    See Kalshi fee rounding doc: settlement may floor credited payout to cents.
    Quadratic trade fee at payout probability 0 or 1 is zero, so no exit trade fee here.
    """
    c = Decimal(str(max(0.0, float(contracts))))
    pay = Decimal(str(max(0.0, float(payout_per_contract_usd))))
    raw_usd = c * pay
    credited = int((raw_usd * Decimal(100)).to_integral_value(rounding=ROUND_FLOOR))
    raw_cents = raw_usd * Decimal(100)
    remainder = raw_cents - Decimal(credited)
    return max(0, credited), {
        "kalshi_settlement_raw_usd": str(raw_usd),
        "kalshi_settlement_rounding_remainder_usd": str(max(Decimal(0), remainder)),
    }
