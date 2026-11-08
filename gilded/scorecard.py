"""Diagnose each cabinet: short tenure, payout, location, game mix, luck, or on pace.

Peers are ratios of sums. A machine is cold when its own coin-in per available
hour is well below the same theme's coin-in per hour in other zones.
"""

from __future__ import annotations

import pandas as pd

from gilded import warehouse

CAUSE_ORDER = [
    "payout_inspect",
    "location",
    "short_tenure",
    "downtime",
    "game_mix",
    "luck",
    "on_pace",
]

CAUSE_LABEL = {
    "payout_inspect": "Inspect payout",
    "location": "Location",
    "short_tenure": "Short tenure",
    "downtime": "Downtime",
    "game_mix": "Game mix",
    "luck": "Luck",
    "on_pace": "On pace",
}


def _rates(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["availability"] = out["avail_h"] / out["sched_h"]
    out["occupancy"] = out["occ_h"] / out["avail_h"]
    out["cph"] = out["coin_in"] / out["avail_h"]
    out["tph"] = out["theo"] / out["avail_h"]
    out["hold"] = out["house_win"] / out["coin_in"]
    out["theo_hold"] = out["theo"] / out["coin_in"]
    out["carded_share"] = out["carded_coin_in"] / out["coin_in"]
    out["down_h"] = out["sched_h"] - out["avail_h"]
    out["lost_theo"] = out["down_h"] * out["tph"]
    return out


def _peers(machines: pd.DataFrame, theme_zone: pd.DataFrame) -> pd.DataFrame:
    """Coin-in per hour for this theme in every zone except the machine's own."""
    totals = (
        theme_zone.groupby("theme", as_index=False)[["coin_in", "avail_h"]]
        .sum()
        .rename(columns={"coin_in": "theme_coin", "avail_h": "theme_hours"})
    )
    zone = theme_zone.rename(
        columns={"coin_in": "zone_coin", "avail_h": "zone_hours", "cph": "zone_cph"}
    )
    out = machines.merge(totals, on="theme", how="left")
    out = out.merge(
        zone[["theme", "zone_name", "zone_coin", "zone_hours", "zone_cph", "machines"]],
        on=["theme", "zone_name"],
        how="left",
    )
    elsewhere_coin = out["theme_coin"] - out["zone_coin"]
    elsewhere_hours = out["theme_hours"] - out["zone_hours"]
    out["peer_cph_elsewhere"] = elsewhere_coin / elsewhere_hours.where(elsewhere_hours > 0)
    out["peer_gap_cph"] = out["peer_cph_elsewhere"] - out["cph"]
    out["peer_cph_ratio"] = out["cph"] / out["peer_cph_elsewhere"]
    return out


def diagnose_row(row: pd.Series, window_days: int) -> tuple[str, str, str]:
    coverage = row["n_days"] / window_days if window_days else 0
    if row["n_days"] < 14 or coverage < 0.50:
        runner = "location" if row["zone_name"] == "Back Forty" else "luck"
        return "short_tenure", runner, "high"

    # Variance-scaled residual. Negative means the cabinet paid more than its theo.
    enough_play = row["coin_in"] >= max(100_000, 2_000 * row["n_days"])
    if pd.notna(row["luck_z"]) and row["luck_z"] <= -3 and enough_play:
        runner = "location" if (row.get("peer_cph_ratio") or 1) < 0.80 else "luck"
        confidence = "medium" if row["volatility_class"] in {"high", "very_high"} else "high"
        return "payout_inspect", runner, confidence

    peer_ratio = row["peer_cph_ratio"]
    if (
        row["n_zones"] == 1
        and pd.notna(peer_ratio)
        and peer_ratio < 0.80
        and row["peer_gap_cph"] > 20
    ):
        runner = "game_mix" if row["theo_hold"] <= 0.055 else "luck"
        confidence = "high" if row["n_days"] >= 60 and peer_ratio < 0.70 else "medium"
        return "location", runner, confidence

    if row["lost_theo"] >= 5_000:
        return "downtime", "on_pace", "medium"

    if row["theo_hold"] <= 0.055:
        return "game_mix", "luck", "medium"

    if pd.notna(row["luck_z"]) and row["luck_z"] < -1.5 and row["house_win"] < row["theo"]:
        return "luck", "on_pace", "high"

    return "on_pace", "luck", "high"


def build(start: str, end: str) -> pd.DataFrame:
    con = warehouse.connect()
    try:
        machines = _rates(warehouse.machine_totals(con, start, end))
        theme_zone = warehouse.theme_zone_rates(con, start, end)
    finally:
        con.close()

    scored = _peers(machines, theme_zone)
    window_days = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1
    causes = scored.apply(lambda row: diagnose_row(row, window_days), axis=1)
    scored["cause"] = causes.map(lambda item: item[0])
    scored["runner_up"] = causes.map(lambda item: item[1])
    scored["confidence"] = causes.map(lambda item: item[2])
    scored["cause_label"] = scored["cause"].map(CAUSE_LABEL)
    scored["window_days"] = window_days
    return scored.sort_values("house_win", ascending=True).reset_index(drop=True)


def naive_bottom(scored: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """The general manager's list: lowest total house win, active days only."""
    return scored.nsmallest(n, "house_win").copy()


def apply_slice(scored: pd.DataFrame, zone: str | None, bank: str | None) -> pd.DataFrame:
    out = scored
    if zone:
        out = out[out["zone_name"] == zone]
    if bank:
        out = out[out["bank_id"] == bank]
    return out.copy()
