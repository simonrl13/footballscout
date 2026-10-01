"""Read the raw Kaggle CSVs (after checking them against data/manifest.json)."""
import pandas as pd

from scout.data.manifest import RAW, verify


def read_raw(check_manifest: bool = True) -> dict[str, pd.DataFrame]:
    if check_manifest:
        verify()
    games = pd.read_csv(RAW / "games.csv", parse_dates=["date"],
                        usecols=["game_id", "season", "date", "competition_id", "competition_type", "home_club_id",
                                 "away_club_id", "home_club_goals", "away_club_goals"])
    apps = pd.read_csv(RAW / "appearances.csv", parse_dates=["date"],
                       usecols=["game_id", "player_id", "player_club_id", "date", "competition_id", "minutes_played",
                                "goals", "assists", "yellow_cards", "red_cards"])
    return {
        # position is the player's current value (rarely changes); date_of_birth is static
        "players": pd.read_csv(RAW / "players.csv", parse_dates=["date_of_birth"],
                               usecols=["player_id", "name", "date_of_birth", "position", "sub_position"]),
        "valuations": pd.read_csv(RAW / "player_valuations.csv", parse_dates=["date"],
                                  usecols=["player_id", "date", "market_value_in_eur", "current_club_id"]),  # club at the valuation date
        "transfers": pd.read_csv(RAW / "transfers.csv", parse_dates=["transfer_date"],
                                 usecols=["player_id", "transfer_date", "from_club_id", "to_club_id"])
                       .rename(columns={"transfer_date": "date"}),
        "appearances": apps.merge(games[["game_id", "season"]], on="game_id", how="left"),
        "games": games,
        # match-day squads (starting XI + bench) and in-match events, for the stats feature pass
        "lineups": pd.read_csv(RAW / "game_lineups.csv", usecols=["game_id", "player_id", "club_id"]),
        "events": pd.read_csv(RAW / "game_events.csv", usecols=["game_id", "type", "player_id", "description"])
                    .query("type == 'Substitutions'").drop(columns="type"),
    }
