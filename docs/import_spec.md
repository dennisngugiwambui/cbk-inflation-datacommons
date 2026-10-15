# Import specification: Kenya inflation rates (CBK) into a custom Data Commons

Written before the pipeline code. Decisions taken after inspecting the source are marked **(after inspection)**.

## 1. Source

| Item                       | Value                                                                                                                                                 |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Page                       | [https://www.centralbank.go.ke/inflation-rates/](https://www.centralbank.go.ke/inflation-rates/)                                                       |
| Publisher                  | Central Bank of Kenya (CBK)                                                                                                                           |
| Original data source       | Kenya National Bureau of Statistics (KNBS), as stated on the page ("(iii) Source: Kenya National Bureau of Statistics")                               |
| Downloaded                 | 2026-10-15 (see `source/download_date.txt`)                                                                                                         |
| Licence                    | Public data published on the CBK website. No explicit open licence is stated on the page, so CBK's website terms of use apply. Attribute CBK and KNBS |
| Update frequency           | Monthly. The latest month in this copy is September 2026                                                                                              |
| Coverage of the full table | January 2005 to September 2026, 262 rows                                                                                                              |

### Files kept in `source/`

| File                                   | What it is                                                                                                                  | How it is used                                                           |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `Inflation Rates _ CBK.html`         | Page saved from the browser                                                                                                 | Definitions and table header only. It holds just 2 data rows (see below) |
| `Inflation Rates.xlsx`               | The full table (262 rows) from the page's **Excel** button                                                            | Compared row by row with the live page                                   |
| `cbk_inflation_live_2026-10-15.html` | The live page fetched from the URL by `src/fetch_live.py`, saved unchanged                                                | Parsed with `pandas.read_html`: all 262 rows                           |
| `cbk_inflation_final.csv`            | **Final dataset**: the live page's table after the comparison, one row per month, sorted, values exactly as published | **Input to `src/pipeline.py`** and to the readback check         |
| `Inflation Rates _ CBK_files/`       | Page assets saved by the browser                                                                                            | Not used                                                                 |

**(after inspection)** The table on the page is a paginated DataTable. A browser "Save page as" only keeps the rows
on the visible page, so the saved HTML holds just 2 data rows (January and February 2005) and says
"Showing 261 to 262 of 262 entries". That is not enough data. So:

1. The live URL was fetched (`python src/fetch_live.py`). The page as the server sends it contains every row (the
   table is only hidden with `display: none` until JavaScript paginates it). The fetched copy is kept in `source/`.
2. Its table (262 rows) was compared row by row, on Year + Month, with the Excel export (262 rows). Result: 261
   distinct months, **0 differences**. The only repeat, April 2019, is identical in both
   (`docs/source_comparison.md`).
3. The agreed table was saved as `source/cbk_inflation_final.csv` (261 months, Jan 2005 to Sep 2026). Everything
   after this point uses that file.

### Definitions (quoted from the page)

- **12-month inflation**: "normally considered as inflation rate, is defined as the percentage change in the monthly
  consumer price index (CPI). For example, the 12-month inflation rate for November 2017 is the percentage change in
  the CPI of November 2017 and November 2016."
- **Annual average inflation**: "is the percentage change in the annual average consumer price index (CPI) of the
  corresponding months e.g. November 2017 and November 2016."

## 2. Places

| Place | DCID            | Check                                                                                                                                      |
| ----- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Kenya | `country/KEN` | Existing Data Commons place. Confirmed with the Data Commons API (`/v2/node`): name "Kenya", typeOf `Country`. No new place is created |

Every observation is national. There are no sub-national rows in the source.

## 3. Variables

| Variable DCID                       | Name                                       | Definition                                                                                                                        | Unit        | Source column                |
| ----------------------------------- | ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- | ----------- | ---------------------------- |
| `cbk/InflationRate_12Month`       | 12-month inflation rate (Kenya, CPI)       | Percentage change in the monthly CPI compared with the same month of the previous year                                            | `Percent` | `12-Month Inflation`       |
| `cbk/InflationRate_AnnualAverage` | Annual average inflation rate (Kenya, CPI) | Percentage change in the average CPI of the 12 months ending in the month, compared with the average of the 12 months before that | `Percent` | `Annual Average Inflation` |

Columns are matched **by header text, never by position**. On the page, Annual Average comes before 12-Month.

### Graph modelling (MCF), with existing DCIDs reused

All of these DCIDs were checked against the live Data Commons API on 2026-10-15.

| Property                                      | Value                                                | Why                                                                                                                                                                         |
| --------------------------------------------- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `typeOf`                                    | `StatisticalVariable`                              | exists                                                                                                                                                                      |
| `populationType`                            | `EconomicActivity`                                 | Base-graph convention for CPI inflation (e.g. `Mean_Inflation_EconomicActivity_ConsumerPriceIndex_GeneralSector`). `Country` is the place type, not the population type |
| `measuredProperty`                          | `inflation`                                        | exists (Property). **`InflationRate` does not exist** in Data Commons, so it is not used                                                                            |
| `statType`                                  | `measuredValue`                                    | A statType must be a StatType such as `measuredValue`. `Percent` is a unit, not a statType                                                                              |
| `constraintProperties` / `activitySource` | `activitySource` = `ConsumerPriceIndex`          | exists; same as the base-graph CPI variables                                                                                                                                |
| `comparisonPeriod`                          | `YearOnChange` (12-month only)                     | exists (`ComparisonPeriodEnum`, "Year On Change")                                                                                                                         |
| `measurementQualifier`                      | `Monthly` (12-month) / `Annual` (annual average) | both exist (`StatAccumulationPeriodEnum`). This is what tells the two variables apart: a one-month CPI against a twelve-month average CPI                                 |
| `unit`                                      | `Percent`                                          | exists (`UnitOfMeasure`)                                                                                                                                                  |

The unit is also stated on every observation (`unit` column in the CSV = `Percent`).

## 4. Scope

- **In scope:** Kenya (`country/KEN`), monthly, **January 2015 onwards** (to September 2026 in this copy), both variables.
- **Out of scope:** earlier years (2005–2014; the table has them, and section 7 shows how to add them),
  CPI index levels, CPI components, sub-national data.
- Expected size: 141 months (Jan 2015 to Sep 2026) × 2 variables = **282 observations**, less any missing values.

## 5. Output format (Data Commons custom data, `variablePerRow`)

`output/observations.csv`, one observation per row:

| Column       | Example                       | Rule                                                        |
| ------------ | ----------------------------- | ----------------------------------------------------------- |
| `entity`   | `country/KEN`               | constant                                                    |
| `variable` | `cbk/InflationRate_12Month` | from the source column                                      |
| `date`     | `2015-01`                   | `YYYY-MM`, built from Year and the month name             |
| `value`    | `5.53`                      | the published number, unchanged (no rounding, no rescaling) |
| `unit`     | `Percent`                   | constant                                                    |

Plus `output/config.json` (how the loader reads the CSV, and the source/provenance) and `output/variables.mcf`
(the two variable definitions). These are loaded with the Data Commons data container
`gcr.io/datcom-ci/datacommons-data:stable`, which writes `output/datacommons/datacommons.db` (SQLite).
The standalone importer (`github.com/datacommonsorg/import`) is **not** used.

## 6. Data rules

- **Missing values:** a blank or non-numeric cell is missing. A missing value gets **no row** in the CSV, so the loader
  never sees it. It is never written as `0`. (This copy has no missing cells in scope.)
- **Repeated header rows:** any row whose cells equal the header (`Year`, `Month`, ...) is skipped.
- **Duplicates (after inspection):** April 2019 appears twice with identical values (4.91 / 6.58). An exact duplicate
  is dropped and logged. If a year-month ever appears twice with **different** values, the pipeline stops, because
  choosing one would be a guess.
- **Footnotes / revisions:** the table has no footnote markers (no `*`, `p`, `r` or superscripts). The values are taken
  as currently published. If CBK revises a month, re-downloading and re-running replaces the old value; past values
  are not kept.
- **Validation:** month names must be one of the 12 English month names; year must be 4 digits; values must be numbers
  between -50 and 100 (a sanity range for Kenyan CPI inflation; anything outside stops the pipeline for a human look).

## 7. Extending

- More years: change `START_DATE = "2015-01"` in `src/pipeline.py` (or run `python src/pipeline.py --start 2010-01`).
- More variables: add the column to `VARIABLES` in `src/pipeline.py` and `src/readback.py`. The MCF node is written
  from the same entry.
