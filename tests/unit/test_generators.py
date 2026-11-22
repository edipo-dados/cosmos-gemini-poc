import pandas as pd

from data.generators.config import GenConfig
from data.generators.run import generate

CFG = GenConfig()


def test_same_seed_same_frames_and_manifest():
    a, la, ma = generate(CFG)
    b, lb, mb = generate(CFG)
    assert ma == mb
    for t in a:
        assert a[t].equals(b[t]), t
        assert la[t].equals(lb[t]), t


def test_different_seed_differs():
    a, _, _ = generate(CFG)
    b, _, _ = generate(GenConfig(seed=7))
    assert not a["orders"].equals(b["orders"])


def test_volumes_and_coverage():
    f, _, _ = generate(CFG)
    n = {t: len(df) for t, df in f.items()}
    assert n["customers"] == 5000 and n["products"] == 500 and n["categories"] == 20 and n["regions"] == 5
    assert n["orders"] == 20000 and n["payments"] == 20000 and n["order_items"] >= 35000 and n["refunds"] > 0
    assert set(f["orders"]["status"]) == {"pending", "paid", "cancelled", "refunded"}
    assert set(f["payments"]["method"]) == {"credit_card", "debit_card", "pix", "boleto"}
    assert len(set(f["customers"]["segment"])) >= 3
    months = {d.strftime("%Y-%m") for d in f["orders"]["order_date"]}
    assert len(months) == 24
    assert min(f["orders"]["order_date"]).isoformat() == "2024-11-01"
    assert max(f["orders"]["order_date"]) <= CFG.end_date
    assert all(e.endswith("@example.com") for e in f["customers"]["email"])


def test_oltp_frames_have_no_defects():
    f, _, _ = generate(CFG)
    o, i, p, r = f["orders"], f["order_items"], f["payments"], f["refunds"]
    assert set(o["customer_id"]) <= set(f["customers"]["customer_id"])
    assert set(i["product_id"]) <= set(f["products"]["product_id"])
    assert p["order_id"].is_unique
    cancelled = set(o.loc[o["status"] == "cancelled", "order_id"])
    assert not (set(p.loc[p["status"] == "captured", "order_id"]) & cancelled)
    line = i.set_index("order_item_id")["line_total"]
    assert (r["refund_amount"] <= r["order_item_id"].map(line)).all()
    assert all(x >= 0 for x in i["line_total"]) and all(x >= 0 for x in p["amount"])
    assert (pd.Series(r["refund_amount"]) >= 0).all()


def test_refunded_means_all_items_fully_refunded():
    f, _, _ = generate(CFG)
    i, r, o = f["order_items"], f["refunds"], f["orders"]
    done = r[r["status"] == "completed"].set_index("order_item_id")["refund_amount"]
    i = i.assign(refunded=i["order_item_id"].map(done))
    full = i.assign(ok=i["refunded"] == i["line_total"]).groupby("order_id")["ok"].all()
    refunded_orders = set(o.loc[o["status"] == "refunded", "order_id"])
    assert all(full[x] for x in refunded_orders)
    paid_orders = set(o.loc[o["status"] == "paid", "order_id"])
    assert not any(full[x] for x in paid_orders)
