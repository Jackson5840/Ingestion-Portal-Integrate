# Ingestion Portal Integrate Intro

This document is a handoff guide for a new server or a new AI agent working on this repo.

## Project Purpose

`Ingestion-Portal-Integrate` is a Docker Compose application for NeuroMorpho ingestion and release operations. It provides a Flask admin/API service (`are`) with static UI pages for:

- Reading archives into staging.
- Ingesting neurons into the review database.
- Reverting archive/read/ingest state.
- Exporting reviewed archives to main.
- Importing full DB dumps.
- Generating GIFs and PVec/TOPVEC outputs.
- Running Major Release statistics and updating `statistics.jsp`.
- Analyzing access logs and updating Hits/Access by Country JSP datasets.

## Main Services

The Compose stack contains:

- `are`: Flask app and UI on `http://localhost:5000`.
- `mysql`: MySQL 5.7 with review/main/logging databases.
- `postgres`: Postgres 12 for ingestion workflow state.
- `redis`: progress, locks, stop flags, and job logs.
- `swc2pvec`: PVec generation service.
- `similarity-search`: duplicate-detection service.

Main UI pages:

- `http://localhost:5000/ui/index.html` - ingestion process dashboard.
- `http://localhost:5000/ui/giffile.html` - folder-based GIF generation.
- `http://localhost:5000/ui/gifgen.html` - archive GIF generation.
- `http://localhost:5000/ui/topvec.html` - folder-based PVec generation.
- `http://localhost:5000/ui/major-release.html` - Major Release reports/builders.

## Important Paths

Linux/WSL defaults:

```text
Repo: /home/kira/app/Ingestion/Ingestion-Portal-Integrate
Data root: /home/kira/app/Ingestion/data
Export root: /home/kira/app/Ingestion/export
Archive export root: /home/kira/app/Ingestion/dataexport
Major Release root: /home/kira/app/Ingestion/MajorRelease
Major Release JSP: /home/kira/app/Ingestion/MajorRelease/statistics.jsp
Review Tomcat webapp: /home/kira/app/Ingestion/data/apache-tomcat-9.0.118/webapps/neuroMorphoReview
```

Mac defaults in `docker-compose-macos.yml`:

```text
/Users/${USER}/app/Ingestion/data
/Users/${USER}/app/Ingestion/export
/Users/${USER}/app/Ingestion/dataexport
/Users/${USER}/app/Ingestion/MajorRelease
```

Important data subdirectories:

```text
data/readyarchives.csv
data/NMOV8.0-ongoing/
data/NMOV8.7-metadata/
data/archives/
data/metadata/
data/apache-tomcat-9.0.118/webapps/neuroMorphoReview/
```

## Startup

Linux/WSL:

```bash
docker compose up -d --build
docker compose ps
curl -s http://localhost:5000/
```

macOS:

```bash
docker compose -f docker-compose-macos.yml up -d --build
docker compose -f docker-compose-macos.yml ps
curl -s http://localhost:5000/
```

Expected health response:

```text
Ingestion app is up!
```

For macOS, override paths in `.env` if needed:

```env
NMO_DATA_ROOT=/Users/yourname/app/Ingestion/data
NMO_EXPORT_ROOT=/Users/yourname/app/Ingestion/export
NMO_ARCHIVE_EXPORT_ROOT=/Users/yourname/app/Ingestion/dataexport
NMO_MAJOR_RELEASE_ROOT=/Users/yourname/app/Ingestion/MajorRelease
```

## Database Defaults

MySQL:

```text
host: mysql
root password: root
app user/password: nmo / nmo
review DB: nmdbDev
main DB: NeuMO
logging DB: LoggingData
```

Postgres:

```text
host: postgres
database: nmo
user/password: nmo / 100neuralDB
```

Useful shell access:

```bash
docker compose exec mysql mysql -uroot -proot
docker compose exec mysql mysql -unmo -pnmo nmdbDev
docker compose exec postgres psql -U nmo -d nmo
docker compose exec redis redis-cli
```

Use `docker compose -f docker-compose-macos.yml ...` on macOS.

## Code Layout

Core backend:

```text
are-repo/app.py
are-repo/are/io.py
are-repo/are/ingest.py
are-repo/are/ingestdiameter.py
are-repo/are/com.py
are-repo/are/cfg.py
```

Core UI:

```text
are-repo/ui/index.html
are-repo/ui/js/main.js
are-repo/ui/giffile.html
are-repo/ui/js/giffile.js
are-repo/ui/topvec.html
are-repo/ui/js/topvec.js
are-repo/ui/major-release.html
are-repo/ui/js/major-release.js
```

ARE source/UI is copied into the Docker image. After editing `are-repo/app.py`, `are-repo/are/*`, or `are-repo/ui/*`, rebuild ARE:

```bash
python3 -m py_compile are-repo/app.py
node --check are-repo/ui/js/main.js
node --check are-repo/ui/js/major-release.js
docker compose config --quiet
docker compose up -d --build are
```

## Ingestion Workflow

Typical UI flow:

```text
Read Archive -> Ingest Archive -> review in Tomcat -> Export to main
```

`Read Archive`:

- Reads source archive data and metadata.
- Writes local staging copies under `data/archives/<folder>` and `data/metadata/<folder>`.
- Writes Postgres ingestion state.
- Runs duplicate checks.
- Updates review acknowledgement JSP.

`Ingest Archive`:

- Runs as a background job.
- UI polls `/checkingestarchive/<archive>`.
- Has progress/log display.
- Supports an `Ingest Threads` selector with `1`, `2`, `4`, or `8`; default is `1`.
- Multi-thread ingest uses a bounded queue and never submits the whole archive at once.
- Supports graceful Stop.
- Resume starts ingest again and only processes `read`, `warning`, or `error` neurons.
- Skips neurons already present in MySQL review DB and marks them `ingested`.
- Ensures MySQL `archive` row exists before calling the ingest stored procedure.
- Caches repeated region/celltype/publication lookups inside each workflow and retries transient MySQL insert deadlocks.
- Writes per-neuron stage timing into `app.log`; progress log shows total time and slowest stage.
- Review export uses a fast `getneurondata` path and per-thread workflow DB sessions, reducing Postgres lookups from 15 connections to 1 for that read path.
- Copies neuron files to the review Tomcat webapp.

Kummer benchmark from this environment:

```text
Kummer has 81 neurons.
Validated with Revert Kummer -> Read Kummer -> Ingest Kummer.
Threads 1: 30.76 seconds
Threads 4: 22.15 seconds
Threads 8: 20.61 seconds
All three runs matched the pre-optimization logical data baseline with diff_count=0.
```

The current bottleneck is still usually `export_review_mysql_tomcat`, but fast review export reduced that stage from roughly `0.34s/neuron` to about `0.10-0.13s/neuron` on Kummer.

## Revert Archive

`Revert Archive` is destructive for the selected archive's review/staging state. It currently rolls back both `Read Archive` and `Ingest Archive` effects.

It removes:

- MySQL review archive/neuron rows and dependent rows.
- Postgres `export`, `archive`, `ingestion`, `ingested_archives`, and `measurements` rows.
- Local staging folders:
  - `data/archives/<folder>`
  - `data/metadata/<folder>`
- Review Tomcat files:
  - `neuroMorphoReview/dableFiles/<archive_lower>/`
  - `neuroMorphoReview/images/imageFiles/<Archive>/`
  - `neuroMorphoReview/rotatingImages/<neuron>.CNG.gif`

It does not replace `Revert from main`. If an archive has been exported to the main site, use the main-specific revert flow.

## Export To Main

`Export to main` is also a background workflow with progress, stop, and resume-style behavior. It copies review files toward the main webapp root, exports neurons to the main DB, updates upload dates, and generates release JSP/info files.

Important note: Solr/Tomcat main publishing may require manual deployment/server-specific steps. Inspect current code and the target server before giving final production instructions.

## Import Full DB

The UI has an Import Full DB tool. The backend endpoint is:

```text
POST /importdb/
```

Known targets include:

```text
mysql_review
mysql_main
logging_data
postgres
```

`logging_data` creates/imports MySQL `LoggingData`.

Example manual LoggingData import:

```bash
docker compose exec mysql mysql -uroot -proot -e "CREATE DATABASE IF NOT EXISTS LoggingData DEFAULT CHARACTER SET latin1"
docker compose exec -T mysql mysql -uroot -proot LoggingData < /home/kira/app/Ingestion/import/backup-LoggingData-2026-06-22.sql
```

## GIF Generation

Folder GIF UI:

```text
http://localhost:5000/ui/giffile.html
```

Behavior:

- Generates `.CNG.gif` files from SWC folders.
- Supports configurable threads.
- Supports graceful Stop.
- Resume deletes the newest 100 GIFs from the output directory, then skips existing GIFs and continues.

Useful Redis/log checks:

```bash
docker compose exec redis redis-cli keys '*_gif_*'
docker compose exec redis redis-cli lrange '<job>_gif_log' -20 -1
docker compose logs --tail=120 are
```

Suggested GIF threads: start with 8-12; reduce if CPU/disk/memory pressure is high.

## TOPVEC / PVec

TOPVEC UI:

```text
http://localhost:5000/ui/topvec.html
```

Backend flow:

1. Clear swc2pvec workspace.
2. Upload SWC files.
3. Call PVec calculation with selected thread count.
4. Write `.CNG.pvec` output files.

There is a Redis `topvec_lock` to avoid concurrent TOPVEC jobs.

Suggested TOPVEC threads: start with 1-4.

## Major Release

Major Release UI:

```text
http://localhost:5000/ui/major-release.html
```

Main features:

- Downloads by Animal Species.
- Downloads by Cell Type.
- Downloads by Archive.
- Downloads by Brain Region.
- Run All.
- Build DownloadsBy into `statistics.jsp`.
- Revert `statistics.jsp` from backup.
- Downloads per Quarter Run/Build/Revert.
- Hit by log folder analysis.

`DownloadsBy` reports query `LoggingData.logdownload` joined with `NeuMO.neuron` dimensions. `No. of Cells` is all-time full cell count from `NeuMO.neuron`; it is not filtered by date.

`Build DownloadsBy` does not run SQL by itself. It uses already displayed report rows and updates JSP datasets:

```text
speciesDataSet
cellDataSet
archiveDataSet
brainRegionDataSet
```

It replaces cell counts, adds new downloads to existing cumulative values, and recalculates averages.

`Downloads per Quarter` can run SQL for a chosen date range and build into JSP Highcharts series:

```text
name: 'Auxillary Files'
name: 'Neuron Files'
```

The quarter array starts at `2006Q3`.

`Hit by log`:

- Reads Apache access log `.txt` files.
- Counts only HTTP `200`.
- Excludes localhost/loopback.
- Writes:
  - `MajorRelease/perQuarter.xlsx`
  - `MajorRelease/AccessCountry.xlsx`
- Updates JSP cumulatively:
  - Adds hits into `name: 'Hits'`.
  - Adds country values into `var countryDataSet`.

Country lookup uses `ip-api.com` by default; failed/private/local IPs are grouped as `Unknown IP`.

## Common Debugging

Service health:

```bash
docker compose ps
docker compose logs --tail=120 are
docker compose logs --tail=120 mysql
docker compose logs --tail=120 postgres
curl -s http://localhost:5000/
```

Archive status:

```bash
curl -s http://localhost:5000/getarchives/
docker compose exec postgres psql -U nmo -d nmo -c "select archive,status,count(*) from ingestion group by archive,status order by archive,status;"
docker compose exec mysql mysql -uroot -proot nmdbDev -e "select archive_id, archive_name from archive order by archive_id desc limit 10;"
```

Ingest job status:

```bash
curl -s http://localhost:5000/checkingestarchive/Kummer
docker compose exec redis redis-cli keys '*Kummer*ingest*'
docker compose logs --tail=200 are
```

TOPVEC status:

```bash
docker compose exec redis redis-cli get topvec_lock
docker compose exec redis redis-cli keys '*_pvec_*'
docker compose logs --tail=120 swc2pvec
```

UI changed but browser does not show it:

```bash
docker compose up -d --build are
curl -s http://localhost:5000/ui/index.html | head
```

## Safety Notes For AI Agents

- Read code before changing behavior; this repo has many fragile workflow assumptions.
- Use `rg` for search.
- Use `apply_patch` for manual file edits.
- Do not revert user changes.
- Do not run destructive git commands unless explicitly requested.
- Do not delete generated outputs unless the user asks.
- Be careful with `Revert Archive`; it intentionally deletes DB rows and review webapp files.
- Test JSP-mutating functions against a temporary copy unless the user expects a real write.
- After ARE changes, rebuild `are`; source is copied into the image, not bind-mounted.
