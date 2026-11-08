"""Turn the scorecard into a July budget. At most three action types.

Planning values use half the observed location gap. The one completed move
out of Back Forty, M-1152, realized the full gap, so the full gap is the upside.
"""

from __future__ import annotations

import pandas as pd

from gilded import warehouse
from gilded.paths import BUDGET_USD, HORIZON_DAYS

HAIRCUT = 0.50
MOVE_ZONE_SKIP = {"Back Forty", "High-Limit Room"}


def _cost(catalog_row: pd.Series, quantity: int) -> float:
    unit = float(catalog_row["unit_cost_cents"]) / 100.0
    recurring = float(catalog_row["recurring_cost_cents_per_day"]) / 100.0
    days = max(0, HORIZON_DAYS - int(catalog_row["lead_days"]))
    return quantity * (unit + recurring * days)


def _hours(catalog_row: pd.Series) -> float:
    days = max(0, HORIZON_DAYS - int(catalog_row["lead_days"]))
    return days * 24 * 0.995 - float(catalog_row["downtime_minutes"]) / 60.0


def _catalog_map(frame: pd.DataFrame) -> dict[str, pd.Series]:
    return {row["action_type_id"]: row for _, row in frame.iterrows()}


def _destinations(con, scored: pd.DataFrame, end: str, theme_zone: pd.DataFrame) -> pd.DataFrame:
    slots = warehouse.empty_slots(con, end)
    if slots.empty:
        return slots
    grouped = scored.groupby("zone_name")[["coin_in", "avail_h"]].sum()
    zone_cph = (grouped["coin_in"] / grouped["avail_h"]).rename("zone_cph")
    slots = slots.merge(zone_cph, left_on="zone_name", right_index=True, how="left")
    slots = slots[~slots["zone_name"].isin(MOVE_ZONE_SKIP)].copy()
    slots = slots.sort_values("zone_cph", ascending=False)
    slots.attrs["theme_zone"] = theme_zone
    return slots


def _theme_cph(theme_zone: pd.DataFrame, theme: str, zone: str) -> float | None:
    hit = theme_zone[(theme_zone["theme"] == theme) & (theme_zone["zone_name"] == zone)]
    if hit.empty or not hit["avail_h"].sum():
        return None
    return float(hit["coin_in"].sum() / hit["avail_h"].sum())


def build(scored: pd.DataFrame, start: str, end: str, theme_zone: pd.DataFrame | None = None) -> dict:
    con = warehouse.connect()
    try:
        catalog = _catalog_map(warehouse.action_catalog(con))
        if theme_zone is None:
            theme_zone = warehouse.theme_zone_rates(con, start, end)
        open_slots = _destinations(con, scored, end, theme_zone)
        spells = warehouse.placement_spells(con)
    finally:
        con.close()

    actions: list[dict] = []
    move_ids: set[str] = set()

    candidates = scored[
        (scored["cause"] == "location")
        & (scored["zone_name"] == "Back Forty")
        & (scored["n_zones"] == 1)
    ].copy()
    # Prefer the cabinets that turn a location gap into the most theoretical win.
    candidates["theo_gap"] = candidates["peer_gap_cph"] * candidates["theo_hold"]
    candidates = candidates.sort_values("theo_gap", ascending=False)

    pairs = []
    if not open_slots.empty and not candidates.empty:
        move_row = catalog["A-MOVE-MACHINE"]
        hours = _hours(move_row)
        used_slots: set[str] = set()
        for _, machine in candidates.iterrows():
            if len(pairs) >= int(move_row["quantity_limit"]):
                break
            for _, slot in open_slots.iterrows():
                if slot["location_id"] in used_slots:
                    continue
                dest_cph = _theme_cph(theme_zone, machine["theme"], slot["zone_name"])
                if dest_cph is None:
                    continue
                gap = dest_cph - float(machine["cph"])
                if gap <= 20:
                    continue
                full = gap * hours * float(machine["theo_hold"])
                pairs.append(
                    {
                        "machine_id": machine["machine_id"],
                        "theme": machine["theme"],
                        "from_zone": machine["zone_name"],
                        "from_location": machine["location_id"],
                        "to_location": slot["location_id"],
                        "to_zone": slot["zone_name"],
                        "gap_cph": round(gap, 1),
                        "expected_theo_usd": round(full * HAIRCUT, 0),
                        "upside_theo_usd": round(full, 0),
                    }
                )
                used_slots.add(slot["location_id"])
                move_ids.add(machine["machine_id"])
                break

    if pairs:
        move_row = catalog["A-MOVE-MACHINE"]
        actions.append(
            {
                "action_type_id": "A-MOVE-MACHINE",
                "name": move_row["name"],
                "quantity": len(pairs),
                "targets": [
                    f"{item['machine_id']} {item['theme']}: {item['from_zone']} → {item['to_zone']} ({item['to_location']})"
                    for item in pairs
                ],
                "target_detail": pairs,
                "cost_usd": round(_cost(move_row, len(pairs)), 2),
                "expected_july_theo_usd": round(sum(item["expected_theo_usd"] for item in pairs), 0),
                "upside_july_theo_usd": round(sum(item["upside_theo_usd"] for item in pairs), 0),
                "uncertainty": (
                    "The planning case keeps half the coin-per-hour gap between Back Forty "
                    "and the destination zone for that theme. M-1152, the one cabinet that "
                    "already left Back Forty, realized the full gap. If a moved cabinet "
                    "earns no extra coin-in, the cost is lost."
                ),
                "measure": (
                    "Theo per available hour of the moved cabinets versus Back Forty "
                    "cabinets of the same theme that stayed, same weekdays, for 30 days."
                ),
            }
        )

    back = scored[scored["zone_name"] == "Back Forty"]
    if len(back) >= 10:
        sign_row = catalog["A-WAYFINDING"]
        days = max(0, HORIZON_DAYS - int(sign_row["lead_days"]))
        # Ratio of sums over the window, then per calendar day the zone was open.
        theo_per_day = float(back["theo"].sum() / back["n_days"].max())
        lift = 0.05
        actions.append(
            {
                "action_type_id": "A-WAYFINDING",
                "name": sign_row["name"],
                "quantity": 1,
                "targets": ["Back Forty"],
                "target_detail": [{"zone": "Back Forty", "assumed_lift": lift, "days": days}],
                "cost_usd": round(_cost(sign_row, 1), 2),
                "expected_july_theo_usd": round(theo_per_day * days * lift, 0),
                "upside_july_theo_usd": round(theo_per_day * days * 0.10, 0),
                "uncertainty": (
                    f"Back Forty theoretical win is about ${theo_per_day:,.0f} a day. "
                    "The plan assumes signs lift that by 5 percent for the "
                    f"{days} days after the lead time. Zero and 10 percent are the bounds. "
                    "Signs will not turn the back of the floor into the main entrance."
                ),
                "measure": (
                    "Back Forty coin-in per available hour versus Garage Entrance, "
                    "same weekdays, before and after the signs go up."
                ),
            }
        )

    inspect_row = catalog["A-INSPECT"]
    suspects = scored[
        (scored["cause"] == "payout_inspect") & (~scored["machine_id"].isin(move_ids))
    ].sort_values("luck_z")
    limit = min(4, int(inspect_row["quantity_limit"]))
    suspects = suspects.head(limit)
    if not suspects.empty:
        detail = [
            {
                "machine_id": row["machine_id"],
                "theme": row["theme"],
                "zone": row["zone_name"],
                "luck_z": round(float(row["luck_z"]), 2),
                "hold": round(float(row["hold"]), 4),
                "theo_hold": round(float(row["theo_hold"]), 4),
            }
            for _, row in suspects.iterrows()
        ]
        actions.append(
            {
                "action_type_id": "A-INSPECT",
                "name": inspect_row["name"],
                "quantity": len(detail),
                "targets": [
                    f"{item['machine_id']} {item['theme']} ({item['zone']}, z={item['luck_z']})"
                    for item in detail
                ],
                "target_detail": detail,
                "cost_usd": round(_cost(inspect_row, len(detail)), 2),
                "expected_july_theo_usd": 0,
                "upside_july_theo_usd": 0,
                "uncertainty": (
                    "An inspection buys information. A large negative residual can be a "
                    "run of luck, especially on a high-volatility title. Nothing here is "
                    "treated as a finding of misconduct. No theoretical win is booked "
                    "until the paytable is checked."
                ),
                "measure": (
                    "Configured RTP versus observed hold on the inspected cabinets only, "
                    "over the following 30 days, compared with uninspected cabinets of the same theme."
                ),
            }
        )

    spent = round(sum(item["cost_usd"] for item in actions), 2)
    return {
        "actions": actions,
        "spent_usd": spent,
        "unspent_usd": round(BUDGET_USD - spent, 2),
        "budget_usd": BUDGET_USD,
        "action_types": len(actions),
        "spells": spells,
        "haircut": HAIRCUT,
    }
