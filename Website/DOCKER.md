# Docker / Compose setup

## Answers (design choices)

### 1. Move all scripts into `Website/backend`?

**Recommendation: no git-move.** Keep `Exeption Programs/` and `Plaza_db_update/` as siblings of `Website/` (current layout). The Docker image **copies** them next to the backend under `/app` with the same relative paths.

Why not physically move into `backend/`?

- Huge history churn and broken local absolute paths
- Scripts are shared with non-website runs
- Same runtime result via `TOLL_REPO_ROOT` / `EXCEPTION_PROGRAMS_ROOT` / `PLAZA_DB_UPDATE_ROOT`

If you later want them under `backend/programs/`, set those env vars — catalogs already honor them.

### 2. Fat image + Selenium — does scraping run in Docker?

**Yes.** Two modes, both controlled only from `Website/backend/.env`
(via `Exeption Programs/common/selenium_scrape_config.py`):

| Mode | When | How |
|------|------|-----|
| **Local Chrome** | `SCRAPE_USE_GRID=0` | Chrome runs **inside the backend container** (fat image). No Grid containers needed. |
| **Selenium Grid** | `SCRAPE_USE_GRID=1` | Backend opens remote sessions on an existing **selenium-hub**; Chrome nodes can be auto-spawned or started via Compose. |

In `backend/.env`:

```bash
SCRAPE_ENABLED=1
SCRAPE_USE_GRID=1
SCRAPE_GRID_URL=http://localhost:4444/wd/hub   # host Python; use host.docker.internal from Docker
SCRAPE_MAX_NODES=3                              # Chrome node containers to auto-start
SCRAPE_MAX_CONCURRENCY=3                        # parallel scrape sessions
SCRAPE_AUTO_MANAGE_NODES=1                      # spawn auto-chrome-node-* against existing hub
SCRAPE_HEADLESS=1
```

**Auto nodes (recommended with an existing hub):** start/keep `selenium-hub` running, set
`SCRAPE_AUTO_MANAGE_NODES=1`. Jobs spawn `SCRAPE_MAX_NODES` Chrome containers on the
`selenium-grid` Docker network, scrape with `SCRAPE_MAX_CONCURRENCY` workers, then remove
the nodes. Backend needs Docker socket access for this (Compose mounts it when Grid is used).

**Static Compose nodes (optional):** leave auto-manage off and start the profile:

```bash
docker compose --profile selenium up --build
```

If the hub runs on the **host** and jobs run in Docker, set
`SCRAPE_GRID_URL=http://host.docker.internal:4444/wd/hub` (Docker Desktop).

### 5. Multithreading for jobs?

**No parallel ETL jobs.** One gunicorn worker + the existing single job-queue thread is correct. Parallel pandas/Excel jobs on large files fight for RAM and cause OOMs. Multithreading for *HTTP* (gunicorn `--threads 4`) is fine; job execution stays serial.

### 8. API + worker in one process — why?

The Flask app already starts `start_exception_job_worker` in a daemon thread. One container with **gunicorn `--workers 1`** means:

- No double-claim of the same queued job
- Shared DB session patterns stay simple
- Matches “one heavy job at a time” on a single host

Scale later with a dedicated `worker` service + DB lock if needed — not now.

### 9–10. Frontend routing + Linux

- Frontend build uses empty `VITE_API_URL` so the browser calls `/api/...`
- nginx proxies `/api/` → `backend:5000`
- Process kill uses `taskkill` on Windows and `killpg` on Linux

---

## Quick start

1. Ensure secrets live in **one** file: `Website/backend/.env`  
   (see `backend/.env.example`; keys from old `Exeption Programs/.env` / `E4/.env` were merged if missing).

2. From `Website/`:

```bash
docker compose up --build
```

3. Open **http://localhost:8080** (frontend). Backend direct: **http://localhost:5000**.

---

## Volume configuration steps

Compose already declares named volumes for job scratch folders. First boot creates them empty; the image still contains script source.

### Inspect volumes

```bash
docker volume ls | findstr toll
docker volume inspect toll-analytics_e4_jobs
```

### Where data lives (Docker Desktop / WSL)

Docker stores named volumes under its VM disk. You normally **do not** browse them as Windows folders. To inspect from a container:

```bash
docker compose exec backend ls -la "/app/Exeption Programs/E4/jobs"
docker compose exec backend ls -la /app/Plaza_db_update/jobs
```

### Optional: bind-mount host folders instead

If you want scratch on a specific host path (easier cleanup on Windows):

1. Create folders, e.g. `D:\toll-docker-data\e4_jobs`, …
2. In `docker-compose.yml`, replace a named volume with:

```yaml
- D:/toll-docker-data/e4_jobs:/app/Exeption Programs/E4/jobs
```

3. `docker compose up -d` again.

### Clear scratch after failed experiments

```bash
docker compose down
docker volume rm toll-analytics_e4_jobs toll-analytics_plaza_jobs
# or: docker volume prune
docker compose up --build
```

**Do not** mount a volume over `/app/Exeption Programs` itself — that hides the scripts from the image.

### Exception one-click pipeline (monthly)

New tables (migration `0021_exception_pipeline`) store month-wise inputs and
**parallel** metrics/outputs (`pipeline_audit_exception_*`). Legacy
`exception_jobs` / `audit_exception_*` are unchanged.

When VRN and/or ETC are uploaded for the month, starting a batch also queues
**plaza analytics** (`analytics_vrn_etc`) in parallel with the exception chain
(migration `0022_pipeline_analytics_job`). The separate Analytics upload page
redirects to this pipeline.

After deploy:

```bash
docker compose exec backend flask db upgrade
```

UI: `/exceptions/pipeline`. Audit Exceptions tab has a **Metrics source**
toggle (Single-run vs One-click pipeline).

### Reference Excel in the image

Job inputs (`*.xlsx` / `*.csv`) are excluded by `.dockerignore` on purpose. One exception is shipped in the image:

- `Exeption Programs/E10/OW multiple LSW std weights.xlsx` (Std Weight lookup)

If E10 fails with `Std weight lookup file not found`, rebuild the backend after confirming that file exists on the host build context.

### Memory / Chrome

- `mem_limit: 16g` — raise if month-sized ETC/VRN OOMs
- `shm_size: 2gb` — required for Chrome in Docker

---

## S3 CORS (required for browser uploads)

Presign hits your API (you already see `POST …/presign → 200`). The **browser then PUTs
directly to S3**. That step never touches Flask — if it fails you will **not** see a
`/files/complete` log, and the upload control clears after a few seconds.

In **AWS Console → S3 → your bucket → Permissions → Cross-origin resource sharing (CORS)**
paste (adjust origins as needed):

```json
[
  {
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET", "PUT", "HEAD"],
    "AllowedOrigins": [
      "http://localhost:8080",
      "http://127.0.0.1:8080",
      "http://localhost:5173",
      "https://mariah-pernickety-phraseologically.ngrok-free.dev"
    ],
    "ExposeHeaders": ["ETag", "x-amz-request-id"],
    "MaxAgeSeconds": 3000
  }
]
```

Also confirm the IAM user in `AWS_ACCESS_KEY_ID` can `s3:PutObject` (and `s3:DeleteObject`)
on `arn:aws:s3:::YOUR_BUCKET/Toll Analytics Files/*`.

Quick check: open DevTools → Network while uploading. Look for a request to
`*.s3.*.amazonaws.com` — if it is red with CORS / blocked, the JSON above is the fix.

---

## Env checklist (backend/.env)

| Area | Keys |
|------|------|
| App DB | `DB_*`, `SECRET_KEY` |
| Exempt headers / checkpost | `RDS_*` (`RDS_DB_NAME`=nhit, `RDS_TABLE_NAME`=checkpostmaster) |
| Metrics | `Toll_Analytics_DB`, `Exception_Metrics_Table` |
| Submissions | `Source_DB_NAME`, `exceptions_Table_NAME` |
| S3 | `AWS_*` |
| Scrape (all programs) | `SCRAPE_ENABLED`, `SCRAPE_USE_GRID`, `SCRAPE_GRID_URL`, `SCRAPE_MAX_NODES`, `SCRAPE_MAX_CONCURRENCY`, `SCRAPE_AUTO_MANAGE_NODES`, `SCRAPE_HEADLESS` |
| Paths (Compose sets these) | `TOLL_REPO_ROOT`, `EXCEPTION_PROGRAMS_ROOT`, … |

Canonical only — do not re-add: `Table_NAME`, `Plaza_analytics_*`, `Checkpost_*`
(see `backend/.env.example`).

Old `Exeption Programs/.env` and `E4/.env` are no longer read by the Website worker.
Scrape settings no longer live in `e5_config.json` / `e6_config.json` (infra moved to `.env`).
