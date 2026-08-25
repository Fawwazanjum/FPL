from fpl_model.analysis.squad_state import SquadState
from fpl_model.config import AppConfig
from fpl_model.optimizer import chips
from fpl_model.optimizer.transfer_optimizer import recommend_transfers
from fpl_model.storage import repository


def _squad_state(chips_available=None, gameweek=1):
    squad = list(range(1, 16))
    sell_prices = {p: 50 for p in squad}
    return SquadState(
        team_id=1, gameweek=gameweek, upcoming_gameweek=gameweek + 1, current_squad=squad,
        starting_xi=squad[:11], bench=squad[11:], captain_id=squad[0], vice_captain_id=squad[1],
        bank_tenths=250, squad_value_tenths=750, free_transfers_available=1,
        chips_available=chips_available if chips_available is not None else ["wildcard", "freehit", "bboost", "3xc"],
        chips_used=[], purchase_prices=sell_prices, sell_prices=sell_prices,
    )


def _positions():
    positions = {}
    for p in (1, 2):
        positions[p] = "GKP"
    for p in (3, 4, 5, 6, 7):
        positions[p] = "DEF"
    for p in (8, 9, 10, 11, 12):
        positions[p] = "MID"
    for p in (13, 14, 15):
        positions[p] = "FWD"
    return positions


def _clubs(ids):
    return {p: p for p in ids}


def _base_prices(squad):
    return {p: 50 for p in squad}


def _strong_replacement_pool():
    """15 candidates (ids 100-114) covering the full position spread, all far
    stronger than the base squad — enough to create a big wildcard-ceiling gap."""
    positions = {}
    for p in (100, 101):
        positions[p] = "GKP"
    for p in (102, 103, 104, 105, 106):
        positions[p] = "DEF"
    for p in (107, 108, 109, 110, 111):
        positions[p] = "MID"
    for p in (112, 113, 114):
        positions[p] = "FWD"
    prices = {p: 50 for p in positions}
    xpts = {p: 20.0 for p in positions}
    return positions, prices, xpts


def test_wildcard_not_recommended_when_gap_small():
    squad_state = _squad_state()
    positions = _positions()
    candidate_ids = squad_state.current_squad
    clubs = _clubs(candidate_ids)
    prices = _base_prices(squad_state.current_squad)
    xpts = {p: 5.0 for p in squad_state.current_squad}
    config = AppConfig(team_id=1)
    rec = recommend_transfers(squad_state, candidate_ids, positions, clubs, prices, xpts, config)

    advice = chips.recommend_wildcard(squad_state, candidate_ids, positions, clubs, prices, xpts, rec, config)
    assert advice.recommended_now is False


def test_wildcard_blocked_by_data_maturity_despite_big_gap():
    squad_state = _squad_state(gameweek=1)  # below min_games_for_wildcard_confidence
    positions = _positions()
    extra_pos, extra_prices, extra_xpts = _strong_replacement_pool()
    candidate_ids = squad_state.current_squad + list(extra_pos.keys())
    positions.update(extra_pos)
    clubs = _clubs(candidate_ids)
    prices = {**_base_prices(squad_state.current_squad), **extra_prices}
    xpts = {p: 2.0 for p in squad_state.current_squad}
    xpts.update(extra_xpts)
    config = AppConfig(team_id=1)
    rec = recommend_transfers(squad_state, candidate_ids, positions, clubs, prices, xpts, config)

    advice = chips.recommend_wildcard(squad_state, candidate_ids, positions, clubs, prices, xpts, rec, config)
    assert advice.recommended_now is False
    assert "gameweek" in advice.reasoning.lower() or "early" in advice.reasoning.lower()


def test_wildcard_recommended_when_gap_big_and_data_mature():
    squad_state = _squad_state(gameweek=5)  # above min_games_for_wildcard_confidence
    positions = _positions()
    extra_pos, extra_prices, extra_xpts = _strong_replacement_pool()
    candidate_ids = squad_state.current_squad + list(extra_pos.keys())
    positions.update(extra_pos)
    clubs = _clubs(candidate_ids)
    prices = {**_base_prices(squad_state.current_squad), **extra_prices}
    xpts = {p: 2.0 for p in squad_state.current_squad}
    xpts.update(extra_xpts)
    config = AppConfig(team_id=1)
    rec = recommend_transfers(squad_state, candidate_ids, positions, clubs, prices, xpts, config)

    advice = chips.recommend_wildcard(squad_state, candidate_ids, positions, clubs, prices, xpts, rec, config)
    assert advice.recommended_now is True


def test_wildcard_unavailable_when_already_used():
    squad_state = _squad_state(chips_available=["freehit", "bboost", "3xc"])
    positions = _positions()
    candidate_ids = squad_state.current_squad
    clubs = _clubs(candidate_ids)
    xpts = {p: 5.0 for p in squad_state.current_squad}
    config = AppConfig(team_id=1)
    rec = recommend_transfers(squad_state, candidate_ids, positions, clubs, {}, xpts, config)

    advice = chips.recommend_wildcard(squad_state, candidate_ids, positions, clubs, {}, xpts, rec, config)
    assert advice.recommended_now is False
    assert "already" in advice.reasoning.lower() or "unavailable" in advice.reasoning.lower()


def _fixture(fixture_id, gw, team_h, team_a):
    return {
        "fixture_id": fixture_id, "gameweek": gw, "kickoff_time": "2026-09-01T13:00:00Z",
        "team_h": team_h, "team_a": team_a, "team_h_difficulty": 3, "team_a_difficulty": 3,
        "team_h_score": None, "team_a_score": None, "finished": 0,
    }


def test_free_hit_recommended_when_enough_starters_blank(conn):
    squad_state = _squad_state()
    positions = _positions()
    # players 1-5 share club 1 (will be blank), players 6-15 have unique clubs with fixtures
    clubs = {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 6, 7: 7, 8: 8, 9: 9, 10: 10, 11: 11, 12: 12, 13: 13, 14: 14, 15: 15}
    # gw2 fixtures cover clubs 6-11 (all in starting_xi) but not club 1
    repository.upsert_fixtures(conn, [
        _fixture(1, 2, 6, 7), _fixture(2, 2, 8, 9), _fixture(3, 2, 10, 11),
    ])
    config = AppConfig(team_id=1)

    advice, blanks = chips.recommend_free_hit(conn, squad_state, positions, clubs, from_gw=2, horizon=1, config=config)
    assert advice.recommended_now is True
    assert advice.best_window_gw == 2


def test_free_hit_not_recommended_when_no_blanks(conn):
    squad_state = _squad_state()
    positions = _positions()
    clubs = _clubs(squad_state.current_squad)
    fixtures = []
    club_ids = list(clubs.values())
    for i in range(0, len(club_ids) - 1, 2):
        fixtures.append(_fixture(i, 2, club_ids[i], club_ids[i + 1]))
    fixtures.append(_fixture(99, 2, club_ids[-1], 999))  # pair the odd one out with an outside club
    repository.upsert_fixtures(conn, fixtures)
    config = AppConfig(team_id=1)

    advice, blanks = chips.recommend_free_hit(conn, squad_state, positions, clubs, from_gw=2, horizon=1, config=config)
    assert advice.recommended_now is False


def test_bench_boost_not_recommended_when_bench_has_no_data(conn):
    squad_state = _squad_state()
    positions = _positions()
    clubs = _clubs(squad_state.current_squad)
    config = AppConfig(team_id=1)

    advice, doubles = chips.recommend_bench_boost(conn, squad_state, positions, clubs, None, None, None, from_gw=2, horizon=1, config=config)
    assert advice.recommended_now is False
    assert doubles == {}


def test_bench_boost_recommended_for_strong_bench_without_double_gameweek(conn):
    """The actual bug this test guards against: bench boost was previously
    NEVER recommended unless a double gameweek existed, even if the bench
    itself was clearly strong on an ordinary single-fixture week."""
    from fpl_model.config import FormWeights
    from fpl_model.data.scoring_rules import ScoringRules

    squad_state = _squad_state()
    clubs = _clubs(squad_state.current_squad)  # bench players 12-15 -> clubs 12-15

    for bench_pid in squad_state.bench:
        repository.upsert_player_snapshots(conn, [_player_snapshot_row(bench_pid, clubs[bench_pid], 3, 90, 1.2, 0.6)])
        repository.upsert_player_gw_history(conn, [_gw_history_row(bench_pid, gw, 90, 1.2, 0.6) for gw in range(1, 4)])
        repository.upsert_fixtures(conn, [
            {"fixture_id": 2000 + bench_pid, "gameweek": 2, "kickoff_time": "2026-09-01T13:00:00Z",
             "team_h": clubs[bench_pid], "team_a": 900 + bench_pid, "team_h_difficulty": 2, "team_a_difficulty": 2,
             "team_h_score": None, "team_a_score": None, "finished": 0},
        ])

    scoring = ScoringRules(
        goals_scored={"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4}, assists=3,
        clean_sheets={"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}, goals_conceded={"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
        defensive_contribution_points={"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
        long_play=2, short_play=1, yellow_cards=-1, red_cards=-3,
    )
    weights = FormWeights()
    team_strength = {clubs[p]: _neutral_team_strength(clubs[p]) for p in squad_state.bench}
    for bench_pid in squad_state.bench:
        team_strength[900 + bench_pid] = _neutral_team_strength(900 + bench_pid)
    positions = _positions()
    config = AppConfig(team_id=1)
    config.chips.bench_boost_min_bench_value = 5.0  # low bar so a genuinely strong (not DGW) bench clears it

    advice, doubles = chips.recommend_bench_boost(conn, squad_state, positions, clubs, scoring, weights, team_strength, from_gw=2, horizon=1, config=config)
    assert advice.recommended_now is True
    assert doubles == {}  # confirms this passed WITHOUT any double gameweek
    assert "no double gameweek needed" in advice.reasoning.lower()


def _player_snapshot_row(player_id, team_id, element_type, minutes, expected_goals, expected_assists):
    return {
        "player_id": player_id, "gameweek": 1, "snapshot_date": "2026-08-25T00:00:00",
        "web_name": f"P{player_id}", "team_id": team_id, "element_type": element_type,
        "now_cost": 50, "selected_by_percent": 5.0, "total_points": 5, "event_points": 5,
        "form": 5.0, "points_per_game": 5.0, "bps": 20, "expected_goals": expected_goals,
        "expected_assists": expected_assists, "expected_goal_involvements": expected_goals + expected_assists,
        "expected_goals_conceded": 1.0, "ict_index": 10.0, "influence": 5.0, "creativity": 5.0, "threat": 5.0,
        "status": "a", "news": None, "chance_of_playing_this_round": None, "chance_of_playing_next_round": None,
        "transfers_in_event": 0, "transfers_out_event": 0, "minutes": minutes,
    }


def _gw_history_row(player_id, gw, minutes, expected_goals, expected_assists):
    return {
        "player_id": player_id, "gameweek": gw, "minutes": minutes, "total_points": 5,
        "goals_scored": 1, "assists": 0, "clean_sheets": 0, "goals_conceded": 1, "bonus": 1, "bps": 20,
        "expected_goals": expected_goals, "expected_assists": expected_assists,
        "expected_goal_involvements": expected_goals + expected_assists, "expected_goals_conceded": 1.0,
        "clearances_blocks_interceptions": 0, "tackles": 0, "recoveries": 0, "defensive_contribution": 0,
        "yellow_cards": 0, "red_cards": 0, "was_home": 1, "opponent_team": 2, "kickoff_time": "2026-08-23T13:00:00Z",
        "value": 50,
    }


def _neutral_team_strength(team_id):
    from fpl_model.analysis.team_strength import TeamStrengthResult

    return TeamStrengthResult(
        team_id=team_id, games_played=3, actual_goals_for=4, actual_goals_against=4,
        attack_xg=4.0, defense_xgc=4.0, attack_overperformance=0.0, defense_overperformance=0.0,
        attack_index=0.0, defense_index=0.0,
    )


def test_triple_captain_recommended_with_strong_double_gameweek_option(conn):
    from fpl_model.config import FormWeights
    from fpl_model.data.scoring_rules import ScoringRules

    squad_state = _squad_state()
    clubs = _clubs(squad_state.current_squad)  # player 1 -> club 1

    # Player 1: strong attacking rate this season, high minutes-reliability, and
    # a double gameweek (two fixtures) at GW3 against weak opponents.
    repository.upsert_player_snapshots(conn, [_player_snapshot_row(1, clubs[1], 3, 90, 1.0, 0.5)])
    repository.upsert_player_gw_history(conn, [_gw_history_row(1, gw, 90, 1.0, 0.5) for gw in range(1, 4)])
    repository.upsert_fixtures(conn, [
        {"fixture_id": 10, "gameweek": 3, "kickoff_time": "2026-09-20T13:00:00Z", "team_h": clubs[1], "team_a": 50,
         "team_h_difficulty": 2, "team_a_difficulty": 2, "team_h_score": None, "team_a_score": None, "finished": 0},
        {"fixture_id": 11, "gameweek": 3, "kickoff_time": "2026-09-23T19:00:00Z", "team_h": 51, "team_a": clubs[1],
         "team_h_difficulty": 2, "team_a_difficulty": 2, "team_h_score": None, "team_a_score": None, "finished": 0},
    ])

    scoring = ScoringRules(
        goals_scored={"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4}, assists=3,
        clean_sheets={"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}, goals_conceded={"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
        defensive_contribution_points={"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
        long_play=2, short_play=1, yellow_cards=-1, red_cards=-3,
    )
    weights = FormWeights()
    team_strength = {clubs[1]: _neutral_team_strength(clubs[1]), 50: _neutral_team_strength(50), 51: _neutral_team_strength(51)}
    doubles = {3: [clubs[1]]}
    config = AppConfig(team_id=1)
    config.chips.triple_captain_uplift_threshold = 0.5  # low bar so the double-fixture uplift clearly clears it

    advice = chips.recommend_triple_captain(conn, squad_state, clubs, normal_week_best_xpts=1.0, double_gameweeks=doubles, scoring=scoring, weights=weights, team_strength=team_strength, config=config)
    assert advice.recommended_now is True
    assert advice.best_window_gw == 3


def test_triple_captain_not_recommended_without_double_gameweek():
    squad_state = _squad_state()
    clubs = _clubs(squad_state.current_squad)
    config = AppConfig(team_id=1)

    advice = chips.recommend_triple_captain(None, squad_state, clubs, 4.0, {}, None, None, None, config)
    assert advice.recommended_now is False
