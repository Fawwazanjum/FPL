from fpl_model.data.understat_client import _normalize, map_fpl_to_understat


def _u(id_, name):
    return {"id": id_, "player_name": name}


def test_normalize_strips_accents_and_punctuation():
    assert _normalize("É.Le Fée") == "ele fee"


def test_exact_surname_substring_match():
    players = [_u("1", "Bruno Fernandes"), _u("2", "Erling Haaland")]
    result = map_fpl_to_understat("B.Fernandes", players)
    assert result == ("1", 1.0)


def test_simple_surname_match():
    players = [_u("1", "Bruno Fernandes"), _u("2", "Erling Haaland")]
    result = map_fpl_to_understat("Haaland", players)
    assert result == ("2", 1.0)


def test_ambiguous_surname_falls_back_to_fuzzy_ratio():
    # Two "Silva"s -> substring match is ambiguous, falls back to full-name fuzzy match
    players = [_u("1", "Bernardo Silva"), _u("2", "Thiago Silva")]
    result = map_fpl_to_understat("Bernardo Silva", players)
    assert result is not None
    assert result[0] == "1"


def test_no_confident_match_returns_none():
    players = [_u("1", "Someone Completely Different")]
    result = map_fpl_to_understat("Xyzzyx Notreal", players)
    assert result is None


def test_empty_candidate_list_returns_none():
    assert map_fpl_to_understat("Haaland", []) is None
