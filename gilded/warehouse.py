"""DuckDB access. Parquet stays read-only; every dollar figure starts here."""

from __future__ import annotations

import duckdb

from gilded.paths import (
    ACTIONS,
    CALENDAR,
    DAILY,
    GAME_MATH,
    LOCATIONS,
    PLACEMENTS,
    PLAYERS,
    PROPERTY,
)


def connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect()


def _p(path) -> str:
    return path.as_posix().replace("'", "''")


def machine_days(con: duckdb.DuckDBPyConnection, start: str, end: str):
    """Active on-floor machine-days. Pre-install and retired rows stay out."""
    return con.execute(
        f"""
        SELECT
            d.machine_id,
            d.gaming_date,
            d.zone_name,
            d.bank_id,
            d.location_id,
            d.theme,
            d.config_id,
            d.manufacturer,
            d.volatility_class,
            d.lease_class,
            d.configured_rtp,
            d.coin_in_usd,
            d.payout_usd,
            d.house_win_usd,
            d.theo_usd,
            d.luck_residual_usd,
            d.available_hours,
            d.occupied_hours,
            d.carded_coin_in_usd,
            d.faults_opened,
            d.lease_cost_usd,
            d.service_cost_usd,
            d.power_cost_usd,
            d.repair_cost_usd,
            d.contribution_after_supplied_costs_usd,
            c.scheduled_seconds,
            c.local_weekday,
            g.payout_multiplier_variance AS pvar
        FROM read_parquet('{_p(DAILY)}') d
        JOIN read_parquet('{_p(CALENDAR)}') c USING (gaming_date)
        JOIN read_parquet('{_p(GAME_MATH)}') g USING (config_id)
        WHERE d.gaming_date BETWEEN ? AND ?
          AND d.active
          AND d.location_id IS NOT NULL
          AND d.location_id <> ''
        """,
        [start, end],
    ).df()


def machine_totals(con: duckdb.DuckDBPyConnection, start: str, end: str):
    """One row per machine. Rates are ratios of sums, not means of daily rates."""
    return con.execute(
        f"""
        WITH days AS (
            SELECT
                d.*,
                c.scheduled_seconds,
                g.payout_multiplier_variance AS pvar
            FROM read_parquet('{_p(DAILY)}') d
            JOIN read_parquet('{_p(CALENDAR)}') c USING (gaming_date)
            JOIN read_parquet('{_p(GAME_MATH)}') g USING (config_id)
            WHERE d.gaming_date BETWEEN ? AND ?
              AND d.active
              AND d.location_id IS NOT NULL
              AND d.location_id <> ''
        )
        SELECT
            machine_id,
            arg_max(theme, gaming_date) AS theme,
            arg_max(config_id, gaming_date) AS config_id,
            arg_max(manufacturer, gaming_date) AS manufacturer,
            arg_max(volatility_class, gaming_date) AS volatility_class,
            arg_max(lease_class, gaming_date) AS lease_class,
            arg_max(configured_rtp, gaming_date) AS configured_rtp,
            arg_max(zone_name, gaming_date) AS zone_name,
            arg_max(bank_id, gaming_date) AS bank_id,
            arg_max(location_id, gaming_date) AS location_id,
            count(*) AS n_days,
            count(DISTINCT zone_name) AS n_zones,
            sum(coin_in_usd) AS coin_in,
            sum(payout_usd) AS payout,
            sum(house_win_usd) AS house_win,
            sum(theo_usd) AS theo,
            sum(luck_residual_usd) AS luck,
            sum(available_hours) AS avail_h,
            sum(occupied_hours) AS occ_h,
            sum(scheduled_seconds) / 3600.0 AS sched_h,
            sum(carded_coin_in_usd) AS carded_coin_in,
            sum(faults_opened) AS faults,
            sum(lease_cost_usd) AS lease_cost,
            sum(service_cost_usd) AS service_cost,
            sum(power_cost_usd) AS power_cost,
            sum(repair_cost_usd) AS repair_cost,
            sum(contribution_after_supplied_costs_usd) AS contribution,
            sum(theo_usd)
                - sum(lease_cost_usd + service_cost_usd + power_cost_usd + repair_cost_usd)
                AS theo_contribution,
            sum(luck_residual_usd)
                / nullif(sqrt(sum(coin_in_usd * pvar)), 0) AS luck_z
        FROM days
        GROUP BY machine_id
        """,
        [start, end],
    ).df()


def theme_zone_rates(con: duckdb.DuckDBPyConnection, start: str, end: str):
    return con.execute(
        f"""
        SELECT
            d.theme,
            d.zone_name,
            count(DISTINCT d.machine_id) AS machines,
            sum(d.coin_in_usd) AS coin_in,
            sum(d.theo_usd) AS theo,
            sum(d.available_hours) AS avail_h,
            sum(d.coin_in_usd) / nullif(sum(d.available_hours), 0) AS cph,
            sum(d.theo_usd) / nullif(sum(d.coin_in_usd), 0) AS theo_hold
        FROM read_parquet('{_p(DAILY)}') d
        WHERE d.gaming_date BETWEEN ? AND ?
          AND d.active
          AND d.location_id IS NOT NULL
          AND d.location_id <> ''
        GROUP BY 1, 2
        """,
        [start, end],
    ).df()


def property_days(con: duckdb.DuckDBPyConnection):
    return con.execute(
        f"""
        SELECT
            p.*,
            c.scheduled_seconds,
            c.is_weekend,
            c.federal_holiday,
            c.month
        FROM read_parquet('{_p(PROPERTY)}') p
        JOIN read_parquet('{_p(CALENDAR)}') c USING (gaming_date)
        ORDER BY p.gaming_date
        """
    ).df()


def action_catalog(con: duckdb.DuckDBPyConnection):
    return con.execute(
        f"SELECT * FROM read_parquet('{_p(ACTIONS)}')"
    ).df()


def placement_spells(con: duckdb.DuckDBPyConnection):
    """Coin-in per available hour for each placement, for machines that moved."""
    return con.execute(
        f"""
        WITH moved AS (
            SELECT machine_id
            FROM read_parquet('{_p(PLACEMENTS)}')
            GROUP BY 1
            HAVING count(*) > 1
        ),
        spells AS (
            SELECT
                machine_id,
                location_id,
                config_id,
                CAST(effective_from_utc AS TIMESTAMP) AS t0,
                CAST(effective_to_utc AS TIMESTAMP) AS t1
            FROM read_parquet('{_p(PLACEMENTS)}')
            WHERE machine_id IN (SELECT machine_id FROM moved)
        ),
        days AS (
            SELECT
                d.machine_id,
                d.gaming_date,
                d.theme,
                d.zone_name,
                d.location_id,
                d.coin_in_usd,
                d.theo_usd,
                d.house_win_usd,
                d.available_hours,
                c.gaming_day_start_utc
            FROM read_parquet('{_p(DAILY)}') d
            JOIN read_parquet('{_p(CALENDAR)}') c USING (gaming_date)
            WHERE d.active
              AND d.machine_id IN (SELECT machine_id FROM moved)
        )
        SELECT
            d.machine_id,
            any_value(d.theme) AS theme,
            s.location_id,
            any_value(d.zone_name) AS zone_name,
            count(*) AS n_days,
            min(d.gaming_date) AS first_date,
            max(d.gaming_date) AS last_date,
            sum(d.coin_in_usd) / nullif(sum(d.available_hours), 0) AS cph,
            sum(d.theo_usd) / nullif(sum(d.available_hours), 0) AS tph,
            sum(d.house_win_usd) AS house_win
        FROM days d
        JOIN spells s
          ON d.machine_id = s.machine_id
         AND d.gaming_day_start_utc >= s.t0
         AND (s.t1 IS NULL OR d.gaming_day_start_utc < s.t1)
        GROUP BY d.machine_id, s.location_id
        ORDER BY d.machine_id, min(d.gaming_date)
        """
    ).df()


def empty_slots(con: duckdb.DuckDBPyConnection, on_date: str):
    return con.execute(
        f"""
        WITH occupied AS (
            SELECT location_id
            FROM read_parquet('{_p(DAILY)}')
            WHERE gaming_date = ?
              AND active
              AND location_id IS NOT NULL
              AND location_id <> ''
        ),
        zones AS (
            SELECT DISTINCT zone_id, zone_name
            FROM read_parquet('{_p(DAILY)}')
            WHERE zone_name IS NOT NULL AND zone_name <> ''
        )
        SELECT
            s.location_id,
            s.bank_id,
            s.zone_id,
            z.zone_name
        FROM read_parquet('{_p(LOCATIONS)}') s
        LEFT JOIN occupied o USING (location_id)
        LEFT JOIN zones z ON s.zone_id = z.zone_id
        WHERE s.node_type = 'slot'
          AND o.location_id IS NULL
        ORDER BY s.location_id
        """,
        [on_date],
    ).df()


def floor_geometry(con: duckdb.DuckDBPyConnection):
    """Survey positions in meters. Slots, zones, doors, and outlets only."""
    return con.execute(
        f"""
        SELECT
            location_id,
            node_type,
            zone_id,
            bank_id,
            name,
            x_m,
            y_m
        FROM read_parquet('{_p(LOCATIONS)}')
        WHERE node_type IN ('slot', 'zone', 'entrance', 'outlet')
        """
    ).df()


def player_totals(con: duckdb.DuckDBPyConnection):
    return con.execute(
        f"""
        SELECT
            player_id,
            any_value(home_region) AS home_region,
            any_value(age_band) AS age_band,
            arg_max(tier_end, period_month) AS tier_end,
            sum(tracked_coin_in_usd) AS coin_in,
            sum(tracked_payout_usd) AS payout,
            sum(tracked_net_usd) AS player_net,
            sum(theo_usd) AS theo,
            sum(comp_cost_usd) AS comp_cost,
            sum(comp_face_value_usd) AS comp_face,
            sum(tracked_contribution_usd) AS contribution,
            sum(observed_visits) AS visits
        FROM read_parquet('{_p(PLAYERS)}')
        GROUP BY player_id
        """
    ).df()


def player_months(con: duckdb.DuckDBPyConnection):
    return con.execute(
        f"""
        SELECT
            period_month,
            sum(theo_usd) AS theo,
            sum(comp_cost_usd) AS comp_cost,
            sum(tracked_coin_in_usd) AS coin_in,
            sum(tracked_net_usd) AS player_net,
            count(DISTINCT player_id) AS players
        FROM read_parquet('{_p(PLAYERS)}')
        GROUP BY 1
        ORDER BY 1
        """
    ).df()
