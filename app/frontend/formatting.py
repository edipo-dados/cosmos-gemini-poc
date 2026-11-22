"""Formatação pt-BR de valores vindos da API. Dinheiro chega como string decimal e nunca passa por float."""
from __future__ import annotations
from decimal import Decimal, InvalidOperation

PERCENT_METRICS = {"cancellation_rate", "monthly_revenue_growth"}
MONEY_METRICS = {"gross_revenue", "net_revenue", "average_order_value", "refund_amount"}
COUNT_METRICS = {"order_count", "active_customers"}
EMPTY = "—"


def to_decimal(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _group(text: str, decimals: int) -> str:
    """Troca separadores de en-US (`1,234.50`) por pt-BR (`1.234,50`)."""
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def format_brl(value) -> str:
    d = to_decimal(value)
    if d is None:
        return EMPTY
    sign = "-" if d < 0 else ""
    return f"{sign}R$ " + _group(f"{abs(d):,.2f}", 2)


def format_int(value) -> str:
    d = to_decimal(value)
    return EMPTY if d is None else _group(f"{d:,.0f}", 0)


def format_percent(value, decimals: int = 2) -> str:
    d = to_decimal(value)
    return EMPTY if d is None else _group(f"{d * 100:,.{decimals}f}", decimals) + "%"


def kind_of(metric: str | None, value_type: str | None = None) -> str:
    if metric in PERCENT_METRICS:
        return "percent"
    if metric in MONEY_METRICS or value_type == "money":
        return "money"
    if metric in COUNT_METRICS or value_type == "count":
        return "count"
    return "number"


def format_value(value, metric: str | None = None, value_type: str | None = None) -> str:
    kind = kind_of(metric, value_type)
    if kind == "percent":
        return format_percent(value)
    if kind == "money":
        return format_brl(value)
    if kind == "count":
        return format_int(value)
    d = to_decimal(value)
    return EMPTY if d is None else _group(f"{d:,.2f}", 2)
