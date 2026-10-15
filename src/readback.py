"""Read the loaded Data Commons database back and compare it with what was meant to be loaded.

Checks
  1. output/observations.csv  vs  observations table in output/datacommons/datacommons.db,
     row by row on (entity, variable, date): missing in DB, missing in CSV, value mismatch,
     wrong unit, duplicate rows, zeros.
  2. The database  vs  the final source dataset (source/cbk_inflation_final.csv: the live CBK page, checked
     against the Excel export by src/fetch_live.py), parsed here with the csv module and none of the
     pipeline code, so a pipeline bug cannot hide behind a matching CSV.
  3. The variable definitions (MCF triples) and the import status are in the database.

Writes docs/readback_report.md. Exits 1 if any difference is found.

Usage:
    python src/readback.py                 # scope from January 2015
    python src/readback.py --start 2010-01 # if the pipeline was run with --start 2010-01
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

import csv as csvlib
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "output" / "datacommons" / "datacommons.db"
CSV = ROOT / "output" / "observations.csv"
SOURCE_FINAL = ROOT / "source" / "cbk_inflation_final.csv"
REPORT = ROOT / "docs" / "readback_report.md"

ENTITY = "country/KEN"
UNIT = "Percent"
# Kept separate from pipeline.py on purpose, so the check does not share the pipeline's code.
VARIABLES = {
    "12-Month Inflation": "cbk/InflationRate_12Month",
    "Annual Average Inflation": "cbk/InflationRate_AnnualAverage",
}
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
KEY = ["entity", "variable", "date"]


def num(x) -> float | None:
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return None


def load_db() -> tuple[pd.DataFrame, dict]:
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    try:
        q = (f"SELECT entity, variable, date, value, unit, provenance FROM observations "
             f"WHERE entity = ? AND variable IN ({','.join('?' * len(VARIABLES))})")
        obs = pd.read_sql_query(q, con, params=[ENTITY, *VARIABLES.values()], dtype=str)
        meta = {
            "all_rows": con.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
            "imports": con.execute("SELECT imported_at, status, metadata FROM imports").fetchall(),
            "triples": {v: dict(con.execute("SELECT predicate, COALESCE(object_id, object_value) FROM triples "
                                            "WHERE subject_id = ?", (v,)).fetchall())
                        for v in VARIABLES.values()},
        }
    finally:
        con.close()
    return obs, meta


def load_source(start: str) -> pd.DataFrame:
    """Independent parse of the final source dataset: match columns by name, build YYYY-MM from Year+Month."""
    out = {}
    with SOURCE_FINAL.open(encoding="utf-8", newline="") as f:
        for r in csvlib.DictReader(f):
            year, month = (r.get("Year") or "").strip(), (r.get("Month") or "").strip()
            if month not in MONTHS or not year.isdigit():
                continue
            d = f"{int(year):04d}-{MONTHS.index(month) + 1:02d}"
            if d < start:
                continue
            for col, var in VARIABLES.items():
                v = num(r.get(col))
                if v is not None:  # blank / non-numeric = missing, no observation expected
                    out[(ENTITY, var, d)] = v
    return pd.DataFrame([(*k, v) for k, v in out.items()], columns=[*KEY, "value"])


def compare(expected: pd.DataFrame, actual: pd.DataFrame, exp_name: str) -> list[str]:
    """Row-by-row comparison on (entity, variable, date). Returns one line per difference."""
    m = expected.merge(actual, on=KEY, how="outer", suffixes=("_exp", "_db"), indicator=True)
    diffs = []
    for _, r in m.sort_values(KEY).iterrows():
        k = f"`{r['variable']}` {r['date']}"
        if r["_merge"] == "left_only":
            diffs.append(f"{k}: in {exp_name} ({r['value_exp']}) but missing in the database: not loaded")
        elif r["_merge"] == "right_only":
            diffs.append(f"{k}: in the database ({r['value_db']}) but not in {exp_name}: unexpected or stale row")
        elif num(r["value_exp"]) != num(r["value_db"]):
            diffs.append(f"{k}: value mismatch, {exp_name} {r['value_exp']} vs database {r['value_db']}")
    return diffs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2015-01", help="first month in scope, YYYY-MM (default 2015-01)")
    args = ap.parse_args(argv)

    for p in (DB, CSV, SOURCE_FINAL):
        if not p.is_file():
            print(f"missing {p.relative_to(ROOT)}: run the pipeline and the load first", file=sys.stderr)
            return 2

    csv = pd.read_csv(CSV, dtype=str, keep_default_na=False)
    db, meta = load_db()
    src = load_source(args.start)

    problems: list[str] = []
    # 1. CSV vs DB
    csv_vs_db = compare(csv[KEY + ["value"]], db[KEY + ["value"]], "CSV")
    matched = len(csv.merge(db, on=KEY).query("value_x.astype('float') == value_y.astype('float')", engine="python"))
    # duplicates, units, zeros, blanks
    for name, df in (("CSV", csv), ("database", db)):
        for _, r in df[df.duplicated(KEY, keep=False)].drop_duplicates(KEY).iterrows():
            problems.append(f"{name}: duplicate rows for `{r['variable']}` {r['date']}")
        for _, r in df[df["unit"] != UNIT].iterrows():
            problems.append(f"{name}: `{r['variable']}` {r['date']} has unit '{r['unit']}', expected '{UNIT}'")
        for _, r in df[df["value"].map(num).isna()].iterrows():
            problems.append(f"{name}: `{r['variable']}` {r['date']} has a blank/non-numeric value '{r['value']}'")
    zeros_db = db[db["value"].map(num) == 0]
    zeros_src = src[src["value"] == 0]
    if len(zeros_db) != len(zeros_src):
        problems.append(f"database has {len(zeros_db)} zero values but the source has {len(zeros_src)}: "
                        "a missing value may have been stored as 0")
    # 2. source vs DB
    src_vs_db = compare(src, db[KEY + ["value"]], "source dataset")
    # 3. definitions + import status
    for var, props in meta["triples"].items():
        for p, want in [("typeOf", "StatisticalVariable"), ("measuredProperty", "inflation"),
                        ("populationType", "EconomicActivity"), ("unit", UNIT)]:
            if props.get(p) != want:
                problems.append(f"MCF: `{var}` {p} is {props.get(p)!r}, expected {want!r}")
    statuses = [s for _, s, _ in meta["imports"]]
    if statuses != ["SUCCESS"]:
        problems.append(f"imports table status is {statuses}, expected ['SUCCESS']")

    differences = csv_vs_db + src_vs_db + problems
    ok = not differences

    per_var = db.groupby("variable").agg(rows=("date", "size"), first=("date", "min"), last=("date", "max"))
    spot = []
    for var in VARIABLES.values():
        for d in ("2015-01", "2019-04", "2025-01", db["date"].max()):
            s = src.query("variable == @var and date == @d")["value"]
            c = csv.query("variable == @var and date == @d")["value"]
            b = db.query("variable == @var and date == @d")["value"]
            spot.append(f"| `{var}` | {d} | {s.iloc[0] if len(s) else '—'} | {c.iloc[0] if len(c) else '—'} | "
                        f"{b.iloc[0] if len(b) else '—'} |")

    lines = [
        "# Readback report",
        "",
        f"Generated by `python src/readback.py` on {date.today().isoformat()}. "
        f"Scope: `{ENTITY}`, {args.start} onwards.",
        "",
        f"**Result: {'PASS — the database matches the CSV and the source, row for row.' if ok else f'FAIL — {len(differences)} difference(s).'}**",
        "",
        "## Counts",
        "| | Rows |",
        "|---|---|",
        f"| Source CSV (`output/observations.csv`) | {len(csv)} |",
        f"| Loaded database (`observations`, {ENTITY}, the 2 variables) | {len(db)} |",
        f"| All rows in the database `observations` table | {meta['all_rows']} |",
        f"| Matching rows (same entity, variable, date and value) | {matched} |",
        f"| Expected from `source/cbk_inflation_final.csv` (parsed independently) | {len(src)} |",
        "",
        "| Variable | Rows in DB | First | Last |",
        "|---|---|---|---|",
        *[f"| `{v}` | {r['rows']} | {r['first']} | {r['last']} |" for v, r in per_var.iterrows()],
        "",
        "## Checks",
        "| Check | Result |",
        "|---|---|",
        f"| CSV vs database, row by row | {'no differences' if not csv_vs_db else f'{len(csv_vs_db)} difference(s)'} |",
        f"| Source dataset vs database, row by row | {'no differences' if not src_vs_db else f'{len(src_vs_db)} difference(s)'} |",
        f"| Duplicate (entity, variable, date) rows | {'none' if not any('duplicate' in p for p in problems) else 'found'} |",
        f"| Units | {', '.join(sorted(db['unit'].unique()))} on every row |",
        f"| Missing values stored as 0 | {'no' if len(zeros_db) == len(zeros_src) else 'POSSIBLY'} "
        f"(zeros in database: {len(zeros_db)}, in source: {len(zeros_src)}) |",
        f"| Provenance ids | {', '.join(sorted(db['provenance'].unique()))} |",
        f"| Import status (`imports` table) | {', '.join(statuses)} |",
        f"| Variable definitions present (MCF triples) | "
        f"{', '.join(f'`{v}` ({len(p)} triples)' for v, p in meta['triples'].items())} |",
        "",
        "## Spot checks",
        "| Variable | Date | Source dataset | CSV | Database |",
        "|---|---|---|---|---|",
        *spot,
        "",
        "## Differences",
        *([f"- {d}" for d in differences] or ["None."]),
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8", newline="\n")

    print(f"source CSV rows:      {len(csv)}")
    print(f"loaded DB rows:       {len(db)}")
    print(f"matching rows:        {matched}")
    print(f"expected from source: {len(src)}")
    for d in differences:
        print("DIFF:", d)
    print(f"{'PASS' if ok else 'FAIL'}: report written to {REPORT.relative_to(ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
