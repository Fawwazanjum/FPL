from pathlib import Path

from fpl_model.report.news_overrides import load_news_overrides


def test_absent_file_returns_empty_overlay(tmp_path):
    result = load_news_overrides(tmp_path / "does_not_exist.yaml")
    assert result == {}


def test_loads_valid_availability_and_role_override(tmp_path):
    path = tmp_path / "news_overrides.yaml"
    path.write_text(
        """
players:
  328:
    status: doubtful
    chance_of_playing_override: 50
    note: "Assessing him daily"
    source: "https://example.com"
  455:
    role_note: "Played as auxiliary midfielder for the full match"
    role_direction: more_attacking
    set_piece_note: "Chances came from corners"
""",
        encoding="utf-8",
    )
    result = load_news_overrides(path)

    assert result[328].status == "doubtful"
    assert result[328].chance_of_playing_override == 50
    assert result[328].note == "Assessing him daily"
    assert result[455].role_direction == "more_attacking"
    assert result[455].set_piece_note == "Chances came from corners"


def test_invalid_status_is_dropped_not_crashed(tmp_path):
    path = tmp_path / "news_overrides.yaml"
    path.write_text("players:\n  1:\n    status: definitely_playing\n", encoding="utf-8")
    result = load_news_overrides(path)
    assert result[1].status is None


def test_invalid_role_direction_is_dropped(tmp_path):
    path = tmp_path / "news_overrides.yaml"
    path.write_text("players:\n  1:\n    role_direction: sideways\n", encoding="utf-8")
    result = load_news_overrides(path)
    assert result[1].role_direction is None


def test_non_integer_player_id_is_skipped(tmp_path):
    path = tmp_path / "news_overrides.yaml"
    path.write_text("players:\n  not_a_number:\n    status: out\n", encoding="utf-8")
    result = load_news_overrides(path)
    assert result == {}


def test_malformed_yaml_returns_empty_overlay_not_crash(tmp_path):
    path = tmp_path / "news_overrides.yaml"
    path.write_text("players: [this is not a mapping structure :::", encoding="utf-8")
    result = load_news_overrides(path)
    assert result == {}


def test_empty_players_key_returns_empty_overlay(tmp_path):
    path = tmp_path / "news_overrides.yaml"
    path.write_text("players: {}\n", encoding="utf-8")
    result = load_news_overrides(path)
    assert result == {}
