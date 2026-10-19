import json
from decimal import Decimal
from pathlib import Path

import pike


def _scored(diver, points, code="105B", line=1):
    """Build a scored dive directly, for ranking and statistics tests."""
    dive = pike.Dive(line, diver, 1, code, Decimal("2.0"), [Decimal("8")] * 5)
    return pike.Scored(dive, [], [], Decimal(points))


FIVE_JUDGE_SHEET = """\
panel: 5
Ana | 1 | 105B | 2.0 | 8.0, 8.0, 8.0, 8.0, 8.0
Ana | 2 | 203C | 2.0 | 8.0, 8.0, 8.0, 8.0, 8.0
Ben | 1 | 107C | 3.6 | 8.0, 8.0, 8.0, 8.0, 8.0
Cy | 1 | 105B | 2.0 | 8.0, 8.0, 8.0, 8.0, 8.0
Dan | 1 | 105B | 2.0 | 8.0, 8.0, 8.0, 8.0, 8.0
"""


def test_seven_judges_drop_two_each_side_and_keep_middle_three():
    sheet, messages = pike.parse_sheet("panel: 7\nA | 1 | 105B | 2.0 | 7.5, 7.0, 7.5, 8.0, 7.5, 7.0, 7.5\n")
    assert messages == []
    scored = pike.score_dive(sheet.dives[0])
    # Sorted: 7.0 7.0 7.5 7.5 7.5 7.5 8.0 -> keep the middle three, which are 7.5 7.5 7.5
    assert scored.kept == [Decimal("7.5")] * 3
    assert scored.dropped == [Decimal("7.0"), Decimal("7.0"), Decimal("7.5"), Decimal("8.0")]
    assert scored.points == Decimal("27.00")  # 22.5 x 2.0 x 0.6


def test_five_judge_panel_drops_one_each_side():
    sheet, _ = pike.parse_sheet("panel: 5\nA | 1 | 105B | 2.0 | 6.0, 7.0, 8.0, 9.0, 10.0\n")
    scored = pike.score_dive(sheet.dives[0])
    assert scored.kept == [Decimal("7.0"), Decimal("8.0"), Decimal("9.0")]
    assert scored.points == Decimal("28.80")  # 24.0 x 2.0 x 0.6


def test_points_use_exact_decimal_arithmetic():
    sheet, _ = pike.parse_sheet("panel: 7\nA | 1 | 107C | 2.1 | 6.5, 7.0, 6.5, 6.5, 7.0, 6.5, 7.0\n")
    scored = pike.score_dive(sheet.dives[0])
    assert scored.kept == [Decimal("6.5"), Decimal("6.5"), Decimal("7.0")]
    assert scored.points == Decimal("25.20")  # 20.0 x 2.1 x 0.6


def test_parse_reports_every_problem_with_line_numbers():
    text = (
        "panel: 7\n"
        "A | 1 | 105B | 2.0 | 7.5, 7.0, 7.5, 8.0, 7.5, 7.0, 7.5\n"
        "B | 0 | 105B | 2.0 | 7.5, 7.0, 7.5, 8.0, 7.5, 7.0, 7.5\n"
        "C | 1 | 9XX | 9.0 | 7.5, 7.0, 7.5, 8.0, 7.5, 7.0, 10.5\n"
        "D | 1 | 205B | 2.0 | 7.5, 7.0\n"
    )
    sheet, messages = pike.parse_sheet(text, "meet.pike")
    assert any(m.startswith("meet.pike:3: round must be") for m in messages)
    assert any(m.startswith("meet.pike:4: dive code '9XX'") for m in messages)
    assert any(m.startswith("meet.pike:4: degree of difficulty 9.0") for m in messages)
    assert any(m.startswith("meet.pike:4: score 10.5 is outside 0-10") for m in messages)
    assert any(m == "meet.pike:5: 2 judge scores given, panel is 7" for m in messages)
    assert [d.diver for d in sheet.dives] == ["A"]


def test_half_point_steps_are_enforced():
    _, messages = pike.parse_sheet("panel: 5\nA | 1 | 105B | 2.0 | 7.3, 7.0, 7.0, 7.0, 7.0\n", "x")
    assert messages == ["x:2: score 7.3 is not a half-point step"]


def test_duplicate_dive_is_flagged_on_second_occurrence():
    text = (
        "panel: 5\n"
        "A | 1 | 105B | 2.0 | 7.0, 7.0, 7.0, 7.0, 7.0\n"
        "a | 1 | 105B | 2.0 | 7.0, 7.0, 7.0, 7.0, 7.0\n"
    )
    _, messages = pike.parse_sheet(text, "x")
    assert messages == ["x:3: duplicate dive 105B for a round 1 (first on line 2)"]


def test_panel_directive_must_be_five_or_seven():
    _, messages = pike.parse_sheet("panel: 6\nA | 1 | 105B | 2.0 | 7.0, 7.0, 7.0, 7.0, 7.0, 7.0\n", "x")
    assert "x:1: panel must be 5 or 7, got '6'" in messages


def test_degree_of_difficulty_range_is_enforced():
    _, messages = pike.parse_sheet("panel: 5\nA | 1 | 105B | 4.2 | 7.0, 7.0, 7.0, 7.0, 7.0\n", "x")
    assert messages == ["x:2: degree of difficulty 4.2 is outside 1.2-4.1"]


def test_four_digit_twisting_codes_are_accepted():
    _, messages = pike.parse_sheet("panel: 5\nA | 1 | 5253B | 2.0 | 7.0, 7.0, 7.0, 7.0, 7.0\n", "x")
    assert messages == []


def test_empty_sheet_is_an_error():
    _, messages = pike.parse_sheet("# nothing here\n", "x")
    assert messages == ["x: no dive lines found"]


def test_standings_rank_by_total_and_share_places_on_full_ties():
    rows = pike.standings([
        _scored("Ana", "28.80", line=2),
        _scored("Ana", "28.80", line=3),
        _scored("Ben", "51.84", line=4),
        _scored("Cy", "28.80", line=5),
        _scored("Dan", "28.80", line=6),
    ])
    assert [r["diver"] for r in rows] == ["Ana", "Ben", "Cy", "Dan"]
    assert [r["place"] for r in rows] == [1, 2, 3, 3]
    assert rows[0]["total"] == Decimal("57.60")


def test_standings_tie_break_on_best_single_dive():
    rows = pike.standings([
        _scored("Ivy", "10.00", line=2),
        _scored("Ivy", "20.00", line=3),
        _scored("Hal", "30.00", line=4),
    ])
    assert [r["diver"] for r in rows] == ["Hal", "Ivy"]
    assert [r["place"] for r in rows] == [1, 2]


def test_judge_bias_flags_the_judge_who_scores_high():
    sheet, _ = pike.parse_sheet(
        "panel: 5\n"
        "A | 1 | 105B | 2.0 | 8.0, 8.0, 8.0, 8.0, 9.0\n"
        "B | 1 | 105B | 2.0 | 8.0, 8.0, 8.0, 8.0, 9.0\n",
        "x",
    )
    report = pike.judge_bias(sheet, Decimal("0.5"))
    assert report[4]["judge"] == 5
    assert report[4]["mean_offset"] == Decimal("1.00")
    assert report[4]["flag"] == "high"
    assert all(r["flag"] == "" for r in report[:4])


def test_points_needed_reports_reached_unreachable_and_possible():
    assert pike.points_needed(Decimal("100"), Decimal("90"), Decimal("2.0"))["status"] == "reached"
    assert pike.points_needed(Decimal("0"), Decimal("1000"), Decimal("2.0"))["status"] == "unreachable"
    plan = pike.points_needed(Decimal("0"), Decimal("30.00"), Decimal("2.0"))
    assert plan["status"] == "possible"
    assert plan["half_step"] == Decimal("8.5")
    assert plan["achieved"] == Decimal("30.60")
    assert plan["achieved"] >= plan["gap"]


def test_dive_stats_group_points_by_code():
    rows = pike.dive_stats([_scored("A", "30.00"), _scored("B", "20.00"), _scored("C", "10.00", code="203C")])
    by_code = {r["code"]: r for r in rows}
    assert by_code["105B"]["count"] == 2
    assert by_code["105B"]["min"] == Decimal("20.00")
    assert by_code["105B"]["mean"] == Decimal("25.00")
    assert by_code["105B"]["max"] == Decimal("30.00")


def test_check_exit_codes_for_ok_lint_and_spread_gate(tmp_path, capsys):
    good = tmp_path / "good.pike"
    good.write_text("panel: 5\nA | 1 | 105B | 2.0 | 7.0, 7.5, 8.0, 8.5, 9.0\n", encoding="utf-8")
    assert pike.main(["check", str(good)]) == pike.EXIT_OK

    bad = tmp_path / "bad.pike"
    bad.write_text("panel: 5\nA | 1 | 105B | 2.0 | 7.3, 7.0, 7.0, 7.0, 7.0\n", encoding="utf-8")
    assert pike.main(["check", str(bad)]) == pike.EXIT_LINT
    assert f"{bad}:2: score 7.3 is not a half-point step" in capsys.readouterr().err

    # Counted judges here are 7.5, 8.0, 8.5: a spread of 1.0.
    assert pike.main(["check", str(good), "--max-spread", "0.5"]) == pike.EXIT_GATE
    assert pike.main(["check", str(good), "--max-spread", "1.0"]) == pike.EXIT_OK


def test_missing_file_and_unknown_diver_are_usage_errors(tmp_path, capsys):
    assert pike.main(["score", str(tmp_path / "nope.pike")]) == pike.EXIT_USAGE
    sheet = tmp_path / "s.pike"
    sheet.write_text(FIVE_JUDGE_SHEET, encoding="utf-8")
    assert pike.main(["needed", str(sheet), "Zed", "100", "--dd", "2.0"]) == pike.EXIT_USAGE
    assert "no diver named 'Zed'" in capsys.readouterr().err


def test_needed_command_reports_unreachable_target(tmp_path, capsys):
    sheet = tmp_path / "s.pike"
    sheet.write_text(FIVE_JUDGE_SHEET, encoding="utf-8")
    assert pike.main(["needed", str(sheet), "Ana", "100", "--dd", "2.0"]) == pike.EXIT_OK
    out = capsys.readouterr().out
    assert "Ana has 57.60 after 2 dives" in out
    assert "Unreachable" in out


def test_json_and_csv_outputs_keep_exact_strings():
    scored = [_scored("Ana", "28.80", line=2)]
    records = json.loads(pike.render_score(scored, "json"))
    assert records[0]["points"] == "28.80"
    rows = pike.standings(scored)
    csv_lines = pike.render_standings(rows, "csv").splitlines()
    assert csv_lines[0] == "place,diver,dives,total,best,average"
    assert csv_lines[1] == "1,Ana,1,28.80,28.80,28.80"


def test_bundled_sample_sheet_is_valid_and_init_refuses_overwrite(tmp_path, capsys):
    _, messages = pike.parse_sheet(pike.SAMPLE, "sample")
    assert messages == []
    target = tmp_path / "meet.pike"
    assert pike.main(["init", str(target)]) == pike.EXIT_OK
    assert target.read_text(encoding="utf-8") == pike.SAMPLE
    assert pike.main(["init", str(target)]) == pike.EXIT_USAGE
    assert pike.main(["init", str(target), "--force"]) == pike.EXIT_OK
