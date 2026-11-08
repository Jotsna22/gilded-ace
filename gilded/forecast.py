"""Weekday-mean forecast of daily floor coin-in, frozen on January–April.

The flat training mean is the baseline. Both forecasts are scored on May–June
only. Later tourism figures are not inputs.
"""

from __future__ import annotations

import pandas as pd

from gilded import warehouse
from gilded.paths import TEST_START, TRAIN_END

WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def build() -> dict:
    con = warehouse.connect()
    try:
        days = warehouse.property_days(con)
    finally:
        con.close()

    days["gaming_date"] = pd.to_datetime(days["gaming_date"])
    days["split"] = days["gaming_date"].map(
        lambda value: "train" if value <= pd.Timestamp(TRAIN_END) else "test"
    )
    train = days[days["split"] == "train"]
    flat = float(train["coin_in_usd"].mean())
    by_weekday = train.groupby("local_weekday")["coin_in_usd"].mean().to_dict()

    days["baseline_coin_in"] = flat
    days["weekday_coin_in"] = days["local_weekday"].map(by_weekday)
    test = days[days["split"] == "test"].copy()
    test["abs_baseline"] = (test["coin_in_usd"] - test["baseline_coin_in"]).abs()
    test["abs_weekday"] = (test["coin_in_usd"] - test["weekday_coin_in"]).abs()

    theo_hold = float(days["theo_usd"].sum() / days["coin_in_usd"].sum())
    promo_cost = 15_000
    saturday = test[test["local_weekday"] == "Sat"]

    return {
        "daily": days,
        "flat_mean": flat,
        "by_weekday": by_weekday,
        "mae_baseline": float(test["abs_baseline"].mean()),
        "mae_weekday": float(test["abs_weekday"].mean()),
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "train_end": TRAIN_END,
        "test_start": TEST_START,
        "theo_hold": theo_hold,
        "promo_cost_usd": promo_cost,
        "promo_hurdle_coin_in": promo_cost / theo_hold,
        "saturday_test_mean": float(saturday["coin_in_usd"].mean()) if len(saturday) else None,
        "saturday_forecast": float(by_weekday.get("Sat", flat)),
    }
