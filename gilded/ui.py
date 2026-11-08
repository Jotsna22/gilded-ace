"""Manager-facing pages. Clicking a period, zone, cabinet, or guest group changes the slice."""

from __future__ import annotations

import hashlib
import html
import json
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from gilded.actions import build as build_plan
from gilded.brief import write_brief
from gilded.facts import build as build_facts
from gilded.forecast import WEEKDAY_ORDER
from gilded.forecast import build as build_forecast
from gilded.paths import DEFAULT_END, DEFAULT_START
from gilded.scorecard import CAUSE_LABEL, apply_slice, naive_bottom
from gilded.scorecard import build as build_scorecard
from gilded import warehouse

CAUSE_COLOR = {
    "location": "#b8975a",
    "payout_inspect": "#8c3a3a",
    "short_tenure": "#6b7a72",
    "downtime": "#a35b2a",
    "game_mix": "#5c6b4a",
    "luck": "#3f6f8a",
    "on_pace": "#234f3b",
}

PAGES = ["The call", "The floor", "Triage", "Demand", "Downtime", "Guests", "Proof"]
PRESETS = {
    "Jan–Jun": ("2025-01-01", "2025-06-30"),
    "Apr–Jun": ("2025-04-01", "2025-06-30"),
    "May–Jun": ("2025-05-01", "2025-06-30"),
    "June": ("2025-06-01", "2025-06-30"),
}
MONEY = {
    "House win": st.column_config.NumberColumn(format="$%,.0f"),
    "Theo": st.column_config.NumberColumn(format="$%,.0f"),
    "Coin-in / hour": st.column_config.NumberColumn(format="$%.1f"),
    "Luck z": st.column_config.NumberColumn(format="%.2f"),
}
CHART = {"displayModeBar": False}


def _money(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"${value:,.0f}"


def _inject_css() -> None:
    st.markdown(
        """
        <style>
          .stAppDeployButton, #MainMenu, footer { display: none; }
          header[data-testid="stHeader"] { background: #f3f3ee; }
          .block-container { padding-top: 4.4rem; max-width: 1180px; }
          section[data-testid="stSidebar"] {
            background: #fdfdf9; border-right: 1px solid #e3e3da;
          }
          h1 { font-weight: 500; letter-spacing: -0.03em; margin-bottom: 0.2rem; }
          .eyebrow { letter-spacing: 0.18em; text-transform: uppercase;
                     color: #b8975a; font-size: 0.72rem; font-weight: 600; }
          .brand-mark { font-size: 1.35rem; font-weight: 500; color: #1f3a2e; }
          .brief { background: #fdfdf9; border: 1px solid #e3e3da; border-radius: 12px;
                   padding: 16px 18px 6px; }
          .brief h3 { margin: 0 0 4px; font-size: 0.92rem; color: #234f3b; }
          .brief p { margin: 0 0 12px; }
          .source { color: #6b7a72; font-size: 0.78rem; }
          div[data-testid="stElementToolbar"] { display: none; }
          div[data-testid="stMetric"] {
            background: #fdfdf9; border: 1px solid #e3e3da;
            border-radius: 12px; padding: 10px 14px;
          }
          .chip { display: inline-block; margin: 0 6px 6px 0; padding: 2px 8px;
                  border-radius: 999px; font-size: 0.75rem; color: #fdfdf9; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _style(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        plot_bgcolor="#fdfdf9",
        paper_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, system-ui, sans-serif", "color": "#1f3a2e", "size": 13},
        legend={"orientation": "h", "y": 1.14, "x": 0},
        hoverlabel={"bgcolor": "#1f3a2e", "font_color": "#fdfdf9"},
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor="#e3e3da", automargin=True)
    fig.update_yaxes(gridcolor="#ecece4", zeroline=False, linecolor="#e3e3da", automargin=True)
    return fig


def _points(event) -> list:
    if event is None:
        return []
    selection = event["selection"] if isinstance(event, dict) else getattr(event, "selection", None)
    if selection is None:
        return []
    points = selection["points"] if isinstance(selection, dict) else getattr(selection, "points", None)
    return list(points or [])


def _rows(event) -> list:
    if event is None:
        return []
    selection = event["selection"] if isinstance(event, dict) else getattr(event, "selection", None)
    if selection is None:
        return []
    rows = selection["rows"] if isinstance(selection, dict) else getattr(selection, "rows", None)
    return list(rows or [])


def _point_label(point: dict) -> str | None:
    value = point.get("customdata")
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        value = point.get("y") or point.get("x")
    return None if value is None else str(value)


def _chart(fig: go.Figure, key: str | None = None, selectable: bool = False):
    kwargs = {"width": "stretch", "config": CHART, "theme": None}
    if key is not None:
        kwargs["key"] = key
    if selectable:
        return st.plotly_chart(fig, on_select="rerun", selection_mode="points", **kwargs)
    return st.plotly_chart(fig, **kwargs)


def _clear_slice() -> None:
    st.session_state["zone_choice"] = "All zones"
    st.session_state["bank_choice"] = "All banks"
    st.session_state["zone_click_token"] = ""
    st.session_state["zone_chart_gen"] = st.session_state.get("zone_chart_gen", 0) + 1


@st.cache_data(show_spinner=False)
def load_forecast() -> dict:
    return build_forecast()


@st.cache_data(show_spinner="Scoring the floor…")
def load_floor(start: str, end: str):
    scored = build_scorecard(start, end)
    con = warehouse.connect()
    try:
        theme_zone = warehouse.theme_zone_rates(con, start, end)
    finally:
        con.close()
    plan = build_plan(scored, start, end, theme_zone)
    spells = plan.pop("spells")
    return scored, theme_zone, plan, spells


@st.cache_data(show_spinner=False)
def load_geometry() -> pd.DataFrame:
    con = warehouse.connect()
    try:
        return warehouse.floor_geometry(con)
    finally:
        con.close()


@st.cache_data(show_spinner=False)
def load_empty(on_date: str) -> pd.DataFrame:
    con = warehouse.connect()
    try:
        return warehouse.empty_slots(con, on_date)
    finally:
        con.close()


@st.cache_data(show_spinner=False)
def load_players():
    con = warehouse.connect()
    try:
        totals = warehouse.player_totals(con)
        months = warehouse.player_months(con)
        property_days = warehouse.property_days(con)
    finally:
        con.close()
    return totals, months, property_days


def _brief_for(facts: dict, api_key: str) -> dict:
    if not api_key:
        return write_brief(facts, None)
    raw = json.dumps(facts, sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    key_tag = hashlib.sha256(api_key.encode()).hexdigest()[:8]
    token = f"{digest}:{key_tag}"
    cache = st.session_state.setdefault("briefs", {})
    if token not in cache:
        cache[token] = write_brief(facts, api_key)
    return cache[token]


def _on_preset() -> None:
    name = st.session_state.get("period_preset")
    if name in PRESETS:
        start, end = PRESETS[name]
        st.session_state["start_date"] = pd.Timestamp(start).date()
        st.session_state["end_date"] = pd.Timestamp(end).date()


def _init_state() -> None:
    st.session_state.setdefault("start_date", pd.Timestamp(DEFAULT_START).date())
    st.session_state.setdefault("end_date", pd.Timestamp(DEFAULT_END).date())
    st.session_state.setdefault("zone_choice", "All zones")
    st.session_state.setdefault("bank_choice", "All banks")
    st.session_state.setdefault("page", "The call")
    st.session_state.setdefault("machine_pick", None)
    queued = st.session_state.pop("queued_zone", None)
    if queued:
        st.session_state["zone_choice"] = queued
        st.session_state["bank_choice"] = "All banks"


def _sidebar(scored: pd.DataFrame) -> tuple[str, str, str | None, str | None, str]:
    st.sidebar.markdown('<div class="brand-mark">♠ The Gilded Ace</div>', unsafe_allow_html=True)
    st.sidebar.caption("Dates rescore the floor. Zone and bank narrow the tables. The forecast test stays May–June.")
    st.sidebar.segmented_control(
        "Period",
        list(PRESETS),
        default="Jan–Jun",
        key="period_preset",
        on_change=_on_preset,
        required=True,
        width="stretch",
    )
    bound = (pd.Timestamp(DEFAULT_START).date(), pd.Timestamp(DEFAULT_END).date())
    start = st.sidebar.date_input("From", key="start_date", min_value=bound[0], max_value=bound[1])
    end = st.sidebar.date_input("To", key="end_date", min_value=bound[0], max_value=bound[1])
    zones = ["All zones"] + sorted(scored["zone_name"].dropna().unique())
    if st.session_state.get("zone_choice") not in zones:
        st.session_state["zone_choice"] = "All zones"
    zone = st.sidebar.selectbox("Zone", zones, key="zone_choice")
    zone_value = None if zone == "All zones" else zone
    banks = scored if zone_value is None else scored[scored["zone_name"] == zone_value]
    bank_options = ["All banks"] + sorted(banks["bank_id"].dropna().unique())
    if st.session_state.get("bank_choice") not in bank_options:
        st.session_state["bank_choice"] = "All banks"
    bank = st.sidebar.selectbox("Bank", bank_options, key="bank_choice")
    bank_value = None if bank == "All banks" else bank
    if zone_value or bank_value:
        st.sidebar.button("Clear zone and bank", on_click=_clear_slice)
    with st.sidebar.expander("Gemini call sheet"):
        api_key = st.text_input(
            "API key",
            value=os.environ.get("GEMINI_API_KEY", ""),
            type="password",
            help="Optional. Numbers still come from the scorecard.",
        )
        if st.button("Rewrite this slice"):
            st.session_state["briefs"] = {}
    return start.isoformat(), end.isoformat(), zone_value, bank_value, api_key.strip()


def _naive_table(frame: pd.DataFrame, detailed: bool = False) -> pd.DataFrame:
    columns = {
        "machine_id": "Machine",
        "cause_label": "Cause",
        "theme": "Theme",
        "zone_name": "Zone",
        "n_days": "Days",
        "house_win": "House win",
        "theo": "Theo",
    }
    if detailed:
        columns = {
            "machine_id": "Machine",
            "cause_label": "Cause",
            "theme": "Theme",
            "zone_name": "Zone",
            "bank_id": "Bank",
            "n_days": "Days",
            "house_win": "House win",
            "cph": "Coin-in / hour",
            "luck_z": "Luck z",
        }
    show = frame[list(columns)].copy()
    show.columns = list(columns.values())
    return show


def _machine_panel(row: pd.Series) -> None:
    st.markdown(f"**{row['machine_id']} · {row['theme']}**")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cause", row["cause_label"])
    c2.metric("Coin-in / hour", _money(row["cph"]))
    c3.metric("Same theme elsewhere", _money(row["peer_cph_elsewhere"]))
    c4.metric("Theo contribution", _money(row["theo_contribution"]))
    peer = row["peer_cph_elsewhere"]
    labels = ["This cabinet"]
    values = [float(row["cph"]) if pd.notna(row["cph"]) else 0]
    colors = ["#b8975a"]
    if pd.notna(peer):
        labels.append("Same theme, other zones")
        values.append(float(peer))
        colors.append("#234f3b")
    fig = go.Figure(go.Bar(y=labels, x=values, orientation="h", marker_color=colors, hovertemplate="$%{x:.0f}<extra></extra>"))
    _style(fig, 150)
    fig.update_layout(margin={"l": 168, "r": 16, "t": 8, "b": 8}, yaxis={"categoryorder": "array", "categoryarray": labels[::-1], "automargin": True})
    _chart(fig)
    st.caption(
        f"{row['zone_name']} · {row['bank_id']} · {row['volatility_class']} volatility · "
        f"RTP {float(row['configured_rtp']):.1%} · {int(row['n_days'])} days on the floor · "
        f"runner-up {CAUSE_LABEL.get(row['runner_up'], row['runner_up'])}."
    )


def _legend() -> None:
    chips = "".join(
        f'<span class="chip" style="background:{color}">{html.escape(CAUSE_LABEL[cause])}</span>'
        for cause, color in CAUSE_COLOR.items()
    )
    st.markdown(chips, unsafe_allow_html=True)


def _page_call(scored, sliced, plan, spells, facts, brief) -> None:
    window = facts["slice"]
    st.markdown('<div class="eyebrow">Floor decision</div>', unsafe_allow_html=True)
    st.title("Luck, location, or a leak?")
    where = window["zone"] or "the whole floor"
    if window["bank"]:
        where = f"bank {window['bank']}"
    st.caption(f"{window['start']} to {window['end']} · {where}. Fictional floor, synthetic play.")

    naive = naive_bottom(scored, 10)
    replaceable = int((naive["cause"] == "on_pace").sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Bottom 10 we would replace", f"{replaceable} of 10")
    c2.metric("July spend", _money(plan["spent_usd"]))
    c3.metric("Left unspent", _money(plan["unspent_usd"]))
    c4.metric(
        "Weekday forecast MAE",
        _money(facts["forecast"]["weekday_mae_usd"]),
        help=f"Flat training-mean MAE on May–June is {_money(facts['forecast']['baseline_mae_usd'])}.",
    )

    moved = spells[spells["machine_id"] == "M-1152"].sort_values("first_date")
    if len(moved) >= 2:
        st.info(
            f"**Already observed.** {moved['machine_id'].iloc[0]} ({moved['theme'].iloc[0]}) "
            f"did {_money(moved['cph'].iloc[0])} of coin-in per hour in {moved['zone_name'].iloc[0]}, "
            f"then {_money(moved['cph'].iloc[1])} after it moved to {moved['zone_name'].iloc[1]}."
        )

    left, right = st.columns([1.25, 1], gap="large")
    with left:
        st.subheader("The general manager's list")
        st.caption("Click a row. Lowest house win on active days, with the fair-test cause.")
        filtered = bool(window["zone"] or window["bank"])
        view = naive if not filtered else naive_bottom(sliced, min(10, max(len(sliced), 1)))
        if filtered:
            st.caption("This table follows the filter. The July budget below stays the property plan.")
        if view.empty:
            st.warning("No active cabinets in this slice.")
        else:
            view = view.reset_index(drop=True)
            picked = st.dataframe(
                _naive_table(view),
                width="stretch",
                hide_index=True,
                column_config=MONEY,
                on_select="rerun",
                selection_mode="single-row",
                key="call_table",
            )
            chosen = _rows(picked)
            if chosen:
                _machine_panel(view.iloc[chosen[0]])
    with right:
        st.subheader("Call sheet")
        source = brief.get("source", "template")
        label = "Gemini, from the facts only" if str(source).startswith("gemini") else "Written from the scorecard"
        st.markdown(
            f"""
            <div class="brief">
              <h3>What this slice shows</h3><p>{html.escape(brief['slice_finding'])}</p>
              <h3>Leave alone</h3><p>{html.escape(brief['leave_alone'])}</p>
              <h3>Fund</h3><p>{html.escape(brief['fund'])}</p>
              <h3>How we will know</h3><p>{html.escape(brief['how_we_know'])}</p>
              <div class="source">{html.escape(label)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if brief.get("gemini_error"):
            st.caption(f"Gemini did not answer. {brief['gemini_error']}")

    st.subheader("July budget")
    st.caption("Pick an action. Prices are the catalog. The planning case is half the location gap, or a 5 percent sign lift.")
    names = [item["name"] for item in plan["actions"]]
    if names:
        short = {
            item["name"]: {"A-MOVE-MACHINE": "Move", "A-WAYFINDING": "Signs", "A-INSPECT": "Inspect"}.get(
                item["action_type_id"], item["name"]
            )
            for item in plan["actions"]
        }
        current = st.session_state.get("action_pick")
        choice = st.pills(
            "Action",
            names,
            default=current if current in names else names[0],
            format_func=lambda name: short.get(name, name),
            key="action_pills",
            required=True,
        )
        selected = next(item for item in plan["actions"] if item["name"] == (choice or names[0]))
        with st.container(border=True):
            a, b, c = st.columns(3)
            a.metric("Quantity", selected["quantity"])
            b.metric("Cost", _money(selected["cost_usd"]))
            c.metric("July theo, planning case", _money(selected["expected_july_theo_usd"]))
            st.write(selected["uncertainty"])
            st.caption("Measure: " + selected["measure"])
            for target in selected["targets"]:
                st.write(f"- {target}")
            if selected["action_type_id"] == "A-MOVE-MACHINE" and selected["upside_july_theo_usd"]:
                st.caption(f"If the full location gap shows up, July theo is {_money(selected['upside_july_theo_usd'])}.")
            elif selected["action_type_id"] == "A-WAYFINDING" and selected["upside_july_theo_usd"]:
                st.caption(f"At a 10 percent lift, July theo is {_money(selected['upside_july_theo_usd'])}.")


def _page_triage(sliced: pd.DataFrame) -> None:
    st.subheader("Which cabinets are actually cold?")
    st.caption("Click a point or a row. Left means less demand. Below the line is a paytable worth inspecting.")
    _legend()
    if sliced.empty:
        st.warning("No active cabinets in this slice.")
        return
    query = st.text_input("Find a cabinet", placeholder="M-1152 or Jackpot Summit")
    view = sliced
    if query:
        mask = view["machine_id"].str.contains(query, case=False) | view["theme"].str.contains(query, case=False)
        view = view[mask]
    if view.empty:
        st.warning("Nothing matches that search.")
        return

    fig = go.Figure()
    for cause, color in CAUSE_COLOR.items():
        part = view[view["cause"] == cause]
        if part.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=part["cph"],
                y=part["luck_z"],
                mode="markers",
                name=CAUSE_LABEL[cause],
                marker={"color": color, "size": 10, "opacity": 0.88, "line": {"width": 0}},
                customdata=part["machine_id"],
                hovertemplate="%{customdata}<br>$%{x:.0f} per hour<br>luck z %{y:.2f}<extra></extra>",
            )
        )
    fig.add_hline(y=-3, line_dash="dot", line_color="#8c3a3a")
    _style(fig, 440)
    chart = _chart(fig, key="triage_scatter", selectable=True)
    points = _points(chart)
    if points:
        machine_id = _point_label(points[0])
        token = json.dumps(points[0], default=str)
        if machine_id and token != st.session_state.get("scatter_token"):
            st.session_state["scatter_token"] = token
            st.session_state["machine_pick"] = machine_id

    show = _naive_table(view.sort_values("house_win"), detailed=True).reset_index(drop=True)
    picked = st.dataframe(
        show,
        width="stretch",
        hide_index=True,
        column_config=MONEY,
        on_select="rerun",
        selection_mode="single-row",
        key="triage_table",
    )
    chosen = _rows(picked)
    if chosen:
        machine_id = show.iloc[chosen[0]]["Machine"]
    else:
        machine_id = st.session_state.get("machine_pick")
    match = view[view["machine_id"] == machine_id]
    if match.empty:
        match = view.iloc[[0]]
    _machine_panel(match.iloc[0])


def _page_demand(forecast: dict, scored: pd.DataFrame, start: str, end: str, zone: str | None) -> None:
    st.subheader("What changed in demand")
    st.caption("Click a zone to filter the floor. The weekday mean was frozen on January–April. Shaded days are the May–June holdout.")
    grain = st.segmented_control("Grain", ["Daily", "Weekly"], default="Daily", key="demand_grain", required=True)
    daily = forecast["daily"].copy()
    daily = daily[(daily["gaming_date"] >= pd.Timestamp(start)) & (daily["gaming_date"] <= pd.Timestamp(end))]
    plotted = daily
    if grain == "Weekly" and not daily.empty:
        plotted = (
            daily.set_index("gaming_date")[["coin_in_usd", "weekday_coin_in", "baseline_coin_in"]]
            .resample("W-MON")
            .sum()
            .reset_index()
        )
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=plotted["gaming_date"], y=plotted["coin_in_usd"], name="Actual coin-in", line={"color": "#234f3b", "width": 2}))
    fig.add_trace(go.Scatter(x=plotted["gaming_date"], y=plotted["weekday_coin_in"], name="Weekday forecast", line={"color": "#b8975a", "width": 2, "dash": "dash"}))
    fig.add_trace(go.Scatter(x=plotted["gaming_date"], y=plotted["baseline_coin_in"], name="Flat training mean", line={"color": "#6b7a72", "width": 1.5, "dash": "dot"}))
    if not daily.empty and pd.Timestamp(forecast["test_start"]) <= pd.Timestamp(end):
        fig.add_vrect(
            x0=max(pd.Timestamp(forecast["test_start"]), pd.Timestamp(start)),
            x1=pd.Timestamp(end),
            fillcolor="#b8975a",
            opacity=0.12,
            line_width=0,
        )
    _style(fig, 380)
    _chart(fig)
    a, b, c = st.columns(3)
    a.metric("Holdout MAE, weekday", _money(forecast["mae_weekday"]))
    b.metric("Holdout MAE, flat mean", _money(forecast["mae_baseline"]))
    c.metric("Promo hurdle", _money(forecast["promo_hurdle_coin_in"]))
    st.caption(
        "Those errors are always May–June, even if the chart is a shorter slice. "
        f"A $15,000 weekend has to beat the Saturday forecast of {_money(forecast['saturday_forecast'])} "
        f"by {_money(forecast['promo_hurdle_coin_in'])}. May–June Saturdays averaged {_money(forecast['saturday_test_mean'])}."
    )

    grouped = scored.groupby("zone_name")[["coin_in", "avail_h"]].sum()
    zones = grouped.assign(coin_per_hour=lambda frame: frame["coin_in"] / frame["avail_h"]).reset_index()
    zones = zones.sort_values("coin_per_hour")
    colors = ["#b8975a" if name == zone else "#234f3b" for name in zones["zone_name"]]
    bar = go.Figure(
        go.Bar(
            y=zones["zone_name"],
            x=zones["coin_per_hour"],
            orientation="h",
            marker_color=colors,
            customdata=zones["zone_name"],
            hovertemplate="%{y}<br>$%{x:.0f} per hour<br>Click to filter<extra></extra>",
        )
    )
    _style(bar, 340)
    bar.update_layout(margin={"l": 150, "r": 24, "t": 12, "b": 12})
    clicked = _chart(bar, key=f"zone_bars_{st.session_state.get('zone_chart_gen', 0)}", selectable=True)
    points = _points(clicked)
    if points:
        name = _point_label(points[0])
        token = json.dumps(points[0], default=str)
        if name and token != st.session_state.get("zone_click_token"):
            st.session_state["zone_click_token"] = token
            st.session_state["queued_zone"] = name
            st.rerun()

    weekday = pd.Series(forecast["by_weekday"]).reindex(WEEKDAY_ORDER).rename("Training mean coin-in").reset_index()
    weekday.columns = ["Weekday", "Training mean coin-in"]
    st.dataframe(
        weekday,
        hide_index=True,
        width="stretch",
        column_config={"Training mean coin-in": st.column_config.NumberColumn(format="$%,.0f")},
    )


def _page_downtime(scored: pd.DataFrame) -> None:
    st.subheader("Play lost to downtime")
    st.caption("Lost theo is downtime hours times that cabinet's own theo per available hour. The line is one technician for 30 days, $11,520.")
    if scored.empty:
        st.warning("No active cabinets in this slice.")
        return
    by_mfr = (
        scored.groupby("manufacturer", as_index=False)
        .agg(lost_theo=("lost_theo", "sum"), down_h=("down_h", "sum"), faults=("faults", "sum"), repair=("repair_cost", "sum"))
        .sort_values("lost_theo", ascending=False)
    )
    months = max(float(scored["window_days"].iloc[0]) / 30.0, 1)
    by_mfr["lost_theo_per_30d"] = by_mfr["lost_theo"] / months
    fig = go.Figure(go.Bar(x=by_mfr["manufacturer"], y=by_mfr["lost_theo_per_30d"], marker_color="#234f3b", hovertemplate="%{x}<br>$%{y:,.0f}<extra></extra>"))
    fig.add_hline(y=11_520, line_dash="dot", line_color="#8c3a3a")
    _style(fig, 340)
    _chart(fig)
    worst = by_mfr.iloc[0]
    st.write(
        f"Removing every {worst['manufacturer']} fault would recover about "
        f"{_money(worst['lost_theo_per_30d'])} of theoretical win per 30 days. "
        "That sits under the technician price, so the budget does not buy one."
    )
    show = by_mfr.copy()
    show.columns = ["Manufacturer", "Lost theo, window", "Down hours", "Faults", "Repair cost", "Lost theo / 30 days"]
    st.dataframe(
        show,
        hide_index=True,
        width="stretch",
        column_config={
            "Lost theo, window": st.column_config.NumberColumn(format="$%,.0f"),
            "Down hours": st.column_config.NumberColumn(format="%.0f"),
            "Repair cost": st.column_config.NumberColumn(format="$%,.0f"),
            "Lost theo / 30 days": st.column_config.NumberColumn(format="$%,.0f"),
        },
    )


def _page_guests() -> None:
    st.subheader("Carded players and the comp program")
    st.caption("Pick a tier or a home region. Player tables are loyalty-card play only. Comp cost is already inside cost of goods.")
    totals, months, property_days = load_players()
    tier = st.pills("Tier", ["All tiers", "Base", "Gold", "Platinum"], default="All tiers", key="guest_tier")
    region = st.pills("Home region", ["All regions", "Local", "Domestic", "Regional", "International"], default="All regions", key="guest_region")
    group = totals
    if tier and tier != "All tiers":
        group = group[group["tier_end"] == tier]
    if region and region != "All regions":
        group = group[group["home_region"] == region]
    if group.empty:
        st.warning("No carded players in that group.")
        return
    ranked = group.sort_values("theo", ascending=False).reset_index(drop=True)
    n = len(ranked)
    ranked["decile"] = (pd.Series(range(n)) * 10 // n) + 1
    decile = ranked.groupby("decile", as_index=False).agg(players=("player_id", "count"), theo=("theo", "sum"), comp=("comp_cost", "sum"))
    decile["theo_share"] = decile["theo"] / decile["theo"].sum()
    comp_total = decile["comp"].sum()
    decile["comp_share"] = decile["comp"] / comp_total if comp_total else 0
    top = decile[decile["decile"] == 1].iloc[0]
    label = " · ".join(part for part in [tier if tier and tier != "All tiers" else None, region if region and region != "All regions" else None] if part) or "All carded players"
    st.caption(f"{label} · {n:,} players")
    c1, c2, c3 = st.columns(3)
    c1.metric("Top decile of theo", f"{top['theo_share']:.0%}")
    c2.metric("Top decile of comp cost", f"{top['comp_share']:.0%}")
    c3.metric("Comp ÷ theo, top decile", f"{(top['comp'] / top['theo']):.1%}" if top["theo"] else "—")

    fig = go.Figure()
    fig.add_trace(go.Bar(x=decile["decile"], y=decile["theo_share"], name="Share of theo", marker_color="#234f3b"))
    fig.add_trace(go.Bar(x=decile["decile"], y=decile["comp_share"], name="Share of comp cost", marker_color="#b8975a"))
    fig.update_layout(barmode="group")
    _style(fig, 340)
    fig.update_yaxes(tickformat=".0%")
    fig.update_xaxes(title="Decile, 1 = highest theoretical win")
    _chart(fig)

    property_days = property_days.copy()
    property_days["month"] = property_days["gaming_date"].astype(str).str.slice(0, 7)
    monthly = property_days.groupby("month", as_index=False).agg(theo=("theo_usd", "sum"), comp=("comp_cost_usd", "sum"))
    monthly["reinvestment"] = monthly["comp"] / monthly["theo"]
    line = go.Figure(go.Scatter(x=monthly["month"], y=monthly["reinvestment"], mode="lines+markers", line={"color": "#234f3b", "width": 2}, marker={"size": 8}))
    _style(line, 260)
    line.update_yaxes(title="Floor comp cost ÷ theoretical win", tickformat=".2%")
    st.caption("This line is the whole floor, every tier. It does not follow the pills above.")
    _chart(line)
    st.write(
        "Across the whole floor, comp cost stays under 1 percent of theoretical win. "
        "The group above can be tighter than that. It is not a large enough leak to spend a policy slot, "
        "and nothing here asks heavy losers to play more."
    )
    with st.expander("Carded play by month, whole floor"):
        st.dataframe(
            months,
            hide_index=True,
            width="stretch",
            column_config={
                "theo": st.column_config.NumberColumn("Theo", format="$%,.0f"),
                "comp_cost": st.column_config.NumberColumn("Comp cost", format="$%,.0f"),
                "coin_in": st.column_config.NumberColumn("Carded coin-in", format="$%,.0f"),
                "player_net": st.column_config.NumberColumn("Player net", format="$%,.0f"),
            },
        )


def _lookup(frame: pd.DataFrame, key: str) -> pd.Series | None:
    hit = frame[frame["location_id"] == key]
    if hit.empty or pd.isna(hit.iloc[0]["x_m"]):
        return None
    return hit.iloc[0]


def _path(
    fig: go.Figure,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    color: str,
    label: str | None = None,
    width: float = 3.4,
) -> None:
    fig.add_trace(
        go.Scatter(
            x=[x0, x1],
            y=[y0, y1],
            mode="lines",
            line={"color": color, "width": width},
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.add_annotation(
        x=x1,
        y=y1,
        ax=x0,
        ay=y0,
        xref="x",
        yref="y",
        axref="x",
        ayref="y",
        showarrow=True,
        arrowhead=3,
        arrowsize=1.4,
        arrowwidth=2.2,
        arrowcolor=color,
        text="",
    )
    if label:
        fig.add_annotation(
            x=(x0 + x1) / 2,
            y=(y0 + y1) / 2,
            text=label,
            showarrow=False,
            font={"size": 12, "color": color, "family": "IBM Plex Sans, system-ui, sans-serif"},
            bgcolor="rgba(253,253,249,0.92)",
            bordercolor=color,
            borderwidth=1,
            borderpad=3,
        )


ZONE_FILL = {
    "Main Entrance": "rgba(35,79,59,0.08)",
    "Center Pit": "rgba(35,79,59,0.05)",
    "Back Forty": "rgba(196,160,90,0.34)",
    "Bar Row": "rgba(35,79,59,0.07)",
    "Garage Entrance": "rgba(35,79,59,0.06)",
    "High-Limit Room": "rgba(140,58,58,0.07)",
    "Hotel Corridor": "rgba(35,79,59,0.06)",
}


def _page_floor(scored: pd.DataFrame, plan: dict, spells: pd.DataFrame, zone: str | None, bank: str | None, end: str) -> None:
    st.subheader("The building, not the ranking")
    st.caption(
        "Seven rooms from the survey. Gold room = Back Forty (cold). "
        "Gold arrows = July moves. Green arrow = M-1152 already walked to Main Entrance."
    )
    view = st.segmented_control(
        "Show",
        ["Decision", "Coin-in"],
        default="Decision",
        key="floor_view",
        required=True,
        help="Decision: only the call. Coin-in: every cabinet by demand.",
    )
    detail = st.toggle("Show every cabinet + empty slots", value=False, key="floor_detail")
    geometry = load_geometry()
    slots = geometry[geometry["node_type"] == "slot"].copy()
    zone_names = geometry[geometry["node_type"] == "zone"][["zone_id", "name"]].rename(columns={"name": "zone_name"})
    slots = slots.merge(zone_names, on="zone_id", how="left")
    occupied = scored.merge(slots[["location_id", "x_m", "y_m"]], on="location_id", how="inner")
    empty = load_empty(end).merge(slots[["location_id", "x_m", "y_m", "zone_name", "bank_id"]], on="location_id", how="left")
    moves = []
    for item in plan["actions"]:
        if item["action_type_id"] == "A-MOVE-MACHINE":
            moves.extend(item["target_detail"])
    destinations = {item["to_location"] for item in moves}
    origins = {item["from_location"] for item in moves}

    def _focus(frame: pd.DataFrame) -> pd.Series:
        if frame.empty:
            return pd.Series(dtype=bool)
        if bank and "bank_id" in frame:
            return frame["bank_id"] == bank
        if zone and "zone_name" in frame:
            return frame["zone_name"] == zone
        return pd.Series(True, index=frame.index)

    fig = go.Figure()
    zone_order = [
        "Main Entrance",
        "Center Pit",
        "Back Forty",
        "Bar Row",
        "Garage Entrance",
        "High-Limit Room",
        "Hotel Corridor",
    ]
    for name in zone_order:
        part = slots[slots["zone_name"] == name]
        if part.empty:
            continue
        pad = 2.4
        x0, x1 = float(part["x_m"].min()) - pad, float(part["x_m"].max()) + pad
        y0, y1 = float(part["y_m"].min()) - pad, float(part["y_m"].max()) + pad
        muted = (zone is not None and name != zone) or (bank is not None and not (part["bank_id"] == bank).any())
        cold_room = name == "Back Forty"
        fig.add_shape(
            type="rect",
            x0=x0,
            x1=x1,
            y0=y0,
            y1=y1,
            line={"color": "#8a6d3b" if cold_room else "#6b7a72", "width": 2.6 if cold_room else 1.4},
            fillcolor=ZONE_FILL[name],
            opacity=0.22 if muted else 1.0,
            layer="below",
        )
        # Label sits on the top edge so machine dots never bury the room name.
        fig.add_annotation(
            x=(x0 + x1) / 2,
            y=y1 - 1.2,
            text=f"<b>{name}</b>",
            showarrow=False,
            font={
                "size": 14 if cold_room else 12,
                "color": "#6e5528" if cold_room else "#1f3a2e",
                "family": "IBM Plex Sans, system-ui, sans-serif",
            },
            bgcolor="rgba(253,253,249,0.94)",
            bordercolor="#c4a05a" if cold_room else "#c5cdc6",
            borderwidth=1,
            borderpad=3,
            opacity=0.45 if muted else 1.0,
        )

    # Orientation: doors as labeled wedges outside the rooms.
    door_specs = [
        ("Main doors", 0.0, 50.0, "middle right", 8, 50),
        ("Garage", 130.0, 110.0, "top center", 130, 116),
        ("Hotel", 62.0, 0.0, "bottom center", 62, -6),
    ]
    for full, x, y, pos, tx, ty in door_specs:
        fig.add_trace(
            go.Scatter(
                x=[x],
                y=[y],
                mode="markers",
                marker={"size": 14, "symbol": "triangle-up", "color": "#1f3a2e", "angle": 90 if full == "Main doors" else 0},
                hovertemplate=f"{full}<extra></extra>",
                showlegend=False,
            )
        )
        fig.add_annotation(
            x=tx,
            y=ty,
            text=full,
            showarrow=False,
            font={"size": 12, "color": "#1f3a2e", "family": "IBM Plex Sans, system-ui, sans-serif"},
        )

    fine = occupied[~occupied["cause"].isin(["location", "payout_inspect"])]
    cold = occupied[occupied["cause"] == "location"]
    inspect = occupied[occupied["cause"] == "payout_inspect"]

    if view == "Coin-in":
        opac = [0.95 if flag else 0.12 for flag in _focus(occupied)]
        fig.add_trace(
            go.Scatter(
                x=occupied["x_m"],
                y=occupied["y_m"],
                mode="markers",
                name="Coin-in / hour",
                marker={
                    "size": 10,
                    "color": occupied["cph"],
                    "colorscale": [[0, "#c45c26"], [0.45, "#b8975a"], [1, "#234f3b"]],
                    "cmin": float(occupied["cph"].quantile(0.05)),
                    "cmax": float(occupied["cph"].quantile(0.95)),
                    "opacity": opac,
                    "colorbar": {"title": "$ / hour", "thickness": 14, "len": 0.45, "outlinewidth": 0},
                    "line": {"width": 0.3, "color": "rgba(31,58,46,0.2)"},
                },
                customdata=occupied[["machine_id", "theme", "zone_name"]].to_numpy(),
                hovertemplate="%{customdata[0]} · %{customdata[1]}<br>%{customdata[2]}<br>$%{marker.color:.0f} / hour<extra></extra>",
                showlegend=False,
            )
        )
    else:
        if detail and not fine.empty:
            fig.add_trace(
                go.Scatter(
                    x=fine["x_m"],
                    y=fine["y_m"],
                    mode="markers",
                    name="Leave alone",
                    marker={
                        "size": 7,
                        "color": "#9eb0a4",
                        "opacity": [0.55 if flag else 0.08 for flag in _focus(fine)],
                        "line": {"width": 0},
                    },
                    customdata=fine[["machine_id", "cause_label", "cph"]].to_numpy(),
                    hovertemplate="%{customdata[0]}<br>%{customdata[1]}<br>$%{customdata[2]:.0f} / hour<extra></extra>",
                    showlegend=False,
                )
            )
        if not cold.empty:
            fig.add_trace(
                go.Scatter(
                    x=cold["x_m"],
                    y=cold["y_m"],
                    mode="markers",
                    name="Cold spot",
                    marker={
                        "size": 11,
                        "color": "#c4a05a",
                        "opacity": [0.92 if flag else 0.1 for flag in _focus(cold)],
                        "line": {"width": 0.8, "color": "#6e5528"},
                    },
                    customdata=cold[["machine_id", "theme", "cph"]].to_numpy(),
                    hovertemplate="%{customdata[0]} · %{customdata[1]}<br>Cold spot · $%{customdata[2]:.0f} / hour<extra></extra>",
                    showlegend=False,
                )
            )
        if not inspect.empty:
            fig.add_trace(
                go.Scatter(
                    x=inspect["x_m"],
                    y=inspect["y_m"],
                    mode="markers",
                    name="Inspect payout",
                    marker={
                        "size": 12,
                        "symbol": "diamond",
                        "color": "#8c3a3a",
                        "opacity": [1.0 if flag else 0.1 for flag in _focus(inspect)],
                        "line": {"width": 1, "color": "#5c2222"},
                    },
                    customdata=inspect[["machine_id", "theme", "luck_z"]].to_numpy(),
                    hovertemplate="%{customdata[0]} · %{customdata[1]}<br>Inspect · luck z %{customdata[2]:.2f}<extra></extra>",
                    showlegend=False,
                )
            )

    held = empty[empty["location_id"].isin(destinations)]
    if detail:
        spare = empty[~empty["location_id"].isin(destinations)]
        if not spare.empty:
            fig.add_trace(
                go.Scatter(
                    x=spare["x_m"],
                    y=spare["y_m"],
                    mode="markers",
                    name="Empty",
                    marker={
                        "size": 8,
                        "color": "rgba(0,0,0,0)",
                        "line": {"color": "#6b7a72", "width": 1.2},
                        "opacity": [0.85 if flag else 0.08 for flag in _focus(spare)],
                    },
                    customdata=spare["location_id"],
                    hovertemplate="%{customdata}<br>Empty slot<extra></extra>",
                    showlegend=False,
                )
            )

    for item in moves:
        origin = _lookup(slots, item["from_location"])
        landing = _lookup(slots, item["to_location"])
        if origin is None or landing is None:
            continue
        _path(fig, float(origin["x_m"]), float(origin["y_m"]), float(landing["x_m"]), float(landing["y_m"]), "#b8975a", item["machine_id"], 3.6)
    if not held.empty:
        fig.add_trace(
            go.Scatter(
                x=held["x_m"],
                y=held["y_m"],
                mode="markers",
                name="July landing",
                marker={"size": 22, "symbol": "circle-open", "color": "#b8975a", "line": {"width": 3.2}},
                customdata=held["location_id"],
                hovertemplate="%{customdata}<br>July landing slot<extra></extra>",
                showlegend=False,
            )
        )
    leaving = occupied[occupied["location_id"].isin(origins)]
    if not leaving.empty:
        fig.add_trace(
            go.Scatter(
                x=leaving["x_m"],
                y=leaving["y_m"],
                mode="markers",
                name="July origin",
                marker={"size": 16, "symbol": "circle-open", "color": "#1f3a2e", "line": {"width": 2.6}},
                customdata=leaving[["machine_id", "theme"]].to_numpy(),
                hovertemplate="%{customdata[0]} · %{customdata[1]}<br>Leaves in July<extra></extra>",
                showlegend=False,
            )
        )

    moved = spells[spells["machine_id"] == "M-1152"].sort_values("first_date")
    if len(moved) >= 2:
        origin = _lookup(slots, moved["location_id"].iloc[0])
        landing = _lookup(slots, moved["location_id"].iloc[-1])
        if origin is not None and landing is not None:
            _path(
                fig,
                float(origin["x_m"]),
                float(origin["y_m"]),
                float(landing["x_m"]),
                float(landing["y_m"]),
                "#234f3b",
                "M-1152",
                3.0,
            )
            fig.add_trace(
                go.Scatter(
                    x=[landing["x_m"]],
                    y=[landing["y_m"]],
                    mode="markers",
                    marker={"size": 15, "symbol": "diamond", "color": "#234f3b"},
                    hovertemplate="M-1152 after the move · Main Entrance<extra></extra>",
                    showlegend=False,
                )
            )

    fig.update_layout(
        height=760,
        margin={"l": 40, "r": 24, "t": 12, "b": 32},
        plot_bgcolor="#e8ebe4",
        paper_bgcolor="rgba(0,0,0,0)",
        font={"family": "IBM Plex Sans, system-ui, sans-serif", "color": "#1f3a2e", "size": 13},
        showlegend=False,
        hoverlabel={"bgcolor": "#1f3a2e", "font_color": "#fdfdf9"},
        dragmode=False,
    )
    # Fixed ranges cover every surveyed room; no scaleanchor so the map fills the chart.
    fig.update_xaxes(
        title=None,
        range=[-8, 142],
        showgrid=False,
        zeroline=False,
        showticklabels=False,
        fixedrange=True,
    )
    fig.update_yaxes(
        title=None,
        range=[-12, 122],
        showgrid=False,
        zeroline=False,
        showticklabels=False,
        fixedrange=True,
    )
    chart = _chart(fig, key=f"floor_rooms_{view}_{int(detail)}", selectable=True)
    points = _points(chart)
    if points:
        label = _point_label(points[0])
        token = json.dumps(points[0], default=str)
        if label and token != st.session_state.get("floor_token"):
            st.session_state["floor_token"] = token
            if label.startswith("M-"):
                st.session_state["machine_pick"] = label

    st.markdown(
        """
        <div style="display:flex;flex-wrap:wrap;gap:16px;margin:2px 0 14px;font-size:0.95rem;color:#1f3a2e;">
          <span><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:#c4a05a;margin-right:6px;"></span>Cold spot (Back Forty)</span>
          <span><span style="display:inline-block;width:11px;height:11px;transform:rotate(45deg);background:#8c3a3a;margin-right:8px;"></span>Inspect payout</span>
          <span><span style="display:inline-block;width:22px;height:0;border-top:3px solid #b8975a;margin:0 6px 3px 0;vertical-align:middle;"></span>July move →</span>
          <span><span style="display:inline-block;width:22px;height:0;border-top:3px solid #234f3b;margin:0 6px 3px 0;vertical-align:middle;"></span>M-1152 already moved</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    location_cases = occupied[occupied["cause"] == "location"]
    back = int((location_cases["zone_name"] == "Back Forty").sum())
    a, b, c = st.columns(3)
    a.metric("Cold cabinets in Back Forty", f"{back} of {len(location_cases)}")
    b.metric("July moves on the map", len(moves))
    c.metric("Warm empty landings", len(held))
    if moves:
        lines = [
            f"- **{item['machine_id']}** {item['theme']}: {item['from_zone']} → {item['to_zone']} ({item['to_location']})"
            for item in moves
        ]
        st.markdown("**Paths drawn**\n" + "\n".join(lines))
    st.write(
        "Gold dots cluster in Back Forty — that is the location call. "
        "July walks three of those cabinets into the open gold rings near the doors and pit."
    )
    chosen = st.session_state.get("machine_pick")
    match = occupied[occupied["machine_id"] == chosen]
    if not match.empty:
        _machine_panel(match.iloc[0])
    else:
        st.caption("Click any cabinet for its cause, coin-in per hour, and theo contribution.")


def _page_proof(forecast, facts, brief, scored) -> None:
    st.subheader("How the model was checked")
    st.write(
        f"Both forecasts were frozen through {forecast['train_end']} ({forecast['n_train']} days) "
        f"and scored from {forecast['test_start']} ({forecast['n_test']} days). "
        "The weekday model is the training mean for that weekday. The baseline is one training mean. "
        "Las Vegas visitation is not a feature."
    )
    test = forecast["daily"]
    test = test[test["split"] == "test"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=test["gaming_date"], y=test["coin_in_usd"], name="Actual", line={"color": "#234f3b", "width": 2}))
    fig.add_trace(go.Scatter(x=test["gaming_date"], y=test["weekday_coin_in"], name="Weekday forecast", line={"color": "#b8975a", "width": 2}))
    fig.add_trace(go.Scatter(x=test["gaming_date"], y=test["baseline_coin_in"], name="Flat mean", line={"color": "#6b7a72", "dash": "dot"}))
    _style(fig, 360)
    _chart(fig)
    st.write(
        f"Weekday error is {_money(forecast['mae_weekday'])}. The flat mean is {_money(forecast['mae_baseline'])}. "
        f"A promotion weekend still has to clear {_money(forecast['promo_hurdle_coin_in'])} of extra coin-in, "
        f"so the forecast keeps the Saturday pattern and leaves the $15,000 unspent."
    )
    with st.expander("Scorecard rules"):
        st.markdown(
            """
            Active days only. Hold and theo per hour are ratios of sums.
            Luck z is house win minus theo, divided by the square root of coin-in times the game's payout variance.

            1. Coverage under half the window, or fewer than 14 days: short tenure.
            2. Luck z at or below −3, with enough coin-in: inspect the payout.
            3. One zone, and coin-in per hour under 80 percent of the same theme elsewhere: location.
            4. Lost theo of $5,000 or more: downtime. On this floor, none clear it.
            5. Theoretical hold of 5.5 percent or less: game mix.
            6. Otherwise a mild negative residual is luck, and the rest are on pace.
            """
        )
    with st.expander("Facts the call sheet is allowed to read"):
        st.caption(f"Source: {brief.get('source', 'template')}")
        st.json(facts)
    export = scored[
        ["machine_id", "theme", "zone_name", "bank_id", "cause", "runner_up", "confidence", "n_days", "house_win", "theo", "luck", "cph", "peer_cph_elsewhere", "luck_z", "availability", "lost_theo"]
    ]
    c1, c2 = st.columns(2)
    c1.download_button("Download facts JSON", json.dumps(facts, indent=2, default=str), "facts.json", "application/json")
    c2.download_button("Download scorecard CSV", export.to_csv(index=False), "scorecard.csv", "text/csv")
    st.caption(
        "Cursor and Grok built the pipeline. DuckDB produces every dollar. "
        "Gemini rewrites the call sheet from this JSON when a key is supplied, and does not query the tables."
    )


def render() -> None:
    _inject_css()
    _init_state()
    start0 = st.session_state["start_date"].isoformat()
    end0 = st.session_state["end_date"].isoformat()
    if start0 > end0:
        start0, end0 = DEFAULT_START, DEFAULT_END
    scored0, _, _, _ = load_floor(start0, end0)
    start, end, zone, bank, api_key = _sidebar(scored0)
    page = st.segmented_control(
        "Page",
        PAGES,
        key="page",
        label_visibility="collapsed",
        required=True,
        width="stretch",
    )
    if start > end:
        st.error("The start date is after the end date.")
        return
    scored, _, plan, spells = load_floor(start, end)
    plan = {**plan, "spells": spells}
    sliced = apply_slice(scored, zone, bank)
    forecast = load_forecast()
    facts = build_facts(scored, sliced, plan, forecast, start, end, zone, bank)
    brief = _brief_for(facts, api_key)
    page = page or "The call"
    if page == "The call":
        _page_call(scored, sliced, plan, spells, facts, brief)
    elif page == "The floor":
        _page_floor(scored, plan, spells, zone, bank, end)
    elif page == "Triage":
        _page_triage(sliced)
    elif page == "Demand":
        _page_demand(forecast, scored, start, end, zone)
    elif page == "Downtime":
        _page_downtime(sliced if zone or bank else scored)
    elif page == "Guests":
        _page_guests()
    else:
        _page_proof(forecast, facts, brief, scored)
