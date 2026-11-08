"""The only object Gemini is allowed to read."""

from __future__ import annotations

import math

import pandas as pd

from gilded.scorecard import naive_bottom


def _num(value, digits=0):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return round(float(value), digits)


def _machine(row: pd.Series) -> dict:
    return {
        "machine_id": row["machine_id"],
        "theme": row["theme"],
        "zone": row["zone_name"],
        "bank": row["bank_id"],
        "cause": row["cause"],
        "runner_up": row["runner_up"],
        "confidence": row["confidence"],
        "days": int(row["n_days"]),
        "house_win_usd": _num(row["house_win"]),
        "theo_usd": _num(row["theo"]),
        "luck_usd": _num(row["luck"]),
        "coin_in_per_hour": _num(row["cph"], 1),
        "peer_coin_in_per_hour": _num(row["peer_cph_elsewhere"], 1),
        "availability": _num(row["availability"], 3),
        "lost_theo_usd": _num(row["lost_theo"]),
        "luck_z": _num(row["luck_z"], 2),
    }


def build(scored: pd.DataFrame, sliced: pd.DataFrame, plan: dict, forecast: dict, start: str, end: str, zone: str | None, bank: str | None) -> dict:
    naive = naive_bottom(scored, 10)
    counts = naive["cause"].value_counts().to_dict()
    cleared = {
        "short_tenure": int(counts.get("short_tenure", 0)),
        "luck": int(counts.get("luck", 0)),
        "location": int(counts.get("location", 0)),
        "game_mix": int(counts.get("game_mix", 0)),
        "payout_inspect": int(counts.get("payout_inspect", 0)),
        "downtime": int(counts.get("downtime", 0)),
        "on_pace": int(counts.get("on_pace", 0)),
    }
    in_slice = set(sliced["machine_id"])
    naive_here = naive[naive["machine_id"].isin(in_slice)]
    open_causes = {"location", "payout_inspect"}
    still_open = sliced[sliced["cause"].isin(open_causes)].head(8)

    spells = []
    spell_frame = plan.get("spells")
    if isinstance(spell_frame, pd.DataFrame) and not spell_frame.empty:
        for machine_id, group in spell_frame.groupby("machine_id"):
            ordered = group.sort_values("first_date")
            spells.append(
                {
                    "machine_id": machine_id,
                    "theme": ordered["theme"].iloc[0],
                    "spells": [
                        {
                            "zone": row["zone_name"],
                            "coin_in_per_hour": _num(row["cph"], 1),
                            "days": int(row["n_days"]),
                        }
                        for _, row in ordered.iterrows()
                    ],
                }
            )

    actions = []
    for item in plan["actions"]:
        actions.append(
            {
                "type": item["action_type_id"],
                "name": item["name"],
                "quantity": item["quantity"],
                "targets": item["targets"],
                "cost_usd": item["cost_usd"],
                "expected_july_theo_usd": item["expected_july_theo_usd"],
                "upside_july_theo_usd": item["upside_july_theo_usd"],
                "measure": item["measure"],
            }
        )

    return {
        "slice": {"start": start, "end": end, "zone": zone, "bank": bank},
        "naive_bottom_10": [_machine(row) for _, row in naive.iterrows()],
        "cleared_by_test": cleared,
        "naive_in_this_slice": [_machine(row) for _, row in naive_here.iterrows()],
        "still_open": [_machine(row) for _, row in still_open.iterrows()],
        "actions": actions,
        "spent_usd": plan["spent_usd"],
        "unspent_usd": plan["unspent_usd"],
        "budget_usd": plan["budget_usd"],
        "moves_already_observed": spells,
        "forecast": {
            "train_end": forecast["train_end"],
            "test_start": forecast["test_start"],
            "baseline_mae_usd": _num(forecast["mae_baseline"]),
            "weekday_mae_usd": _num(forecast["mae_weekday"]),
            "promo_hurdle_coin_in_usd": _num(forecast["promo_hurdle_coin_in"]),
            "saturday_forecast_usd": _num(forecast["saturday_forecast"]),
            "saturday_test_mean_usd": _num(forecast["saturday_test_mean"]),
        },
    }
