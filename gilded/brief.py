"""Call sheet. The template always works. Gemini rewrites it from the facts object."""

from __future__ import annotations

import json
import os
from typing import Any

FIELDS = ("slice_finding", "leave_alone", "fund", "how_we_know")


def _cleared_sentence(facts: dict) -> str:
    cleared = facts["cleared_by_test"]
    parts = []
    labels = [
        ("location", "sits in a cold spot", "sit in a cold spot"),
        ("short_tenure", "was not on the floor long enough", "were not on the floor long enough"),
        ("luck", "is inside a luck band", "are inside a luck band"),
        ("game_mix", "is a low-hold game doing what its paytable says", "are low-hold games doing what their paytable says"),
        ("payout_inspect", "needs a paytable check before anyone replaces it", "need a paytable check before anyone replaces them"),
        ("downtime", "was limited by downtime", "were limited by downtime"),
    ]
    for key, singular, plural in labels:
        count = cleared.get(key, 0)
        if count:
            phrase = singular if count == 1 else plural
            parts.append(f"{count} {phrase}")
    if not parts:
        return "The lowest house-win cabinets stay open after the fair tests."
    return "Of the 10 lowest house-win cabinets, " + "; ".join(parts) + "."


def template_brief(facts: dict) -> dict[str, str]:
    window = facts["slice"]
    where = window["zone"] or "the whole floor"
    if window["bank"]:
        where = f"{window['bank']} in {where}"
    spent = facts["spent_usd"]
    names = ", ".join(item["name"] for item in facts["actions"]) or "no new spend"
    forecast = facts["forecast"]
    drilled = window["zone"] or window["bank"]
    in_slice = len(facts.get("naive_in_this_slice") or [])
    lead = f"From {window['start']} to {window['end']}, looking at {where}. "
    if drilled:
        verb = "is" if in_slice == 1 else "are"
        lead += f"{in_slice} of the property's 10 lowest house-win cabinets {verb} in this slice. "
    return {
        "slice_finding": (
            lead
            + _cleared_sentence(facts)
            + " Total house win is the wrong ranking for a replacement."
        ),
        "leave_alone": (
            "Do not buy replacement cabinets for the short-tenure, high-RTP, or unlucky names. "
            "Availability on this floor is already about 99 percent, so a technician does not clear $11,520. "
            "A promotion weekend would have to add about "
            f"${forecast['promo_hurdle_coin_in_usd']:,.0f} of coin-in above a Saturday the weekday model already expects."
        ),
        "fund": (
            f"Fund {names}. Cost ${spent:,.0f} of the $100,000. "
            f"Leave ${facts['unspent_usd']:,.0f} unspent. "
            "The move list is capped by empty slots in stronger zones, not by the budget."
        ),
        "how_we_know": (
            "Moved cabinets: theoretical win per available hour against same-theme cabinets left in Back Forty. "
            "Signs: Back Forty coin-in per hour against Garage Entrance. "
            "Inspections: observed hold against configured RTP, with no theo booked in advance. "
            f"The weekday forecast MAE on May–June is ${forecast['weekday_mae_usd']:,.0f}, "
            f"against ${forecast['baseline_mae_usd']:,.0f} for a flat average."
        ),
        "source": "template",
    }


def _client(api_key: str):
    from google import genai

    return genai.Client(api_key=api_key)


def gemini_brief(facts: dict, api_key: str, model: str | None = None) -> dict[str, str]:
    """Rewrite the call sheet. Every number must already be in `facts`."""
    model_name = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    payload = json.dumps(facts, default=str)
    prompt = f"""You are the floor analytics lead at a fictional casino, The Gilded Ace.
Write a manager call sheet from the JSON facts below. Use only numbers and machine ids that appear in the JSON. If a figure is absent, leave it out.

Rules:
- Four short sections, about 120 words total.
- slice_finding: what this date and zone slice shows about the lowest house-win machines.
- leave_alone: which cabinets not to replace, and why luck, tenure, game mix, or downtime is the wrong purchase.
- fund: the actions, their cost, and that unspent money stays unspent.
- how_we_know: the measurement for July.
- Do not accuse anyone of cheating. A strange payout is a reason to inspect.
- Do not suggest pushing heavy losers to wager more.
- The casino and its people are fictional.

FACTS:
{payload}
"""
    from google.genai import types

    response = _client(api_key).models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema={
                "type": "OBJECT",
                "properties": {field: {"type": "STRING"} for field in FIELDS},
                "required": list(FIELDS),
            },
        ),
    )
    raw: Any = getattr(response, "text", None) or ""
    parsed = json.loads(raw)
    brief = {field: str(parsed[field]).strip() for field in FIELDS}
    brief["source"] = f"gemini:{model_name}"
    return brief


def write_brief(facts: dict, api_key: str | None) -> dict[str, str]:
    if not api_key:
        return template_brief(facts)
    try:
        return gemini_brief(facts, api_key)
    except Exception as exc:  # noqa: BLE001 — the page must render if the free tier fails
        brief = template_brief(facts)
        brief["source"] = "template"
        brief["gemini_error"] = str(exc)[:300]
        return brief
