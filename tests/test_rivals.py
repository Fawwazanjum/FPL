from fpl_model.analysis.rivals import compute_rival_ownership, get_rival_standings
from fpl_model.storage import repository

MY_TEAM_ID = 1000
RIVAL_A = 2000
RIVAL_B = 3000


def _standing_row(league_id, team_id, entry_name, player_name, rank, total_points):
    return {
        "league_id": league_id, "league_name": f"League {league_id}", "team_id": team_id,
        "entry_name": entry_name, "player_name": player_name, "rank": rank,
        "total_points": total_points, "snapshot_date": "2026-08-28T00:00:00",
    }


def _pick_row(team_id, gw, player_id, is_captain=False):
    return {
        "team_id": team_id, "gameweek": gw, "player_id": player_id,
        "squad_position": 1, "multiplier": 2 if is_captain else 1,
        "is_captain": 1 if is_captain else 0, "is_vice_captain": 0,
    }


def test_rival_standings_computes_gap_to_me(conn):
    repository.upsert_league_standings(conn, [
        _standing_row(1, MY_TEAM_ID, "MyTeam", "Me", 1, 150),
        _standing_row(1, RIVAL_A, "RivalTeamA", "Alice", 2, 130),
        _standing_row(1, RIVAL_B, "RivalTeamB", "Bob", 3, 170),
    ])
    standings = get_rival_standings(conn, my_total_points=150)
    by_team = {s.team_id: s for s in standings}
    assert by_team[RIVAL_A].gap_to_me == 20  # I'm ahead by 20
    assert by_team[RIVAL_B].gap_to_me == -20  # Bob is ahead of me by 20
    assert by_team[MY_TEAM_ID].gap_to_me == 0


def test_rival_standings_spans_multiple_leagues(conn):
    repository.upsert_league_standings(conn, [
        _standing_row(1, MY_TEAM_ID, "MyTeam", "Me", 1, 100),
        _standing_row(2, MY_TEAM_ID, "MyTeam", "Me", 4, 100),
        _standing_row(2, RIVAL_A, "RivalTeamA", "Alice", 1, 140),
    ])
    standings = get_rival_standings(conn, my_total_points=100)
    leagues_seen = {s.league_id for s in standings}
    assert leagues_seen == {1, 2}


def test_rival_ownership_counts_only_the_configured_rivals(conn):
    repository.upsert_league_standings(conn, [
        _standing_row(1, MY_TEAM_ID, "MyTeam", "Me", 1, 100),
        _standing_row(1, RIVAL_A, "RivalTeamA", "Alice", 2, 90),
        _standing_row(1, RIVAL_B, "RivalTeamB", "Bob", 3, 80),
    ])
    gw = 1
    repository.upsert_manager_picks(conn, [
        _pick_row(RIVAL_A, gw, 100, is_captain=True),  # Alice owns+captains player 100
        _pick_row(RIVAL_A, gw, 200),
        _pick_row(RIVAL_B, gw, 100),  # Bob owns player 100 too, doesn't captain it
    ])

    ownership = compute_rival_ownership(conn, gw, [100, 200, 300], MY_TEAM_ID)

    assert ownership[100].rivals_owning == 2
    assert ownership[100].rivals_captaining == 1
    assert "RivalTeamA" in ownership[100].captained_by
    assert ownership[100].total_rivals == 2

    assert ownership[200].rivals_owning == 1
    assert ownership[200].rivals_captaining == 0

    assert ownership[300].rivals_owning == 0  # nobody owns this one — a true differential


def test_rival_ownership_empty_when_no_leagues_tracked(conn):
    ownership = compute_rival_ownership(conn, gw=1, player_ids=[100], my_team_id=MY_TEAM_ID)
    assert ownership == {}


def test_same_rival_across_two_leagues_not_double_counted(conn):
    # RivalTeamA is in both leagues (same real person) — should count once,
    # not twice, since ownership is about people, not league memberships.
    repository.upsert_league_standings(conn, [
        _standing_row(1, MY_TEAM_ID, "MyTeam", "Me", 1, 100),
        _standing_row(1, RIVAL_A, "RivalTeamA", "Alice", 2, 90),
        _standing_row(2, MY_TEAM_ID, "MyTeam", "Me", 5, 100),
        _standing_row(2, RIVAL_A, "RivalTeamA", "Alice", 1, 90),
    ])
    gw = 1
    repository.upsert_manager_picks(conn, [_pick_row(RIVAL_A, gw, 100)])

    ownership = compute_rival_ownership(conn, gw, [100], MY_TEAM_ID)
    assert ownership[100].rivals_owning == 1
    assert ownership[100].total_rivals == 1
