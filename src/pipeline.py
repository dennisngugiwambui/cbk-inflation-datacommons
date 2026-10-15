"""Build Data Commons loader input from the final CBK inflation dataset.

Reads   source/cbk_inflation_final.csv  (written by src/fetch_live.py: the live CBK page, checked
                                         row by row against the saved Excel export)
Writes  output/observations.csv, output/config.json, output/variables.mcf

Idempotent: the outputs are rebuilt from the source on every run, sorted, with no duplicates.

Usage:
    python src/pipeline.py                 # January 2015 onwards
    python src/pipeline.py --start 2010-01 # include earlier months
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SOURCE_FINAL = ROOT / "source" / "cbk_inflation_final.csv"
OUTPUT_DIR = ROOT / "output"

START_DATE = "2015-01"  # first month in scope (YYYY-MM)

ENTITY = "country/KEN"
UNIT = "Percent"
SOURCE_URL = "https://www.centralbank.go.ke/inflation-rates/"
SOURCE_NAME = "Central Bank of Kenya"
PROVENANCE = "CBK Inflation Rates"

COL_YEAR, COL_MONTH = "Year", "Month"
# Source column -> variable definition. Columns are matched by header text, never by position.
VARIABLES = {
    "12-Month Inflation": {
        "dcid": "cbk/InflationRate_12Month",
        "name": "12-month inflation rate (Kenya, CPI)",
        "description": "Percentage change in the monthly consumer price index (CPI) compared with the same "
                       "month of the previous year. Published by the Central Bank of Kenya; "
                       "source: Kenya National Bureau of Statistics.",
        "extra": {"measurementQualifier": "dcid:Monthly", "comparisonPeriod": "dcid:YearOnChange"},
    },
    "Annual Average Inflation": {
        "dcid": "cbk/InflationRate_AnnualAverage",
        "name": "Annual average inflation rate (Kenya, CPI)",
        "description": "Percentage change in the annual average consumer price index (CPI) of the corresponding "
                       "months, i.e. the average CPI of the 12 months ending in the month compared with the "
                       "average of the previous 12 months. Published by the Central Bank of Kenya; "
                       "source: Kenya National Bureau of Statistics.",
        "extra": {"measurementQualifier": "dcid:Annual"},
    },
}
EXPECTED_COLUMNS = [COL_YEAR, COL_MONTH, *VARIABLES]

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}
VALUE_RANGE = (-50.0, 100.0)  # sanity range for Kenyan CPI inflation, in percent

log = logging.getLogger("pipeline")


class PipelineError(Exception):
    """A problem with the source that needs a human decision."""


def clean_table(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """Normalise headers/cells, skip repeated header rows and blank rows, keep the expected columns."""
    df = df.copy()
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        raise PipelineError(f"{label}: columns {missing} not found; got {list(df.columns)}")
    df = df[EXPECTED_COLUMNS].astype("string").apply(lambda s: s.str.strip())

    is_header = (df[COL_YEAR] == COL_YEAR) & (df[COL_MONTH] == COL_MONTH)
    if is_header.any():
        log.info("%s: skipped %d repeated header row(s)", label, int(is_header.sum()))
    is_blank = df[COL_YEAR].isna() & df[COL_MONTH].isna()
    return df[~is_header & ~is_blank].reset_index(drop=True)


def read_source(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise PipelineError(f"{path.name} not found: run python src/fetch_live.py first")
    try:
        raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception as exc:
        raise PipelineError(f"could not read {path}: {exc}") from exc
    df = clean_table(raw.replace("", pd.NA), path.name)
    log.info("%s: %d data rows", path.name, len(df))
    return df


def to_long(df: pd.DataFrame, start: str) -> pd.DataFrame:
    """Validate, build YYYY-MM dates, filter, de-duplicate and pivot to one observation per row."""
    bad_month = ~df[COL_MONTH].isin(list(MONTHS))
    bad_year = ~df[COL_YEAR].fillna("").str.fullmatch(r"\d{4}")
    if (bad_month | bad_year).any():
        raise PipelineError(f"unrecognised year/month:\n{df[bad_month | bad_year]}")
    df = df.assign(date=df[COL_YEAR] + "-" + df[COL_MONTH].map(MONTHS).map("{:02d}".format))

    df = df[df["date"] >= start]  # scope: months from START_DATE onwards

    dup = df.duplicated(["date"], keep=False)
    if dup.any():
        exact = df[dup].drop_duplicates()
        if exact["date"].duplicated().any():
            raise PipelineError(f"same month published with different values:\n{df[dup]}")
        for d in exact["date"]:
            log.warning("duplicate row for %s with identical values: kept one", d)
        df = df.drop_duplicates()

    long = df.melt(id_vars=["date"], value_vars=list(VARIABLES), var_name="column", value_name="raw")
    long["value"] = pd.to_numeric(long["raw"], errors="coerce")
    missing = long["value"].isna()
    for _, r in long[missing].iterrows():
        log.warning("missing/non-numeric value %r for %s %s: no row written", r["raw"], r["column"], r["date"])
    long = long[~missing]

    lo, hi = VALUE_RANGE
    out_of_range = (long["value"] < lo) | (long["value"] > hi)
    if out_of_range.any():
        raise PipelineError(f"values outside {VALUE_RANGE}:\n{long[out_of_range]}")

    long = long.assign(
        entity=ENTITY,
        variable=long["column"].map(lambda c: VARIABLES[c]["dcid"]),
        value=long["value"].map(lambda v: format(v, ".15g")),  # the published number, no rounding
        unit=UNIT,
    )
    return long[["entity", "variable", "date", "value", "unit"]].sort_values(["variable", "date"]).reset_index(drop=True)


def build_config() -> dict:
    return {
        "inputFiles": {
            "observations.csv": {
                "format": "variablePerRow",
                "provenance": PROVENANCE,
                "entityType": "Country",
                "columnMappings": {c: c for c in ["variable", "entity", "date", "value", "unit"]},
            }
        },
        "sources": {
            SOURCE_NAME: {
                "url": SOURCE_URL,
                "provenances": {PROVENANCE: SOURCE_URL},
            }
        },
    }


def build_mcf() -> str:
    nodes = []
    for v in VARIABLES.values():
        lines = [
            f"Node: dcid:{v['dcid']}",
            "typeOf: dcid:StatisticalVariable",
            f"name: {json.dumps(v['name'])}",
            f"description: {json.dumps(v['description'])}",
            "populationType: dcid:EconomicActivity",
            "measuredProperty: dcid:inflation",
            "statType: dcid:measuredValue",
            "constraintProperties: dcid:activitySource",
            "activitySource: dcid:ConsumerPriceIndex",
            *(f"{k}: {val}" for k, val in v["extra"].items()),
            f"unit: dcid:{UNIT}",
        ]
        nodes.append("\n".join(lines))
    return "\n\n".join(nodes) + "\n"


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default=START_DATE, help=f"first month to include, YYYY-MM (default {START_DATE})")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", args.start):
        log.error("--start must be YYYY-MM, got %r", args.start)
        return 2

    try:
        data = read_source(SOURCE_FINAL)
        obs = to_long(data, args.start)
    except PipelineError as exc:
        log.error("%s", exc)
        return 1
    if obs.empty:
        log.error("no observations from %s onwards", args.start)
        return 1

    OUTPUT_DIR.mkdir(exist_ok=True)
    obs.to_csv(OUTPUT_DIR / "observations.csv", index=False, lineterminator="\n")
    write_text(OUTPUT_DIR / "config.json", json.dumps(build_config(), indent=2) + "\n")
    mcf = build_mcf()
    write_text(OUTPUT_DIR / "variables.mcf", mcf)

    log.info("months %s to %s", obs["date"].min(), obs["date"].max())
    for dcid, n in obs.groupby("variable").size().items():
        log.info("  %s: %d observations", dcid, n)
    print(f"output/observations.csv: {len(obs)} rows")
    print(f"output/config.json: 1 input file, 1 source")
    print(f"output/variables.mcf: {mcf.count('Node: ')} nodes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
