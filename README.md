# Pike 🤿

**Offline diving-judge scorer for plain-text dive sheets.**

Pike takes one readable text file of dives and judge scores and gives you exact,
trimmed-mean scores, standings, judge-bias reports, and "what do I need next dive"
answers. It is a single standard-library Python file with no accounts, no servers,
and no network access.

## Features

- **Plain-text dive sheets.** One dive per line: `diver | round | dive code | DD | judge scores`. Comments start with `#`.
- **Trimmed-mean scoring.** Drops the highest and lowest judges, keeps the middle three, and computes `middle sum × DD × 0.6`.
- **Panels of 5 or 7.** A `panel:` directive sets the judge count, and every dive is checked against it.
- **Exact cents.** All arithmetic uses `Decimal`. Points are rounded half-up to 0.01, never floats.
- **Line-numbered lint.** `check` reports every problem at `file:line`: bad dive codes, DD outside 1.2–4.1, scores outside 0–10, scores that are not half-point steps, wrong judge counts, duplicate dives, and unknown directives.
- **Per-dive breakdown.** `score` shows the kept judges, the dropped judges, and the points for every dive, as text, CSV, or JSON.
- **Standings.** `standings` ranks divers by total, breaks ties on the best single dive, and gives equal records a shared place. Filter by round with `--round`.
- **Judge-bias report.** `judges` shows each judge's mean offset from the panel median and flags judges who lean high or low.
- **Target planner.** `needed` says what the next dive must score to reach a target total, including the half-point scores that get there. It also reports when the target can't be reached.
- **Dive statistics.** `summary` gives count, min, mean, and max points for each dive code.
- **CI gate.** `check --max-spread` fails with exit code 3 when counted judges disagree too much on any dive.
- **Exit codes that scripts can use.** 0 for success, 1 for lint errors, 2 for usage or file errors, and 3 for a failed gate.
- **Sample sheet.** `init` writes a working example to start from.

## Quick start

```bash
python3 pike.py init meet.pike
python3 pike.py check meet.pike
python3 pike.py standings meet.pike
```

The bundled example lives at `examples/sample.pike`. Running `check` on it prints:

```
OK: 9 dives, 3 divers, panel of 7
```

`standings` on the same file prints:

```
Place  Diver       Dives  Total   Best   Average
-----  ----------  -----  ------  -----  -------
1      Cleo Marin  3      106.50  41.34  35.50
2      Ana Reyes   3      95.40   37.44  31.80
3      Ben Okafor  3      87.84   31.59  29.28
```

Other useful commands:

```bash
python3 pike.py score meet.pike --round 3 --format csv
python3 pike.py judges meet.pike --threshold 0.5
python3 pike.py needed meet.pike "Ben Okafor" 100 --dd 2.7
python3 pike.py check meet.pike --max-spread 1.5
```

## Dive sheet format

```
# comments start with #
panel: 7
Ana Reyes | 1 | 105B | 2.0 | 7.5, 7.0, 7.5, 8.0, 7.5, 7.0, 7.5
```

- `panel:` is optional and must be `5` or `7`. The default is `7`.
- `round` is a positive whole number.
- The dive code is a group from 1 to 6, then two or three digits, then a position letter A–D, such as `105B` or `5253B`.
- `DD` is the degree of difficulty, from 1.2 to 4.1.
- Judge scores run from 0 to 10 in half-point steps and are separated by commas or spaces.

## How scoring works

For a 7-judge panel, the highest two and lowest two scores are dropped. For a 5-judge panel,
the highest and lowest are dropped. Either way, the middle three are summed, multiplied by
the DD, multiplied by 0.6, and rounded to the cent.

## How to run

Pike needs Python 3.10 or newer and nothing else.

```bash
python3 pike.py --help
python3 pike.py <command> --help
```

Exit codes: `0` success, `1` lint errors in the sheet, `2` usage or file errors, `3` a failed `--max-spread` gate.

## How to test

The tests use pytest. Install it once with `pip install pytest`, then run:

```bash
python3 -m pytest -q
```

The suite covers the scoring rules, the line-numbered lint, tie-breaks, judge bias, the
target planner, CSV and JSON output, and the CLI exit codes.

## Project layout

```
pike.py              the whole program (standard library only)
examples/sample.pike a nine-dive sample meet
tests/               pytest suite
```

## Limits

Pike models the scoring rule described above. It does not model synchronised or tandem
dives, and it does not look up DD values, which you enter yourself from the rulebook for your
event.
