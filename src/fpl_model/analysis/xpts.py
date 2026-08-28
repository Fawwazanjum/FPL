"""Position-aware expected-points model. Each player's xPts is built from
separately-weighted components (attacking return, clean sheet, DEFCON, bonus,
conceded penalty, card risk) rather than one blended number, so a defender who
racks up defensive actions is compared on the right axis against a defender who
doesn't, and both are compared correctly against attackers. See constants in
data/scoring_rules.py for the live, position-keyed point values driving this.

The appearance-probability and clean-sheet-probability pieces below are
deliberately simple heuristics (not a calibrated Poisson goal model) — a
reasonable first pass for a personal tool, easy to refine later without
changing the surrounding architecture.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass

from fpl_model.analysis.rate_blend import blend_rate, multi_season_prior_rate
from fpl_model.analysis.team_strength import TeamStrengthResult
from fpl_model.config import AppConfig, FormWeights
from fpl_model.constants import DEFCON_TRACKED_SEASON_LABELS, ELEMENT_TYPE_ID_TO_POSITION
from fpl_model.data.scoring_rules import DEFCON_THRESHOLD, ScoringRules
from fpl_model.report.news_overrides import NewsOverride
from fpl_model.storage import repository

CLEAN_SHEET_BASE_RATE = 0.30
CLEAN_SHEET_INDEX_SENSITIVITY = 0.12
CLEAN_SHEET_MIN, CLEAN_SHEET_MAX = 0.03, 0.75
CONCEDED_INDEX_SENSITIVITY = 0.15
# Weight given to FPL's own home/away strength ratings (team_strength.py's
# attack/defense_index_home/away) relative to this season's live xG-based
# index when scoring a specific fixture. Kept below 1.0 deliberately: the
# live index is the more direct signal once there's enough of a sample, this
# is a venue-context adjustment on top of it, not a replacement for it.
HOME_AWAY_INDEX_WEIGHT = 0.4
# Attacking-side opponent/venue adjustment (see memory: fpl-model-project —
# previously attacking_rate had NO opponent adjustment at all, only the
# defensive side did). Two effects, both using the same real underlying
# attack/defense indices as the clean-sheet calc above, not a flat
# home-good/away-bad or "big club" label:
#   - opponent's defense: weaker opponent defense -> higher expected output
#   - own team's attacking form: our team creating well right now -> a bit
#     more expected output for this player specifically
# The own-team-form term is deliberately weaker than the opponent term: a
# player's own attacking_rate already partly reflects their team's attacking
# context over the games it was measured on, so weighting it too heavily here
# risks double-counting the same signal twice.
ATTACK_OPPONENT_DEFENSE_SENSITIVITY = 0.15
ATTACK_OWN_TEAM_FORM_SENSITIVITY = 0.08
ATTACK_MULTIPLIER_MIN, ATTACK_MULTIPLIER_MAX = 0.5, 1.8
MIN_MINUTES_FACTOR = 0.15
SEASON_GAMES = 38
DOUBTFUL_DEFAULT_CHANCE = 0.5
# Below this, net gameweek transfer activity isn't worth mentioning — informational
# only (see memory: fpl-model-project), it never touches `total`, so this only
# affects whether a reasoning line gets printed, not any score.
TRANSFER_MOMENTUM_NOTABLE_THRESHOLD = 50_000
# A manager quote/observed tactical change is a real, immediate signal (see
# memory: fpl-model-project, the Guéhi discussion) — modest by design, this
# nudges the attacking rate rather than overriding the statistical estimate.
ROLE_DIRECTION_ATTACK_MULTIPLIER = {"more_attacking": 1.15, "more_defensive": 0.85}


@dataclass
class XptsBreakdown:
    player_id: int
    gameweek: int
    opponent_team_id: int | None
    is_home: bool | None
    num_fixtures: int
    p_full_involvement: float
    appearance_pts: float
    attacking_pts: float
    clean_sheet_pts: float
    clean_sheet_prob: float
    defcon_pts: float
    defcon_hit_rate: float
    defcon_per90: float
    conceded_penalty: float
    bonus_pts: float
    card_penalty: float
    total: float
    reasoning: str
    transfers_in_event: int
    transfers_out_event: int


def _attacking_points_rate_for_season(row: sqlite3.Row, position: str, scoring: ScoringRules) -> float:
    # Prefer underlying xG/xA over actual goals/assists — actual output is
    # already the converted (lucky-or-unlucky) result; using it as a prior
    # anchor means a player who overperformed starts overrated, and one who
    # created well but finished poorly starts underrated. xG/xA is the more
    # mean-reverting signal, which is the whole point of a prior. Falls back
    # to actual goals/assists only for a row that predates this column
    # (pre-migration player_history_past rows with NULLs there).
    if row["expected_goals"] is not None or row["expected_assists"] is not None:
        xg = row["expected_goals"] or 0.0
        xa = row["expected_assists"] or 0.0
    else:
        xg = row["goals_scored"] or 0
        xa = row["assists"] or 0
    return scoring.attacking_points(position, xg, xa) / (row["minutes"] / 90)


def _attacking_rate_per90(
    conn: sqlite3.Connection,
    player_id: int,
    position: str,
    scoring: ScoringRules,
    weights: FormWeights,
    history_past_seasons: dict[str, sqlite3.Row],
) -> tuple[float, int]:
    last_rate = multi_season_prior_rate(
        history_past_seasons, lambda row: _attacking_points_rate_for_season(row, position, scoring)
    )
    last_rate = last_rate if last_rate is not None else 0.0

    snap = repository.get_latest_snapshot_for_player(conn, player_id)
    if snap is not None and (snap["minutes"] or 0) > 0:
        season_rate = scoring.attacking_points(position, snap["expected_goals"] or 0.0, snap["expected_assists"] or 0.0) / (
            snap["minutes"] / 90
        )
    else:
        season_rate = 0.0

    all_rows = repository.get_player_gw_history_all(conn, player_id)
    played_rows = [r for r in all_rows if (r["minutes"] or 0) > 0]
    n = len(played_rows)
    recent_rows = played_rows[-6:]
    recent_minutes = sum((r["minutes"] or 0) for r in recent_rows)
    recent_points = sum(
        scoring.attacking_points(position, r["expected_goals"] or 0.0, r["expected_assists"] or 0.0) for r in recent_rows
    )
    recent_rate = recent_points / (recent_minutes / 90) if recent_minutes > 0 else 0.0

    blend = blend_rate(last_rate, season_rate, recent_rate, n, weights)
    return blend.blended_rate, n


def _bonus_rate_per90(
    conn: sqlite3.Connection,
    player_id: int,
    weights: FormWeights,
    history_past_seasons: dict[str, sqlite3.Row],
    n: int,
) -> float:
    # player_history_past now stores a season-total 'bonus' column (it didn't
    # for the first version of this fix — caught as a leftover gap, see
    # memory: fpl-model-project), so this gets the same multi-season prior
    # treatment as attacking rate instead of defaulting to a neutral 0.
    last_rate = multi_season_prior_rate(
        history_past_seasons, lambda row: (row["bonus"] or 0) / (row["minutes"] / 90)
    )
    last_rate = last_rate if last_rate is not None else 0.0

    all_rows = repository.get_player_gw_history_all(conn, player_id)
    played_rows = [r for r in all_rows if (r["minutes"] or 0) > 0]
    season_minutes = sum((r["minutes"] or 0) for r in played_rows)
    season_bonus = sum((r["bonus"] or 0) for r in played_rows)
    season_rate = season_bonus / (season_minutes / 90) if season_minutes > 0 else 0.0

    recent_rows = played_rows[-6:]
    recent_minutes = sum((r["minutes"] or 0) for r in recent_rows)
    recent_bonus = sum((r["bonus"] or 0) for r in recent_rows)
    recent_rate = recent_bonus / (recent_minutes / 90) if recent_minutes > 0 else 0.0

    blend = blend_rate(last_rate, season_rate, recent_rate, n, weights)
    return blend.blended_rate


def _defcon_rate_per90(
    conn: sqlite3.Connection,
    player_id: int,
    history_past_seasons: dict[str, sqlite3.Row],
    weights: FormWeights,
) -> tuple[float, int]:
    """Blended DEFCON actions-per-90, multi-season prior / this season / recent —
    same purple-patch discipline as attacking rate, and now the SAME KIND of
    quantity throughout the blend (a rate), not a rate-proxy for one leg and
    an actual measured frequency for another. That mixing was the root cause
    of a labeling bug a user caught: the old version derived a last-season
    component by comparing a season AVERAGE against the per-game threshold
    and calling the result a 'hit rate' alongside a genuinely-measured
    this-season hit frequency — an average clearing the bar doesn't mean the
    player cleared it in literally every match. Blending the raw rate here
    instead sidesteps that entirely; converting rate -> hit probability
    happens once, in one place (_poisson_p_at_least), from a single clean
    number. This is also the number worth showing directly to compare two
    players' defensive output — see PlayerXptsOut.defcon_per90.

    Deliberately restricted to DEFCON_TRACKED_SEASON_LABELS, not the full
    multi-season window every other rate here uses — DEFCON is a newer FPL
    scoring category, and blending in a season before it existed would mean
    treating "not tracked that year" as "recorded zero defensive actions all
    season," dragging every veteran's prior down. Verified directly against
    the data before this shipped, see constants.py for the check."""
    tracked_seasons = {
        season: row for season, row in history_past_seasons.items() if season in DEFCON_TRACKED_SEASON_LABELS
    }
    last_rate = multi_season_prior_rate(
        tracked_seasons,
        lambda row: (row["defensive_contribution"] or 0) / (row["minutes"] / 90),
    )
    last_rate = last_rate if last_rate is not None else 0.0

    all_rows = repository.get_player_gw_history_all(conn, player_id)
    played_rows = [r for r in all_rows if (r["minutes"] or 0) > 0]
    n = len(played_rows)
    season_minutes = sum((r["minutes"] or 0) for r in played_rows)
    season_dc = sum((r["defensive_contribution"] or 0) for r in played_rows)
    season_rate = season_dc / (season_minutes / 90) if season_minutes > 0 else 0.0

    recent_rows = played_rows[-6:]
    recent_minutes = sum((r["minutes"] or 0) for r in recent_rows)
    recent_dc = sum((r["defensive_contribution"] or 0) for r in recent_rows)
    recent_rate = recent_dc / (recent_minutes / 90) if recent_minutes > 0 else 0.0

    blend = blend_rate(last_rate, season_rate, recent_rate, n, weights)
    return blend.blended_rate, n


def _poisson_p_at_least(mu: float, k: int) -> float:
    """P(X >= k) for X ~ Poisson(mu) — the actual quantity FPL's DEFCON bonus
    pays out on (clear a fixed per-match action count, or don't; no partial
    credit), converted from a single per-90 rate rather than an ad-hoc cap.
    Poisson is a standard, defensible model for a per-match count stat like
    this; not fitted/validated against real DEFCON distributions, so treat as
    a reasonable default rather than a calibrated model."""
    if mu <= 0 or k <= 0:
        return 0.0 if mu <= 0 else 1.0
    p_less_than_k = 0.0
    term = math.exp(-mu)  # P(X = 0)
    p_less_than_k += term
    for i in range(1, k):
        term *= mu / i  # P(X = i) from P(X = i-1)
        p_less_than_k += term
    return max(0.0, min(1.0, 1.0 - p_less_than_k))


ROLE_SHIFT_MIN_GAMES = 4
ROLE_SHIFT_ATTACK_DROP_RATIO = 0.5
ROLE_SHIFT_ATTACK_RISE_RATIO = 1.8
ROLE_SHIFT_DEFENSIVE_RISE_RATIO = 1.3
ROLE_SHIFT_MIN_EARLIER_ATTACK = 0.5


def _detect_role_shift(conn: sqlite3.Connection, player_id: int, position: str, scoring: ScoringRules) -> str | None:
    """Flags a likely change in tactical role (e.g. a midfielder now being played
    deeper/more defensively, or a defender pushed further forward) by comparing
    a player's own recent underlying numbers against their own earlier-season
    baseline — not a generic position assumption. Needs a handful of games on
    both sides of the split to say anything; returns None otherwise (which is
    expected/normal early in a season)."""
    all_rows = repository.get_player_gw_history_all(conn, player_id)
    played_rows = [r for r in all_rows if (r["minutes"] or 0) > 0]
    if len(played_rows) < ROLE_SHIFT_MIN_GAMES:
        return None

    split = max(1, len(played_rows) // 2)
    earlier_rows, recent_rows = played_rows[:-split], played_rows[-split:]
    if not earlier_rows or not recent_rows:
        return None

    def _rate(rows, key_fn):
        minutes = sum((r["minutes"] or 0) for r in rows)
        if minutes <= 0:
            return 0.0
        return sum(key_fn(r) for r in rows) / (minutes / 90)

    earlier_attack = _rate(earlier_rows, lambda r: scoring.attacking_points(position, r["expected_goals"] or 0.0, r["expected_assists"] or 0.0))
    recent_attack = _rate(recent_rows, lambda r: scoring.attacking_points(position, r["expected_goals"] or 0.0, r["expected_assists"] or 0.0))
    earlier_def = _rate(earlier_rows, lambda r: r["defensive_contribution"] or 0)
    recent_def = _rate(recent_rows, lambda r: r["defensive_contribution"] or 0)

    if earlier_attack >= ROLE_SHIFT_MIN_EARLIER_ATTACK and recent_attack < earlier_attack * ROLE_SHIFT_ATTACK_DROP_RATIO and (
        earlier_def == 0 or recent_def > earlier_def * ROLE_SHIFT_DEFENSIVE_RISE_RATIO
    ):
        return "attacking output down / defensive actions up vs own earlier-season baseline — possible deeper role, check team news"
    if recent_attack > 0.5 and earlier_attack > 0 and recent_attack > earlier_attack * ROLE_SHIFT_ATTACK_RISE_RATIO:
        return "attacking output up vs own earlier-season baseline — possible more advanced role"
    return None


def _card_rate_per90(conn: sqlite3.Connection, player_id: int, scoring: ScoringRules) -> float:
    all_rows = repository.get_player_gw_history_all(conn, player_id)
    played_rows = [r for r in all_rows if (r["minutes"] or 0) > 0]
    minutes = sum((r["minutes"] or 0) for r in played_rows)
    if minutes <= 0:
        return 0.0
    points = sum(
        (r["yellow_cards"] or 0) * scoring.yellow_cards + (r["red_cards"] or 0) * scoring.red_cards for r in played_rows
    )
    return points / (minutes / 90)


# Accumulated-booking suspension thresholds -> ban length in matches (FA
# disciplinary rule for English domestic competitions). Not exposed anywhere
# in FPL's API — hardcoded the same way DEFCON_THRESHOLD is, for the same
# reason (documented external rule, not derived data); flagged here so a
# future rule change is easy to find. The exact cutoff GAMEWEEK each
# threshold applies by shifts slightly season to season and isn't modeled —
# this is "you're one booking from a ban," not a per-gameweek probability.
SUSPENSION_THRESHOLDS = {5: 1, 10: 2, 15: 3}


def _suspension_risk_note(conn: sqlite3.Connection, player_id: int) -> str | None:
    all_rows = repository.get_player_gw_history_all(conn, player_id)
    total_yellows = sum((r["yellow_cards"] or 0) for r in all_rows)
    for threshold, ban_matches in SUSPENSION_THRESHOLDS.items():
        if total_yellows == threshold - 1:
            return (
                f"{total_yellows} yellow cards this season — next booking triggers a "
                f"{ban_matches}-match suspension (accumulation threshold {threshold})"
            )
    return None


def _minutes_reliability(
    conn: sqlite3.Connection,
    player_id: int,
    history_past_seasons: dict[str, sqlite3.Row],
    weights: FormWeights,
) -> tuple[float, int]:
    """Blended share (0-1) of available team minutes this player actually plays —
    a multi-season prior, this-season-to-date, and recent, blended with the
    same purple-patch/blip weighting used for scoring rates (form.py /
    rate_blend.py), just applied to playing time instead of points.

    This is a real (if imperfect) proxy for pecking-order/rotation risk: a
    player who's genuinely dropped below new signings or in-form teammates
    shows it here as a declining minutes-share trend over the coming
    gameweeks, rather than the model overreacting to a single early cameo.

    Pulling from up to 3 seasons rather than 1 also directly softens the
    single worst failure mode this had (see memory: fpl-model-project, the
    Mosquera case): a player whose ONE most-recent season happened to be a
    squad-rotation year no longer single-handedly anchors the prior — a
    genuinely nailed player with one down year mixed among better ones reads
    closer to their real pecking order, not their worst recent season.
    """
    # One row per gameweek the player's team played, minutes=0 if unused — this
    # is exactly the signal needed (unlike attacking/bonus rates, which only
    # look at played_rows since a 0-minute game can't have a scoring rate).
    all_rows = repository.get_player_gw_history_all(conn, player_id)
    n_team_games = len(all_rows)
    season_share = sum((r["minutes"] or 0) for r in all_rows) / (n_team_games * 90) if n_team_games > 0 else 0.0

    last_share = multi_season_prior_rate(
        history_past_seasons, lambda row: min(1.0, row["minutes"] / (SEASON_GAMES * 90))
    )
    if last_share is None:
        # No last-season data (promoted/new signing/transfer in) — fall back to
        # this season's own share rather than a punitive 0, which would wrongly
        # drag down a player who's actually nailed on but has no history yet.
        last_share = season_share

    recent_rows = all_rows[-4:]
    recent_share = sum((r["minutes"] or 0) for r in recent_rows) / (len(recent_rows) * 90) if recent_rows else season_share

    blend = blend_rate(last_share, season_share, recent_share, n_team_games, weights)
    return max(MIN_MINUTES_FACTOR, min(1.0, blend.blended_rate)), n_team_games


def _clean_sheet_probability(own_defense_index: float, opp_attack_index: float) -> float:
    p = CLEAN_SHEET_BASE_RATE + CLEAN_SHEET_INDEX_SENSITIVITY * (own_defense_index - opp_attack_index)
    return max(CLEAN_SHEET_MIN, min(CLEAN_SHEET_MAX, p))


def _expected_conceded_this_fixture(team_strength: TeamStrengthResult, opp_attack_index: float, team_games: int) -> float:
    per_game_xgc = team_strength.defense_xgc / team_games if team_games > 0 else team_strength.defense_xgc
    adjusted = per_game_xgc * (1 + CONCEDED_INDEX_SENSITIVITY * opp_attack_index)
    return max(0.2, min(4.0, adjusted))


def compute_player_xpts_gw(
    conn: sqlite3.Connection,
    player_id: int,
    gameweek: int,
    scoring: ScoringRules,
    weights: FormWeights,
    team_strength: dict[int, TeamStrengthResult],
    news_override: NewsOverride | None = None,
) -> XptsBreakdown | None:
    from fpl_model.constants import RECENT_SEASON_LABELS

    snap = repository.get_latest_snapshot_for_player(conn, player_id)
    if snap is None:
        return None
    position = ELEMENT_TYPE_ID_TO_POSITION.get(snap["element_type"], "MID")
    team_id = snap["team_id"]

    history_past_seasons = repository.get_player_history_past_seasons(conn, player_id, RECENT_SEASON_LABELS)
    attacking_rate, n = _attacking_rate_per90(conn, player_id, position, scoring, weights, history_past_seasons)
    bonus_rate = _bonus_rate_per90(conn, player_id, weights, history_past_seasons, n)
    defcon_per90, _ = _defcon_rate_per90(conn, player_id, history_past_seasons, weights)
    defcon_threshold = DEFCON_THRESHOLD.get(position)
    defcon_rate = _poisson_p_at_least(defcon_per90, defcon_threshold) if defcon_threshold else 0.0
    card_rate = _card_rate_per90(conn, player_id, scoring)

    news_reasoning: list[str] = []
    if news_override is not None and news_override.role_direction in ROLE_DIRECTION_ATTACK_MULTIPLIER:
        attacking_rate *= ROLE_DIRECTION_ATTACK_MULTIPLIER[news_override.role_direction]
    if news_override is not None and news_override.role_note:
        news_reasoning.append(f"NEWS: {news_override.role_note}")
    if news_override is not None and news_override.set_piece_note:
        news_reasoning.append(f"NEWS (set-piece): {news_override.set_piece_note}")

    minutes_factor, n_team_games = _minutes_reliability(conn, player_id, history_past_seasons, weights)
    chance = snap["chance_of_playing_next_round"]
    p_available = 1.0 if chance is None else max(0.0, min(1.0, chance / 100))
    if news_override is not None:
        if news_override.status == "out":
            p_available = 0.0
            news_reasoning.append(f"NEWS: ruled OUT{f' ({news_override.note})' if news_override.note else ''}")
        elif news_override.chance_of_playing_override is not None:
            p_available = max(0.0, min(1.0, news_override.chance_of_playing_override / 100))
            news_reasoning.append(f"NEWS: {p_available:.0%} chance of playing{f' ({news_override.note})' if news_override.note else ''}")
        elif news_override.status == "doubtful":
            p_available = DOUBTFUL_DEFAULT_CHANCE
            news_reasoning.append(f"NEWS: doubtful{f' ({news_override.note})' if news_override.note else ''}")
    p_full = p_available * minutes_factor

    # Loop over ALL of the team's fixtures this gameweek, not just the first —
    # a blank gameweek (0 fixtures) must zero everything out, and a double
    # gameweek (2 fixtures) must count for roughly double, both of which
    # matter a lot for Bench Boost/Triple Captain (Phase 4) even though a
    # normal single-fixture week is by far the common case.
    fixtures = repository.get_fixtures_for_team_gw(conn, team_id, gameweek)
    num_fixtures = len(fixtures)
    opponent_id: int | None = None
    is_home: bool | None = None
    expected_clean_sheets = 0.0  # sum of per-fixture clean-sheet probabilities
    conceded_penalty = 0.0
    attacking_pts_full90 = 0.0  # sum of per-fixture opponent/venue-adjusted attacking output
    reasoning_parts = []
    fixture_descriptions = []

    if fixtures and team_id in team_strength:
        own_strength = team_strength[team_id]
        team_games = max(1, len(repository.get_finished_fixtures(conn)) // 10)  # rough per-team game count proxy
        for i, fx in enumerate(fixtures):
            fx_is_home = fx["team_h"] == team_id
            fx_opponent = fx["team_a"] if fx_is_home else fx["team_h"]
            if i == 0:
                is_home, opponent_id = fx_is_home, fx_opponent
            opp_strength = team_strength.get(fx_opponent)
            opp_attack_index = opp_strength.attack_index if opp_strength else 0.0
            # Venue-adjusted terms: our defense uses its home rating when we're
            # at home (away rating otherwise); the opponent's attack uses the
            # opposite venue from theirs, since they're playing the away leg
            # of this fixture when we're at home, and vice versa.
            own_defense_venue = own_strength.defense_index_home if fx_is_home else own_strength.defense_index_away
            opp_attack_venue = opp_strength.attack_index_away if (opp_strength and fx_is_home) else (
                opp_strength.attack_index_home if opp_strength else 0.0
            )
            own_defense_adj = own_strength.defense_index + HOME_AWAY_INDEX_WEIGHT * own_defense_venue
            opp_attack_adj = opp_attack_index + HOME_AWAY_INDEX_WEIGHT * opp_attack_venue
            cs_prob = _clean_sheet_probability(own_defense_adj, opp_attack_adj)
            expected_clean_sheets += cs_prob
            expected_conceded = _expected_conceded_this_fixture(own_strength, opp_attack_adj, team_games)
            conceded_penalty += scoring.goals_conceded.get(position, 0) * (expected_conceded / 2)

            # Attacking side: same underlying indices, mirrored — a player's
            # expected attacking output rises against a weaker opponent
            # defense and when their own team is creating well right now, both
            # venue-adjusted the same way as above. Real underlying numbers per
            # team/fixture, not a categorical "away form" or "big club" label.
            opp_defense_index = opp_strength.defense_index if opp_strength else 0.0
            opp_defense_venue = opp_strength.defense_index_away if (opp_strength and fx_is_home) else (
                opp_strength.defense_index_home if opp_strength else 0.0
            )
            opp_defense_adj = opp_defense_index + HOME_AWAY_INDEX_WEIGHT * opp_defense_venue
            own_attack_venue = own_strength.attack_index_home if fx_is_home else own_strength.attack_index_away
            own_attack_adj = own_strength.attack_index + HOME_AWAY_INDEX_WEIGHT * own_attack_venue
            attack_multiplier = (
                1.0
                - ATTACK_OPPONENT_DEFENSE_SENSITIVITY * opp_defense_adj
                + ATTACK_OWN_TEAM_FORM_SENSITIVITY * own_attack_adj
            )
            attack_multiplier = max(ATTACK_MULTIPLIER_MIN, min(ATTACK_MULTIPLIER_MAX, attack_multiplier))
            attacking_pts_full90 += attacking_rate * attack_multiplier

            fixture_descriptions.append(
                f"vs team {fx_opponent} ({'H' if fx_is_home else 'A'}, CS prob {cs_prob:.0%}, attack x{attack_multiplier:.2f})"
            )
        if num_fixtures > 1:
            reasoning_parts.append(f"DOUBLE GAMEWEEK: {'; '.join(fixture_descriptions)}")
        else:
            reasoning_parts.append(fixture_descriptions[0])
    else:
        reasoning_parts.append("no fixture found for this gameweek (blank)")

    # Appearance-scaled components multiply by num_fixtures (0 for a blank
    # gameweek correctly zeroes everything; 2 for a double gameweek assumes
    # the player features in both, weighted by the same involvement estimate).
    # attacking_pts_full90 is NOT included here — it's already accumulated
    # per-fixture above (with its own per-fixture opponent adjustment), which
    # both handles blanks/doubles correctly and, as a bonus, means a double
    # gameweek now properly uses two different opponent adjustments instead of
    # doubling one flat rate.
    appearance_pts = num_fixtures * p_available * (minutes_factor * scoring.long_play + (1 - minutes_factor) * scoring.short_play)
    clean_sheet_pts = scoring.clean_sheets.get(position, 0) * expected_clean_sheets
    defcon_pts = scoring.defensive_contribution_points.get(position, 0) * defcon_rate * num_fixtures
    bonus_rate_total = bonus_rate * num_fixtures
    card_rate_total = card_rate * num_fixtures

    total = appearance_pts + p_full * (
        attacking_pts_full90 + clean_sheet_pts + defcon_pts + conceded_penalty + bonus_rate_total + card_rate_total
    )

    if attacking_pts_full90 > 1.0:
        reasoning_parts.append(f"strong attacking rate ({attacking_rate:.2f} pts/90)")
    if defcon_pts > 0.3:
        # Lead with the raw per-90 rate — the directly comparable number
        # between two players — then the derived probability, clearly framed
        # as an estimate rather than a measured frequency. Position-relative
        # percentile isn't available here (needs the full player pool, which
        # this function doesn't see) — that's attached separately in
        # report/writer.py as PlayerXptsOut.defcon_percentile.
        reasoning_parts.append(f"DEFCON {defcon_per90:.1f}/90 (~{defcon_rate:.0%} est. chance of clearing the bar)")
    role_shift = _detect_role_shift(conn, player_id, position, scoring)
    if role_shift:
        reasoning_parts.append(role_shift)
    if p_full < 0.5:
        reasoning_parts.append(f"rotation/fitness risk (minutes-share {minutes_factor:.0%}, n={n_team_games} GW)")
    suspension_risk = _suspension_risk_note(conn, player_id)
    if suspension_risk:
        reasoning_parts.append(suspension_risk)

    transfers_in_event = snap["transfers_in_event"] or 0
    transfers_out_event = snap["transfers_out_event"] or 0
    net_transfers = transfers_in_event - transfers_out_event
    if abs(net_transfers) >= TRANSFER_MOMENTUM_NOTABLE_THRESHOLD:
        direction = "IN" if net_transfers > 0 else "OUT"
        reasoning_parts.append(
            f"transfer momentum: {abs(net_transfers):,} net {direction} this GW (informational only — not a scoring input)"
        )
    reasoning_parts.extend(news_reasoning)

    return XptsBreakdown(
        player_id=player_id,
        gameweek=gameweek,
        opponent_team_id=opponent_id,
        is_home=is_home,
        num_fixtures=num_fixtures,
        p_full_involvement=p_full,
        appearance_pts=appearance_pts,
        attacking_pts=p_full * attacking_pts_full90,
        clean_sheet_pts=p_full * clean_sheet_pts,
        clean_sheet_prob=expected_clean_sheets,
        defcon_pts=p_full * defcon_pts,
        defcon_hit_rate=defcon_rate,
        defcon_per90=defcon_per90,
        conceded_penalty=p_full * conceded_penalty,
        bonus_pts=p_full * bonus_rate_total,
        card_penalty=p_full * card_rate_total,
        total=total,
        reasoning="; ".join(reasoning_parts),
        transfers_in_event=transfers_in_event,
        transfers_out_event=transfers_out_event,
    )


def compute_horizon_xpts(
    conn: sqlite3.Connection,
    player_id: int,
    from_gw: int,
    horizon: int,
    decay: float,
    scoring: ScoringRules,
    weights: FormWeights,
    team_strength: dict[int, TeamStrengthResult],
    news_override: NewsOverride | None = None,
) -> float:
    total = 0.0
    for i in range(horizon):
        gw = from_gw + i
        result = compute_player_xpts_gw(conn, player_id, gw, scoring, weights, team_strength, news_override)
        if result is not None:
            total += result.total * (decay**i)
    return total


def compute_all(
    conn: sqlite3.Connection,
    player_ids: list[int],
    gameweek: int,
    config: AppConfig,
    scoring: ScoringRules,
    team_strength: dict[int, TeamStrengthResult],
    news_overrides: dict[int, NewsOverride] | None = None,
) -> dict[int, XptsBreakdown]:
    news_overrides = news_overrides or {}
    results: dict[int, XptsBreakdown] = {}
    for pid in player_ids:
        breakdown = compute_player_xpts_gw(
            conn, pid, gameweek, scoring, config.form_weights, team_strength, news_overrides.get(pid)
        )
        if breakdown is not None:
            results[pid] = breakdown
    return results
