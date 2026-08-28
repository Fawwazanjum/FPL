CREATE TABLE IF NOT EXISTS teams_snapshots (
    team_id INTEGER NOT NULL,
    gameweek INTEGER NOT NULL,
    name TEXT NOT NULL,
    short_name TEXT NOT NULL,
    strength_overall_home INTEGER,
    strength_overall_away INTEGER,
    strength_attack_home INTEGER,
    strength_attack_away INTEGER,
    strength_defence_home INTEGER,
    strength_defence_away INTEGER,
    snapshot_date TEXT NOT NULL,
    PRIMARY KEY (team_id, gameweek)
);

CREATE TABLE IF NOT EXISTS player_snapshots (
    player_id INTEGER NOT NULL,
    gameweek INTEGER NOT NULL,
    snapshot_date TEXT NOT NULL,
    web_name TEXT NOT NULL,
    team_id INTEGER NOT NULL,
    element_type INTEGER NOT NULL,
    now_cost INTEGER NOT NULL,
    selected_by_percent REAL,
    total_points INTEGER,
    event_points INTEGER,
    form REAL,
    points_per_game REAL,
    bps INTEGER,
    expected_goals REAL,
    expected_assists REAL,
    expected_goal_involvements REAL,
    expected_goals_conceded REAL,
    ict_index REAL,
    influence REAL,
    creativity REAL,
    threat REAL,
    status TEXT,
    news TEXT,
    chance_of_playing_this_round INTEGER,
    chance_of_playing_next_round INTEGER,
    transfers_in_event INTEGER,
    transfers_out_event INTEGER,
    minutes INTEGER,
    PRIMARY KEY (player_id, gameweek)
);

CREATE TABLE IF NOT EXISTS player_gw_history (
    player_id INTEGER NOT NULL,
    gameweek INTEGER NOT NULL,
    minutes INTEGER,
    total_points INTEGER,
    goals_scored INTEGER,
    assists INTEGER,
    clean_sheets INTEGER,
    goals_conceded INTEGER,
    bonus INTEGER,
    bps INTEGER,
    expected_goals REAL,
    expected_assists REAL,
    expected_goal_involvements REAL,
    expected_goals_conceded REAL,
    clearances_blocks_interceptions INTEGER,
    tackles INTEGER,
    recoveries INTEGER,
    defensive_contribution INTEGER,
    yellow_cards INTEGER,
    red_cards INTEGER,
    was_home INTEGER,
    opponent_team INTEGER,
    kickoff_time TEXT,
    value INTEGER,
    PRIMARY KEY (player_id, gameweek)
);

CREATE TABLE IF NOT EXISTS player_history_past (
    player_id INTEGER NOT NULL,
    season_name TEXT NOT NULL,
    total_points INTEGER,
    minutes INTEGER,
    goals_scored INTEGER,
    assists INTEGER,
    clean_sheets INTEGER,
    bps INTEGER,
    expected_goals REAL,
    expected_assists REAL,
    defensive_contribution INTEGER,
    bonus INTEGER,
    PRIMARY KEY (player_id, season_name)
);

CREATE TABLE IF NOT EXISTS fixtures (
    fixture_id INTEGER PRIMARY KEY,
    gameweek INTEGER,
    kickoff_time TEXT,
    team_h INTEGER NOT NULL,
    team_a INTEGER NOT NULL,
    team_h_difficulty INTEGER,
    team_a_difficulty INTEGER,
    team_h_score INTEGER,
    team_a_score INTEGER,
    finished INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS understat_player_map (
    fpl_player_id INTEGER PRIMARY KEY,
    understat_id TEXT,
    match_confidence REAL
);

CREATE TABLE IF NOT EXISTS understat_player_history (
    understat_id TEXT NOT NULL,
    date TEXT NOT NULL,
    xg REAL,
    xa REAL,
    shots INTEGER,
    key_passes INTEGER,
    npxg REAL,
    minutes INTEGER,
    PRIMARY KEY (understat_id, date)
);

CREATE TABLE IF NOT EXISTS manager_history (
    team_id INTEGER NOT NULL,
    gameweek INTEGER NOT NULL,
    points INTEGER,
    total_points INTEGER,
    rank INTEGER,
    overall_rank INTEGER,
    bank INTEGER,
    value INTEGER,
    event_transfers INTEGER,
    event_transfers_cost INTEGER,
    points_on_bench INTEGER,
    PRIMARY KEY (team_id, gameweek)
);

CREATE TABLE IF NOT EXISTS manager_picks (
    team_id INTEGER NOT NULL,
    gameweek INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    squad_position INTEGER,
    multiplier INTEGER,
    is_captain INTEGER NOT NULL DEFAULT 0,
    is_vice_captain INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (team_id, gameweek, player_id)
);

CREATE TABLE IF NOT EXISTS manager_transfers (
    team_id INTEGER NOT NULL,
    event INTEGER NOT NULL,
    time TEXT,
    element_in INTEGER NOT NULL,
    element_in_cost INTEGER,
    element_out INTEGER NOT NULL,
    element_out_cost INTEGER,
    PRIMARY KEY (team_id, event, element_in, element_out)
);

CREATE TABLE IF NOT EXISTS chips_used (
    team_id INTEGER NOT NULL,
    chip_name TEXT NOT NULL,
    event INTEGER NOT NULL,
    PRIMARY KEY (team_id, chip_name, event)
);

CREATE TABLE IF NOT EXISTS league_standings (
    league_id INTEGER NOT NULL,
    league_name TEXT,
    team_id INTEGER NOT NULL,
    entry_name TEXT,
    player_name TEXT,
    rank INTEGER,
    total_points INTEGER,
    snapshot_date TEXT,
    PRIMARY KEY (league_id, team_id)
);

CREATE TABLE IF NOT EXISTS reports_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT NOT NULL,
    gameweek INTEGER,
    file_path TEXT NOT NULL
);
