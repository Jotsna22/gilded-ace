"""Run the decision math and fail loudly if a budget or forecast rule breaks."""

from __future__ import annotations

import json

from gilded.actions import build as build_plan
from gilded.brief import template_brief
from gilded.facts import build as build_facts
from gilded.forecast import build as build_forecast
from gilded.paths import DEFAULT_END, DEFAULT_START
from gilded.scorecard import build as build_scorecard
from gilded.scorecard import naive_bottom
from gilded import warehouse


def main() -> None:
    scored = build_scorecard(DEFAULT_START, DEFAULT_END)
    naive = naive_bottom(scored)
    con = warehouse.connect()
    try:
        theme_zone = warehouse.theme_zone_rates(con, DEFAULT_START, DEFAULT_END)
    finally:
        con.close()
    plan = build_plan(scored, DEFAULT_START, DEFAULT_END, theme_zone)
    forecast = build_forecast()
    facts = build_facts(scored, scored, plan, forecast, DEFAULT_START, DEFAULT_END, None, None)
    brief = template_brief(facts)

    print("Naive bottom 10")
    print(
        naive[
            ["machine_id", "theme", "zone_name", "n_days", "house_win", "theo", "cph", "luck_z", "cause"]
        ].to_string(index=False)
    )
    print("\nCause counts")
    print(scored["cause"].value_counts().to_string())
    print("\nPlan")
    for action in plan["actions"]:
        print(
            f"  {action['action_type_id']} x{action['quantity']} "
            f"${action['cost_usd']:,.0f} expected theo ${action['expected_july_theo_usd']:,.0f}"
        )
        for target in action["targets"]:
            print(f"    - {target}")
    print(f"Spent ${plan['spent_usd']:,.0f}  unspent ${plan['unspent_usd']:,.0f}")
    print(
        f"MAE weekday ${forecast['mae_weekday']:,.0f}  "
        f"baseline ${forecast['mae_baseline']:,.0f}  "
        f"promo hurdle ${forecast['promo_hurdle_coin_in']:,.0f}"
    )
    print("Brief source", brief["source"])

    assert forecast["mae_weekday"] < forecast["mae_baseline"]
    assert plan["spent_usd"] <= plan["budget_usd"]
    assert plan["action_types"] <= 3
    ids = {item["action_type_id"] for item in plan["actions"]}
    assert not ({"A-COMP-PILOT", "A-COMP-CHANGE"} <= ids)
    assert "A-REPLACE-BUY" not in ids
    spells = plan["spells"]
    move = spells[spells["machine_id"] == "M-1152"].sort_values("first_date")
    assert len(move) == 2
    assert float(move["cph"].iloc[1]) > float(move["cph"].iloc[0]) * 1.5
    json.dumps(facts)
    assert set(brief) >= {"slice_finding", "leave_alone", "fund", "how_we_know"}
    print("\nSelf-check passed")


if __name__ == "__main__":
    main()
