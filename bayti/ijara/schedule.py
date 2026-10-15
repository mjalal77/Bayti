"""Rental schedule for a fixed-rental Ijara with an optional residual value."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import List

CENT = Decimal("0.01")


def money(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class RentalRow:
    period: int
    due: date
    rental: Decimal
    profit: Decimal
    capital: Decimal
    outstanding: Decimal


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    year, month = d.year + y, m + 1
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    last = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(d.day, last))


def monthly_rental(financed: Decimal, annual_rate: Decimal, months: int, residual: Decimal) -> Decimal:
    if months <= 0:
        raise ValueError("term_months must be positive")
    if financed <= 0:
        raise ValueError("financed amount must be positive")
    if residual < 0 or residual >= financed:
        raise ValueError("residual value must be >= 0 and below the financed amount")
    r = annual_rate / 12
    if r == 0:
        return money((financed - residual) / months)
    growth = (1 + r) ** months
    return money((financed - residual / growth) * r / (1 - 1 / growth))


def build_schedule(financed: Decimal, annual_rate: Decimal, months: int,
                   residual: Decimal, start: date) -> List[RentalRow]:
    """Rows of rental split into profit and capital; the last row absorbs rounding."""
    rental = monthly_rental(financed, annual_rate, months, residual)
    r = annual_rate / 12
    outstanding = financed
    rows: List[RentalRow] = []
    for i in range(1, months + 1):
        profit = money(outstanding * r)
        if i == months:
            capital = outstanding - residual
            this_rental = capital + profit
        else:
            capital = rental - profit
            this_rental = rental
        outstanding = money(outstanding - capital)
        rows.append(RentalRow(i, add_months(start, i), money(this_rental), profit, money(capital), outstanding))
    return rows
