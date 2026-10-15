# Kenya Inflation Data Commons Import

Loads Kenya's monthly inflation rates, as published by the Central Bank of Kenya (source: KNBS), into a
custom Data Commons SQLite database with the official data container. A readback check then confirms that the
database holds the published numbers.

- **Place:** `country/KEN` (existing Data Commons place)
- **Variables:** `cbk/InflationRate_12Month`, `cbk/InflationRate_AnnualAverage` (unit `Percent`)
- **Scope:** monthly, January 2015 to September 2026: 141 months × 2 variables = **282 observations**, all loaded,
  readback 282/282 matching.

## One command to run everything

Git Bash / macOS / Linux / Windows `cmd`:

```bash
python src/pipeline.py && python src/load.py && python src/readback.py
```

Note that you have to be in the main folder for you to run this command. The root folder for the project

Windows PowerShell 5.1 (it has no `&&`): (Ensure also you are in the root folder not inside the src/ or source/ or any other folder)

```powershell
python src/pipeline.py; if ($?) { python src/load.py }; if ($?) { python src/readback.py }
```

`src/load.py` runs exactly this container command and saves the log (with the API key masked):

```bash
docker run --rm --platform linux/amd64 --env-file env.list -e INPUT_DIR=/data -e OUTPUT_DIR=/data \
  -v "$(pwd)/output:/data" gcr.io/datcom-ci/datacommons-data:stable 2>&1 | tee output/load.log
```

Expected output (my run). The loader ends with `Runner finished successfully` (282 observations), and the readback
prints `PASS` with 282/282 rows matching:

![Output of the load and readback: Runner finished successfully, 282 observations, readback PASS](source/Screenshot%202026-10-15%20104729.png)

`output/` is mounted at `/data` in the container, so `INPUT_DIR`/`OUTPUT_DIR` are the same short path on every
operating system and always match the mount.

## First-time setup

1. Python 3.10+, then `pip install -r requirements.txt`.
2. Docker Desktop running, and `docker pull gcr.io/datcom-ci/datacommons-data:stable` (about 0.9 GB download).
   On Windows, if `docker` is "not recognised", Docker Desktop's folder is not on PATH. `src/load.py` finds it
   anyway. To fix the terminal, run this in PowerShell and open a new window:

   ```powershell
   [Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path","User") + ";$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin", "User")
   ```

   Expected result (Docker 29.7.2, loader image pulled):

   ![docker --version and docker pull of the Data Commons data container](source/b8e33fbf-da0c-4b3a-a380-f82c437dca98.jpg)

3. A Data Commons API key from [https://apikeys.datacommons.org](https://apikeys.datacommons.org). Copy `env.list.example` to `env.list` and put the
   key in it. `env.list` is git-ignored; never commit it.

## Deliverables

| Deliverable                              | Location                                                                           |
| ---------------------------------------- | ---------------------------------------------------------------------------------- |
| Import specification                     | `docs/import_spec.md`                                                              |
| Source fetch + comparison, final dataset | `src/fetch_live.py`, `docs/source_comparison.md`, `source/cbk_inflation_final.csv` |
| Pipeline code                            | `src/pipeline.py` (and `src/load.py`, the loader wrapper)                          |
| Generated loader input                   | `output/observations.csv`, `output/config.json`, `output/variables.mcf`            |
| Loader log                               | `output/load.log`                                                                  |
| Readback check                           | `src/readback.py`, `docs/readback_report.md`                                       |
| Handover note                            | `docs/handover.md`                                                                 |
| Learning log                             | `docs/learning_log.md`                                                             |
| Source copy                              | `source/` (see `source/download_date.txt`)                                         |

## Repository structure

The project was laid out with these commands first, before any code was written:

```bash
mkdir kenya-inflation-dc
cd kenya-inflation-dc

mkdir -p source docs src output
touch README.md
touch docs/import_spec.md docs/handover.md docs/learning_log.md docs/readback_report.md
touch src/pipeline.py src/readback.py
touch .gitignore
```

The repository now looks like this (the folder is named `cbk-inflation-datacommons` here). The files from the
commands above are marked ★; everything else was added while building:

```
cbk-inflation-datacommons/
├── README.md ★                       this file
├── .gitignore ★                      env.list, output/datacommons/, __pycache__/, *.pyc
├── .gitattributes                    LF line endings; .xlsx/.db binary
├── requirements.txt                  pandas, lxml, openpyxl
├── env.list.example                  template for env.list (the real env.list holds the API key, git-ignored)
├── source/ ★
│   ├── Inflation Rates _ CBK.html    page saved from the browser (only 2 rows: not enough data)
│   ├── Inflation Rates _ CBK_files/  its saved assets (not used)
│   ├── Inflation Rates.xlsx          full table from the page's Excel button
│   ├── cbk_inflation_live_2026-10-15.html   live page fetched from the URL (all 262 rows)
│   ├── cbk_inflation_final.csv       FINAL DATASET: live page checked against the Excel export
│   ├── b8e33fbf-da0c-4b3a-a380-f82c437dca98.jpg   screenshot: docker --version and docker pull
│   ├── Screenshot 2026-10-15 104729.png        screenshot: load + readback output (expected / my output)
│   └── download_date.txt             what was downloaded, when, and its role
├── src/ ★
│   ├── fetch_live.py                 fetch live page, compare with Excel, write final dataset
│   ├── pipeline.py ★                 final dataset -> observations.csv, config.json, variables.mcf
│   ├── load.py                       runs the Data Commons data container (Docker)
│   └── readback.py ★                 database vs CSV vs source, writes the readback report
├── output/ ★
│   ├── observations.csv              282 observations
│   ├── config.json                   how the loader reads the CSV; source and provenance
│   ├── variables.mcf                 the two statistical variables
│   ├── load.log                      loader log (API key masked)
│   └── datacommons/                  generated SQLite database (git-ignored)
└── docs/ ★
    ├── import_spec.md ★              import specification
    ├── source_comparison.md          live page vs Excel export: 0 differences
    ├── readback_report.md ★          readback result: 282/282 match
    ├── handover.md ★                 handover note
    └── learning_log.md ★             learning log
```

## Notes

- **Source data.** The page I saved from the browser held only the rows on screen (2 of 262) (I realized this after opening it on my laptop), which is not enough.
  So the live URL was fetched (`src/fetch_live.py`). The server's page contains all 262 rows, and they were compared
  row by row with the page's Excel export: 261 months, 0 differences. The result is the **final dataset**,
  `source/cbk_inflation_final.csv`, which the pipeline and the readback use. Details in `docs/source_comparison.md`.
- **Refreshing the source** (e.g. a new month): `python src/fetch_live.py` downloads today's page, compares it with
  `source/Inflation Rates.xlsx` (export a fresh one from the page first) and rewrites the final dataset only if the
  two agree. Then run the one command.
- Don't open and re-save `output/observations.csv` in Excel. It rewrites numbers and line endings. Re-run the pipeline
  instead.
