"""Fetch the live CBK inflation page, compare it with the saved Excel export, and save the final dataset.

Why: a browser "Save page as" keeps only the rows on the visible page of the paginated table (2 of 262 rows
in source/Inflation Rates _ CBK.html). The page as sent by the server contains every row.

Steps
  1. Download https://www.centralbank.go.ke/inflation-rates/ and save it unchanged as
     source/cbk_inflation_live_<YYYY-MM-DD>.html  (or, with --html, re-use a copy already saved).
  2. Parse the table with pandas.read_html.
  3. Compare it row by row (Year + Month) with source/Inflation Rates.xlsx.
  4. If they agree, write the final dataset source/cbk_inflation_final.csv (all months, one row per month,
     sorted) and the comparison report docs/source_comparison.md.
     If any value differs, or a month is in one and not the other, stop: that needs a human decision.

Usage:
    python src/fetch_live.py                                            # download today's page
    python src/fetch_live.py --html source/cbk_inflation_live_2026-10-15.html   # re-use a saved copy
"""
from __future__ import annotations

import argparse
import logging
import sys
import urllib.request
from datetime import date
from io import StringIO
from pathlib import Path

import pandas as pd

from pipeline import COL_MONTH, COL_YEAR, EXPECTED_COLUMNS, MONTHS, SOURCE_URL, VARIABLES, PipelineError, clean_table

ROOT = Path(__file__).resolve().parent.parent
SOURCE_XLSX = ROOT / "source" / "Inflation Rates.xlsx"
FINAL_CSV = ROOT / "source" / "cbk_inflation_final.csv"
REPORT = ROOT / "docs" / "source_comparison.md"
KEY = [COL_YEAR, COL_MONTH]

log = logging.getLogger("fetch_live")


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (cbk-inflation-datacommons)"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read()
    dest.write_bytes(body)
    log.info("downloaded %s (%d bytes) -> %s", url, len(body), dest.relative_to(ROOT))


def parse_html(path: Path) -> pd.DataFrame:
    text = path.read_text(encoding="utf-8", errors="replace")
    # the server sends the table with style="display: none" (JavaScript shows it), so include hidden elements
    tables = pd.read_html(StringIO(text), match="12-Month Inflation", displayed_only=False,
                          converters={i: str for i in range(len(EXPECTED_COLUMNS))})
    for t in tables:
        if isinstance(t.columns, pd.MultiIndex):
            t.columns = t.columns.get_level_values(0)
        try:
            return clean_table(t, path.name)
        except PipelineError:
            continue
    raise PipelineError(f"{path.name}: no table with columns {EXPECTED_COLUMNS}")


def compare(live: pd.DataFrame, xlsx: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Outer-join on Year+Month (duplicates removed first) and list every disagreement."""
    m = live.drop_duplicates().merge(xlsx.drop_duplicates(), on=KEY, how="outer",
                                     suffixes=("_live", "_xlsx"), indicator=True)
    diffs = []
    for _, r in m.iterrows():
        k = f"{r[COL_MONTH]} {r[COL_YEAR]}"
        if r["_merge"] == "left_only":
            diffs.append(f"{k}: on the live page but not in the Excel export")
        elif r["_merge"] == "right_only":
            diffs.append(f"{k}: in the Excel export but not on the live page")
        else:
            for col in VARIABLES:
                a, b = pd.to_numeric(r[f"{col}_live"], errors="coerce"), pd.to_numeric(r[f"{col}_xlsx"], errors="coerce")
                if not (a == b or (pd.isna(a) and pd.isna(b))):
                    diffs.append(f"{k}, {col}: live page {r[f'{col}_live']} vs Excel export {r[f'{col}_xlsx']}")
    return m, diffs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--html", type=Path, help="use this saved copy of the live page instead of downloading")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        if args.html:
            html_path = args.html.resolve()
        else:
            html_path = ROOT / "source" / f"cbk_inflation_live_{date.today().isoformat()}.html"
            download(SOURCE_URL, html_path)
        live = parse_html(html_path)
        xlsx = clean_table(pd.read_excel(SOURCE_XLSX, dtype=str), SOURCE_XLSX.name)
    except Exception as exc:
        log.error("%s", exc)
        return 1

    dup_live = live[live.duplicated(keep=False)].drop_duplicates()
    conflicting = live.drop_duplicates()[live.drop_duplicates().duplicated(KEY, keep=False)]
    if not conflicting.empty:
        log.error("live page has the same month with different values:\n%s", conflicting)
        return 1

    merged, diffs = compare(live, xlsx)
    matched = int((merged["_merge"] == "both").sum()) - sum(", " in d for d in diffs)
    log.info("live page: %d rows; Excel export: %d rows; months compared: %d; differences: %d",
             len(live), len(xlsx), len(merged), len(diffs))

    final = live.drop_duplicates().copy()
    final.insert(0, "date", final[COL_YEAR] + "-" + final[COL_MONTH].map(MONTHS).map("{:02d}".format))
    final = final.sort_values("date").reset_index(drop=True)

    lines = [
        "# Source comparison: live CBK page vs saved Excel export",
        "",
        f"Generated by `python src/fetch_live.py` on {date.today().isoformat()}.",
        "",
        "**Why:** the page saved from the browser (`source/Inflation Rates _ CBK.html`) holds only 2 of the table's",
        "262 rows, because the table is paginated in the browser and only the visible page is saved. The page as",
        f"sent by the server (<{SOURCE_URL}>) contains every row, so it was fetched and compared with the Excel",
        "export before being used.",
        "",
        "| | Rows |",
        "|---|---|",
        f"| Live page (`{html_path.relative_to(ROOT).as_posix()}`) | {len(live)} |",
        f"| Excel export (`source/Inflation Rates.xlsx`) | {len(xlsx)} |",
        f"| Distinct months compared | {len(merged)} |",
        f"| Months where both values agree | {matched} |",
        f"| Differences | {len(diffs)} |",
        f"| Months covered | {final['date'].min()} to {final['date'].max()} |",
        "",
        "**Duplicates:** " + (", ".join(f"{r[COL_MONTH]} {r[COL_YEAR]}" for _, r in dup_live.iterrows())
                              + " appears twice on the live page with identical values; kept once in the final dataset."
                              if not dup_live.empty else "none."),
        "",
        "## Differences",
        *([f"- {d}" for d in diffs] or ["None: the live page and the Excel export hold the same values for every month."]),
        "",
        "## Result",
        (f"Final dataset written to `{FINAL_CSV.relative_to(ROOT).as_posix()}` ({len(final)} months, one row per month, "
         "values exactly as published). `src/pipeline.py` reads this file." if not diffs else
         "Final dataset **not** written: resolve the differences above first."),
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8", newline="\n")

    if diffs:
        for d in diffs:
            log.error("DIFF: %s", d)
        log.error("sources disagree; final dataset not written (see %s)", REPORT.relative_to(ROOT))
        return 1
    final.to_csv(FINAL_CSV, index=False, lineterminator="\n")
    print(f"{FINAL_CSV.relative_to(ROOT)}: {len(final)} months ({final['date'].min()} to {final['date'].max()})")
    print(f"comparison report: {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
