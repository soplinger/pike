#!/usr/bin/env python3
"""Pike: offline diving-judge scorer for plain-text dive sheets.

Each dive line gives the diver, round, dive code, degree of difficulty (DD)
and every judge's score. Pike drops the highest and lowest judges, keeps the
middle three, and scores the dive as middle-sum x DD x 0.6, with exact cents.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

MIN_DD = Decimal("1.2")
MAX_DD = Decimal("4.1")
FACTOR = Decimal("0.6")
CENT = Decimal("0.01")
MAX_SCORE = Decimal("10")
COUNTED = 3
PANEL_SIZES = (5, 7)
CODE_RE = re.compile(r"^[1-6]\d{2,3}[A-D]$")
SCORE_SPLIT_RE = re.compile(r"[,\s]+")

EXIT_OK = 0
EXIT_LINT = 1
EXIT_USAGE = 2
EXIT_GATE = 3

SAMPLE = """\
# Pike dive sheet
# Dive line:  diver | round | dive code | DD | judge scores (comma-separated)
# Scores run 0-10 in half-point steps. Count must match the panel size.
panel: 7
Ana Reyes | 1 | 105B | 2.0 | 7.5, 7.0, 7.5, 8.0, 7.5, 7.0, 7.5
Ana Reyes | 2 | 203C | 2.4 | 7.0, 7.5, 7.0, 7.5, 7.0, 6.5, 7.5
Ana Reyes | 3 | 301B | 2.6 | 8.0, 8.5, 8.0, 7.5, 8.0, 8.0, 8.5
Ben Okafor | 1 | 107C | 2.1 | 6.5, 7.0, 6.5, 6.5, 7.0, 6.5, 7.0
Ben Okafor | 2 | 205B | 2.3 | 7.5, 7.5, 8.0, 7.0, 7.5, 7.5, 7.0
Ben Okafor | 3 | 303C | 2.7 | 6.0, 6.5, 6.5, 7.0, 6.0, 6.5, 6.5
Cleo Marin | 1 | 105B | 2.0 | 8.5, 8.0, 8.5, 9.0, 8.0, 8.5, 8.5
Cleo Marin | 2 | 203C | 2.4 | 8.0, 8.0, 8.5, 8.0, 8.5, 8.0, 8.0
Cleo Marin | 3 | 301B | 2.6 | 9.0, 8.5, 9.0, 8.5, 9.0, 8.5, 9.0
"""


class PikeError(Exception):
    """A user-facing error. Printed without a traceback."""


class LintError(PikeError):
    """A sheet that failed validation. Carries one message per problem."""

    def __init__(self, messages: list[str]):
        super().__init__("\n".join(messages))
        self.messages = messages


@dataclass
class Dive:
    line: int
    diver: str
    round: int
    code: str
    dd: Decimal
    scores: list[Decimal]


@dataclass
class Sheet:
    panel: int = 7
    dives: list[Dive] = field(default_factory=list)


@dataclass
class Scored:
    dive: Dive
    kept: list[Decimal]
    dropped: list[Decimal]
    points: Decimal


# ---------------------------------------------------------------- parsing

def _check_score(token: str) -> tuple[Decimal | None, str | None]:
    try:
        value = Decimal(token)
    except InvalidOperation:
        return None, f"score {token!r} is not a number"
    if not value.is_finite() or value < 0 or value > MAX_SCORE:
        return None, f"score {token} is outside 0-10"
    doubled = value * 2
    if doubled != doubled.to_integral_value():
        return None, f"score {token} is not a half-point step"
    return value, None


def _check_dd(token: str) -> tuple[Decimal | None, str | None]:
    try:
        value = Decimal(token)
    except InvalidOperation:
        return None, f"degree of difficulty {token!r} is not a number"
    if not value.is_finite() or not MIN_DD <= value <= MAX_DD:
        return None, f"degree of difficulty {token} is outside {MIN_DD}-{MAX_DD}"
    return value, None


def parse_sheet(text: str, label: str = "sheet") -> tuple[Sheet, list[str]]:
    """Parse a dive sheet. Returns the sheet and every problem found, in line order."""
    sheet = Sheet()
    problems: list[tuple[int, str]] = []
    seen: dict[tuple[str, int, str], int] = {}

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if "|" not in line:
            key, sep, value = line.partition(":")
            if not sep or key.strip().lower() != "panel":
                problems.append((lineno, f"unknown directive {line!r} (expected 'panel: 5' or 'panel: 7')"))
                continue
            try:
                panel = int(value.strip())
            except ValueError:
                panel = None
            if panel in PANEL_SIZES:
                sheet.panel = panel
            else:
                problems.append((lineno, f"panel must be 5 or 7, got {value.strip()!r}"))
            continue

        fields = [f.strip() for f in line.split("|")]
        if len(fields) != 5:
            problems.append((lineno, f"expected 5 fields (diver | round | dive | DD | scores), found {len(fields)}"))
            continue
        diver, round_txt, code, dd_txt, score_txt = fields
        line_ok = True

        if not diver:
            problems.append((lineno, "diver name is empty"))
            line_ok = False
        if not round_txt.isdigit() or int(round_txt) < 1:
            problems.append((lineno, f"round must be a positive whole number, got {round_txt!r}"))
            line_ok = False
        if not CODE_RE.match(code):
            problems.append((lineno, f"dive code {code!r} must look like 105B or 5253B (group 1-6, two or three more digits, position A-D)"))
            line_ok = False
        dd, dd_problem = _check_dd(dd_txt)
        if dd_problem:
            problems.append((lineno, dd_problem))
            line_ok = False

        tokens = [t for t in SCORE_SPLIT_RE.split(score_txt) if t]
        scores: list[Decimal] = []
        if not tokens:
            problems.append((lineno, "no judge scores given"))
            line_ok = False
        for token in tokens:
            value, problem = _check_score(token)
            if problem:
                problems.append((lineno, problem))
                line_ok = False
            else:
                scores.append(value)

        if not line_ok:
            continue

        key = (diver.casefold(), int(round_txt), code)
        if key in seen:
            problems.append((lineno, f"duplicate dive {code} for {diver} round {round_txt} (first on line {seen[key]})"))
            continue
        seen[key] = lineno
        sheet.dives.append(Dive(lineno, diver, int(round_txt), code, dd, scores))

    # Judge counts depend on the panel directive, which may come after the dives.
    for dive in list(sheet.dives):
        if len(dive.scores) != sheet.panel:
            problems.append((dive.line, f"{len(dive.scores)} judge scores given, panel is {sheet.panel}"))
            sheet.dives.remove(dive)

    if not sheet.dives and not problems:
        problems.append((0, "no dive lines found"))

    problems.sort(key=lambda p: p[0])
    messages = [f"{label}:{n}: {msg}" if n else f"{label}: {msg}" for n, msg in problems]
    return sheet, messages


def load_sheet(path: str, round_no: int | None = None) -> Sheet:
    """Read and validate a sheet file, optionally keeping only one round."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise PikeError(f"cannot read {path}: {exc.strerror}") from exc
    sheet, messages = parse_sheet(text, path)
    if messages:
        raise LintError(messages)
    if round_no is not None:
        sheet.dives = [d for d in sheet.dives if d.round == round_no]
        if not sheet.dives:
            raise PikeError(f"no dives in round {round_no}")
    return sheet


# ---------------------------------------------------------------- scoring

def score_dive(dive: Dive) -> Scored:
    """Drop the highest and lowest judges (trimmed equally), keep the middle three."""
    ordered = sorted(dive.scores)
    trim = (len(ordered) - COUNTED) // 2
    kept = ordered[trim:len(ordered) - trim]
    dropped = ordered[:trim] + ordered[len(ordered) - trim:]
    points = (sum(kept, Decimal(0)) * dive.dd * FACTOR).quantize(CENT, rounding=ROUND_HALF_UP)
    return Scored(dive, kept, dropped, points)


def score_sheet(sheet: Sheet) -> list[Scored]:
    return [score_dive(d) for d in sheet.dives]


def standings(scored: list[Scored]) -> list[dict]:
    """Rank divers by total. Ties break on best single dive, then name. Equal records share a place."""
    rows: dict[str, dict] = {}
    for s in scored:
        key = s.dive.diver.casefold()
        row = rows.setdefault(key, {"diver": s.dive.diver, "dives": 0,
                                    "total": Decimal(0), "best": Decimal(0)})
        row["dives"] += 1
        row["total"] += s.points
        row["best"] = max(row["best"], s.points)
    ordered = sorted(rows.values(), key=lambda r: (-r["total"], -r["best"], r["diver"].casefold()))
    place = 0
    previous = None
    for index, row in enumerate(ordered, start=1):
        record = (row["total"], row["best"])
        if record != previous:
            place = index
            previous = record
        row["place"] = place
        row["average"] = (row["total"] / row["dives"]).quantize(CENT, rounding=ROUND_HALF_UP)
    return ordered


def judge_bias(sheet: Sheet, threshold: Decimal) -> list[dict]:
    """Each judge's mean distance from the panel median, flagged when it passes the threshold."""
    panel = sheet.panel
    totals = [Decimal(0)] * panel
    for dive in sheet.dives:
        median = Decimal(str(statistics.median(dive.scores)))
        for index, score in enumerate(dive.scores):
            totals[index] += score - median
    count = len(sheet.dives)
    report = []
    for index, total in enumerate(totals):
        mean = (total / count).quantize(CENT, rounding=ROUND_HALF_UP)
        flag = ""
        if abs(mean) >= threshold:
            flag = "high" if mean > 0 else "low"
        report.append({"judge": index + 1, "mean_offset": mean, "flag": flag})
    return report


def points_needed(current: Decimal, target: Decimal, dd: Decimal) -> dict:
    """Work out what one more dive must score to lift a total to the target."""
    gap = target - current
    if gap <= 0:
        return {"status": "reached", "gap": Decimal(0)}
    best = (MAX_SCORE * COUNTED * dd * FACTOR).quantize(CENT, rounding=ROUND_HALF_UP)
    if gap > best:
        return {"status": "unreachable", "gap": gap, "best": best}
    avg = gap / (dd * FACTOR) / COUNTED
    half_step = (avg * 2).to_integral_value(rounding=ROUND_CEILING) / 2
    achieved = (half_step * COUNTED * dd * FACTOR).quantize(CENT, rounding=ROUND_HALF_UP)
    return {"status": "possible", "gap": gap, "average": avg.quantize(CENT, rounding=ROUND_HALF_UP),
            "half_step": half_step, "achieved": achieved, "best": best}


def dive_stats(scored: list[Scored]) -> list[dict]:
    """Points per dive code across every diver who performed it."""
    groups: dict[str, list[Decimal]] = {}
    for s in scored:
        groups.setdefault(s.dive.code, []).append(s.points)
    rows = []
    for code in sorted(groups):
        values = groups[code]
        mean = (sum(values, Decimal(0)) / len(values)).quantize(CENT, rounding=ROUND_HALF_UP)
        rows.append({"code": code, "count": len(values), "min": min(values), "mean": mean, "max": max(values)})
    return rows


# ---------------------------------------------------------------- rendering

def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return "\n".join(lines)


def _csv(headers: list[str], rows: list[list]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows([[str(v) for v in row] for row in rows])
    return buffer.getvalue()


def _json(rows: list[dict]) -> str:
    return json.dumps(rows, indent=2) + "\n"


def render_score(scored: list[Scored], fmt: str) -> str:
    headers = ["Line", "Diver", "Rnd", "Dive", "DD", "Kept", "Dropped", "Points"]
    if fmt == "text":
        rows = [[str(s.dive.line), s.dive.diver, str(s.dive.round), s.dive.code, str(s.dive.dd),
                 " ".join(str(v) for v in s.kept), " ".join(str(v) for v in s.dropped), str(s.points)]
                for s in scored]
        return _table(headers, rows) + "\n"
    records = [{"line": s.dive.line, "diver": s.dive.diver, "round": s.dive.round, "dive": s.dive.code,
                "dd": str(s.dive.dd), "kept": [str(v) for v in s.kept],
                "dropped": [str(v) for v in s.dropped], "points": str(s.points)} for s in scored]
    if fmt == "csv":
        return _csv(["line", "diver", "round", "dive", "dd", "kept", "dropped", "points"],
                    [[r["line"], r["diver"], r["round"], r["dive"], r["dd"],
                      " ".join(r["kept"]), " ".join(r["dropped"]), r["points"]] for r in records])
    return _json(records)


def render_standings(rows: list[dict], fmt: str) -> str:
    if fmt == "text":
        table = [[str(r["place"]), r["diver"], str(r["dives"]), str(r["total"]),
                  str(r["best"]), str(r["average"])] for r in rows]
        return _table(["Place", "Diver", "Dives", "Total", "Best", "Average"], table) + "\n"
    records = [{"place": r["place"], "diver": r["diver"], "dives": r["dives"],
                "total": str(r["total"]), "best": str(r["best"]), "average": str(r["average"])}
               for r in rows]
    if fmt == "csv":
        return _csv(["place", "diver", "dives", "total", "best", "average"],
                    [[r["place"], r["diver"], r["dives"], r["total"], r["best"], r["average"]] for r in records])
    return _json(records)


def render_bias(report: list[dict]) -> str:
    rows = [[f"J{r['judge']}", str(r["mean_offset"]), r["flag"] or "-"] for r in report]
    return _table(["Judge", "Mean offset", "Flag"], rows) + "\n"


def render_summary(rows: list[dict]) -> str:
    table = [[r["code"], str(r["count"]), str(r["min"]), str(r["mean"]), str(r["max"])] for r in rows]
    return _table(["Dive", "Count", "Min", "Mean", "Max"], table) + "\n"


# ---------------------------------------------------------------- commands

def _decimal_arg(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from exc
    if not value.is_finite():
        raise argparse.ArgumentTypeError(f"not a finite number: {text!r}")
    return value


def cmd_check(args: argparse.Namespace) -> int:
    try:
        text = Path(args.file).read_text(encoding="utf-8")
    except OSError as exc:
        raise PikeError(f"cannot read {args.file}: {exc.strerror}") from exc
    sheet, messages = parse_sheet(text, args.file)
    if messages:
        for message in messages:
            print(message, file=sys.stderr)
        return EXIT_LINT
    divers = {d.diver.casefold() for d in sheet.dives}
    print(f"OK: {len(sheet.dives)} dives, {len(divers)} divers, panel of {sheet.panel}")
    if args.max_spread is not None:
        failures = [s for s in score_sheet(sheet)
                    if max(s.kept) - min(s.kept) > args.max_spread]
        for s in failures:
            spread = max(s.kept) - min(s.kept)
            print(f"{args.file}:{s.dive.line}: counted-judge spread {spread} exceeds {args.max_spread}")
        if failures:
            return EXIT_GATE
        print(f"spread gate passed (limit {args.max_spread})")
    return EXIT_OK


def cmd_score(args: argparse.Namespace) -> int:
    sheet = load_sheet(args.file, args.round)
    print(render_score(score_sheet(sheet), args.format), end="")
    return EXIT_OK


def cmd_standings(args: argparse.Namespace) -> int:
    sheet = load_sheet(args.file, args.round)
    print(render_standings(standings(score_sheet(sheet)), args.format), end="")
    return EXIT_OK


def cmd_judges(args: argparse.Namespace) -> int:
    sheet = load_sheet(args.file)
    print(render_bias(judge_bias(sheet, args.threshold)), end="")
    return EXIT_OK


def cmd_summary(args: argparse.Namespace) -> int:
    sheet = load_sheet(args.file)
    print(render_summary(dive_stats(score_sheet(sheet))), end="")
    return EXIT_OK


def cmd_needed(args: argparse.Namespace) -> int:
    if not MIN_DD <= args.dd <= MAX_DD:
        raise PikeError(f"degree of difficulty {args.dd} is outside {MIN_DD}-{MAX_DD}")
    sheet = load_sheet(args.file)
    scored = score_sheet(sheet)
    mine = [s for s in scored if s.dive.diver.casefold() == args.diver.casefold()]
    if not mine:
        raise PikeError(f"no diver named {args.diver!r} in {args.file}")
    current = sum((s.points for s in mine), Decimal(0))
    name = mine[0].dive.diver
    plan = points_needed(current, args.target, args.dd)
    print(f"{name} has {current} after {len(mine)} dives (target {args.target}).")
    if plan["status"] == "reached":
        print("Target already reached.")
    elif plan["status"] == "unreachable":
        print(f"Unreachable: {plan['gap']} more needed, but the best next dive at DD {args.dd} is {plan['best']}.")
    else:
        print(f"Next dive at DD {args.dd} needs {plan['gap']} points.")
        print(f"The three counted judges must average at least {plan['average']}.")
        print(f"Half-point scores of {plan['half_step']} from each counted judge give {plan['achieved']}.")
    return EXIT_OK


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if path.exists() and not args.force:
        raise PikeError(f"{args.path} already exists (use --force to overwrite)")
    path.write_text(SAMPLE, encoding="utf-8")
    print(f"wrote sample sheet to {args.path}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pike", description="Offline diving-judge scorer for plain-text dive sheets.")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="lint a dive sheet with line-numbered errors")
    check.add_argument("file")
    check.add_argument("--max-spread", type=_decimal_arg,
                       help="CI gate: fail if counted judges on any dive differ by more than this")
    check.set_defaults(func=cmd_check)

    score = sub.add_parser("score", help="score every dive, showing kept and dropped judges")
    score.add_argument("file")
    score.add_argument("--round", type=int)
    score.add_argument("--format", choices=["text", "csv", "json"], default="text")
    score.set_defaults(func=cmd_score)

    standing = sub.add_parser("standings", help="rank divers by total with tie-breaks")
    standing.add_argument("file")
    standing.add_argument("--round", type=int)
    standing.add_argument("--format", choices=["text", "csv", "json"], default="text")
    standing.set_defaults(func=cmd_standings)

    judges = sub.add_parser("judges", help="show each judge's mean offset from the panel median")
    judges.add_argument("file")
    judges.add_argument("--threshold", type=_decimal_arg, default=Decimal("0.5"),
                        help="flag judges whose mean offset is at least this large (default 0.5)")
    judges.set_defaults(func=cmd_judges)

    summary = sub.add_parser("summary", help="points per dive code: count, min, mean, max")
    summary.add_argument("file")
    summary.set_defaults(func=cmd_summary)

    needed = sub.add_parser("needed", help="what the next dive must score to reach a target total")
    needed.add_argument("file")
    needed.add_argument("diver")
    needed.add_argument("target", type=_decimal_arg)
    needed.add_argument("--dd", type=_decimal_arg, required=True, help="degree of difficulty of the next dive")
    needed.set_defaults(func=cmd_needed)

    init = sub.add_parser("init", help="write a sample dive sheet")
    init.add_argument("path")
    init.add_argument("--force", action="store_true", help="overwrite an existing file")
    init.set_defaults(func=cmd_init)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_USAGE if exc.code else EXIT_OK
    try:
        return args.func(args)
    except LintError as exc:
        for message in exc.messages:
            print(message, file=sys.stderr)
        return EXIT_LINT
    except PikeError as exc:
        print(f"pike: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
