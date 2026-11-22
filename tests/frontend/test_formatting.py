from app.frontend.formatting import format_brl, format_int, format_percent, format_value


def test_brl_uses_decimal_string_without_float_rounding():
    assert format_brl("30515235.50") == "R$ 30.515.235,50"
    assert format_brl("0.10") == "R$ 0,10"
    assert format_brl("-1234.5") == "-R$ 1.234,50"
    assert format_brl("12345678901234567.89") == "R$ 12.345.678.901.234.567,89"


def test_int_percent_and_missing():
    assert format_int(20000) == "20.000"
    assert format_percent(0.1169) == "11,69%"
    assert format_percent("-0.2426") == "-24,26%"
    assert format_brl(None) == format_int("abc") == format_percent(None) == "—"


def test_format_value_by_metric():
    assert format_value(1585.18177, "average_order_value", "ratio") == "R$ 1.585,18"
    assert format_value(0.1169, "cancellation_rate", "ratio") == "11,69%"
    assert format_value(1424, "active_customers", "count") == "1.424"
    assert format_value("26269632.31", "net_revenue", "money") == "R$ 26.269.632,31"
