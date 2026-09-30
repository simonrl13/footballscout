-- Transfermarkt tables (Kaggle davidcariboo/player-scores). Columns mirror the CSV headers.
-- Rebuilt from scratch on every load.
DROP TABLE IF EXISTS valuation_targets, player_valuations, appearances, games, transfers, players, clubs, competitions;

CREATE TABLE competitions (
    competition_id       text PRIMARY KEY,
    competition_code     text,
    name                 text,
    sub_type             text,
    type                 text,
    country_id           integer,
    country_name         text,
    domestic_league_code text,
    confederation        text,
    total_clubs          integer,
    url                  text
);

-- Club attributes are a CURRENT snapshot (e.g. domestic_competition_id is the league today).
CREATE TABLE clubs (
    club_id                 integer PRIMARY KEY,
    club_code               text,
    name                    text,
    domestic_competition_id text,
    total_market_value      bigint,
    squad_size              integer,
    average_age             real,
    foreigners_number       integer,
    foreigners_percentage   real,
    national_team_players   integer,
    stadium_name            text,
    stadium_seats           integer,
    net_transfer_record     text,
    coach_name              text,
    last_season             integer,
    filename                text,
    url                     text
);

-- Player attributes are a CURRENT snapshot. contract_expiration_date and current_club_* are
-- NOT point-in-time: never use them as features for historical snapshots.
CREATE TABLE players (
    player_id                            integer PRIMARY KEY,
    first_name                           text,
    last_name                            text,
    name                                 text,
    last_season                          integer,
    current_club_id                      integer,
    player_code                          text,
    country_of_birth                     text,
    city_of_birth                        text,
    country_of_citizenship               text,
    date_of_birth                        date,
    sub_position                         text,
    position                             text,
    foot                                 text,
    height_in_cm                         integer,
    contract_expiration_date             date,
    agent_name                           text,
    image_url                            text,
    international_caps                   integer,
    international_goals                  integer,
    current_national_team_id             integer,
    url                                  text,
    current_club_domestic_competition_id text,
    current_club_name                    text,
    market_value_in_eur                  bigint,
    highest_market_value_in_eur          bigint
);

CREATE TABLE games (
    game_id                integer PRIMARY KEY,
    competition_id         text,
    season                 integer,
    round                  text,
    date                   date,
    home_club_id           integer,
    away_club_id           integer,
    home_club_goals        integer,
    away_club_goals        integer,
    home_club_position     integer,
    away_club_position     integer,
    home_club_manager_name text,
    away_club_manager_name text,
    stadium                text,
    attendance             integer,
    referee                text,
    url                    text,
    home_club_formation    text,
    away_club_formation    text,
    home_club_name         text,
    away_club_name         text,
    aggregate              text,
    competition_type       text
);

-- No FK to players: 2 appearance rows reference players missing from players.csv.
CREATE TABLE appearances (
    appearance_id          text PRIMARY KEY,
    game_id                integer NOT NULL,
    player_id              integer NOT NULL,
    player_club_id         integer,
    player_current_club_id integer,
    date                   date NOT NULL,
    player_name            text,
    competition_id         text,
    yellow_cards           smallint,
    red_cards              smallint,
    goals                  smallint,
    assists                smallint,
    minutes_played         smallint
);
CREATE INDEX ON appearances (player_id, date);

-- current_club_id is point-in-time: the club at the valuation date (checked in reports/m1_data.md).
-- player_club_domestic_competition_id is that club's CURRENT league, not the league at `date`: never use it.
CREATE TABLE player_valuations (
    player_id                           integer NOT NULL,
    date                                date NOT NULL,
    market_value_in_eur                 bigint NOT NULL,
    current_club_name                   text,
    current_club_id                     integer,
    player_club_domestic_competition_id text,
    PRIMARY KEY (player_id, date)
);

-- Contains dates after the data snapshot (up to 2030): likely planned moves / loan ends.
CREATE TABLE transfers (
    player_id           integer NOT NULL,
    transfer_date       date,
    transfer_season     text,
    from_club_id        integer,
    to_club_id          integer,
    from_club_name      text,
    to_club_name        text,
    transfer_fee        numeric,
    market_value_in_eur numeric,
    player_name         text
);
CREATE INDEX ON transfers (player_id, transfer_date);
