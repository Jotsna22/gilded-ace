from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

DAILY = DATA / "1_prepared_views" / "prepared_daily_view.parquet"
PROPERTY = DATA / "1_prepared_views" / "property_day.parquet"
PLAYERS = DATA / "1_prepared_views" / "player_period.parquet"
CALENDAR = DATA / "2_machine_decision" / "calendar_day.parquet"
GAME_MATH = DATA / "2_machine_decision" / "game_math.parquet"
ACTIONS = DATA / "2_machine_decision" / "action_catalog.parquet"
PLACEMENTS = DATA / "2_machine_decision" / "placements.parquet"
LOCATIONS = DATA / "2_machine_decision" / "floor_locations.parquet"
BUDGET_USD = 100_000
HORIZON_DAYS = 30
TRAIN_END = "2025-04-30"
TEST_START = "2025-05-01"
DEFAULT_START = "2025-01-01"
DEFAULT_END = "2025-06-30"
