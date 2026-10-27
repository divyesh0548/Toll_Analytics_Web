# Production readiness & config modernization

Checklist and design notes before deploying the Toll Analytics Website, plus a
plan to move keyword / vehicle-class / MOP / column mappings from JSON files into
the database so operators can edit them in the UI.

Last updated: 2026-10-16

---

## Deploy order (recommended)

1. Lock secrets, CORS/S3, `FLASK_ENV`, and run DB migrations.
2. Rebuild backend + frontend images; bring up Compose behind HTTPS.
3. Smoke-test File Upload, one plaza analytics run, and one exception program.
4. Then implement **mappings DB + admin UI** (JSON edits + image rebuild remain a temporary ops workaround).

---

## Must-fix before production

### Secrets

- Use only untracked `Website/backend/.env` (copy from `.env.example`).
- Set a strong unique `SECRET_KEY` (not a placeholder / `change-me`).
- Set `SITEADMIN_EMAIL` / `SITEADMIN_PASSWORD`, then treat that password as sensitive (siteadmin password can reset on boot if left in env).
- **Critical:** `Website/backend/exempt_query-env.env` has appeared git-tracked with RDS credentials. Rotate that password, stop using the file in prod, remove it from the repo, and purge from history if the repo was shared.

### Prod flags

| Setting | Value | Notes |
|---|---|---|
| `FLASK_ENV` | `production` | Disables Flask debug |
| `Development_Exceptions` | `0` | Hides classic Exceptions upload nav + Audit “metrics source” toggle. File Upload (`/exceptions/pipeline`) stays available. See `hidden-ui.md`. |

### CORS / S3

- `CORS_ORIGINS` = real frontend URL(s) only (drop leftover ngrok / localhost).
- S3 bucket CORS must allow those same origins for browser presigned uploads.
- Prefer IAM role / short-lived AWS credentials over long-lived keys in `.env` when hosting in cloud.

### Database

- Fill `DB_*` for the app DB (`toll_analytics`).
- Run migrations (`flask db upgrade` through the latest revision).
- Confirm app DB vs RDS / source DBs used by exception ETL are correct for prod.

### Plaza mappings (still files today)

- `Exeption Programs/common/plaza_entity_map.json` — `plaza_identifier` → submissions `entity_name`.
- `…/Final_7_scripts/annexure_plaza_config.json` — Full Exempt plaza UUID map + rates/approved-exemption filenames.
- Every live plaza must be mapped, or Full Exempt / File Upload will fail for that plaza.
- Annexure rates / approved-exemption folders must exist (Compose bind-mounts or bake into the image).

### Deploy model

- Frontend and much of backend logic/scripts are **baked into Docker images**.
- After UI / config / script changes: **rebuild images**, then `compose up`.
- Do not rely on editing JSON inside a running container.

### Selenium

- Prefer a fixed Grid (hub + nodes) in production.
- Avoid mounting `/var/run/docker.sock` into the backend on a public host (high risk if the app is compromised).

### Ops

- Terminate HTTPS in front of nginx (`8080`).
- External uptime check on `/api/health`.
- Watch memory: File Upload pipeline can run **2 exception jobs + plaza analytics** in parallel (`_WORKER_MAX_PARALLEL = 2`).

---

## Should-fix (with or soon after first prod cut)

| Item | Why |
|---|---|
| Align `DOCKER.md` with parallel workers (max 2) + analytics track | Docs still imply more serial processing than the code does |
| Raise/monitor `mem_limit` under parallel pipeline load | Availability under heavy E5/E6 + analytics |
| Confirm annexure bind-mounts (or bake required xlsx) | Full Exempt defaults otherwise fail |
| IAM least privilege on S3 prefix | Limit blast radius of leaked keys |
| Smoke-test Full Exempt, E5/E6 scrape, File Upload re-open of an active batch | Regressions from recent work |
| Confirm monthly-input S3 protection still holds after any new delete paths | Avoid ghost File Upload files / HeadObject 404s |
| Move class / MOP / keywords to DB + admin UI | Main product gap (see below) |

---

## Nice-to-have

- Split API vs worker containers (with a DB claim lock) before horizontal scale.
- Remove hardcoded ngrok defaults from code once env is mandatory in prod.
- Export mappings to JSON for offline/CLI runs after DB becomes source of truth.
- Health checks / restart already use `unless-stopped`; keep Compose profile for optional Selenium clean.

---

## Security risks (summary)

| Risk | Severity | Notes |
|---|---|---|
| Committed credentials in `Website/backend/exempt_query-env.env` | **Critical** | Rotate RDS password; delete / gitignore; purge history if shared |
| `docker.sock` mounted into backend | **High** | Equivalent to host root on RCE |
| Default `SECRET_KEY` if `.env` missing | **High** | Token forgery |
| Siteadmin password from env every boot | **Medium** | Convenient for deploy; dangerous if `.env` leaks |
| Ngrok origin in default CORS / S3 docs | **Medium** | Widen attack surface if left in prod |
| CORS fallback when origin list empty | **Medium** | Edge case in app init |
| Long-lived AWS keys in `.env` | **Medium** | Prefer IAM role / short-lived creds |
| No TLS in Compose | **Medium** for internet expose | Terminate TLS at reverse proxy |
| 16g + Chrome + parallel jobs | **Ops** | Self-DoS / OOM more than auth |

---

## Config today (JSON / file inventory)

Canonical plaza ETL mappings live as files baked into the backend image. Changing them today means: edit file → rebuild → redeploy. No in-app add/remove.

### Plaza analytics (vehicle class / MOP / columns)

| Path | Purpose |
|---|---|
| `Plaza_db_update/config/vehicle_class.json` | Canonical vehicle classes → `db_column` + aliases; `exclude` list |
| `Plaza_db_update/config/mop.json` | Canonical MOP → `db_column` + aliases; `ignore` list |
| `Plaza_db_update/config/excel_config.py` | Excel **column header** aliases (Python, not JSON) |

Loaded at process time from disk (`/app/Plaza_db_update/config/` in Docker).

### Plaza / Full Exempt mappings

| Path | Purpose |
|---|---|
| `Exeption Programs/common/plaza_entity_map.json` | `plaza_identifier` → `entity_name` |
| `…/Final_7_scripts/annexure_plaza_config.json` | Rates/approved filenames; plaza UUID → Full Exempt key |
| `…/Final_7_scripts/codes_dump.json` | Full Exempt plaza keys (BASSI, …) |

### Exception program header keywords / aliases

| Path | Purpose |
|---|---|
| `E4/etc_merge_config.json`, `E4/vrn_merge_config.json`, `E4/config.json` | Header keywords, merge aliases, E4 settings |
| `E5/e5_config.json` | Columns, `class_aliases`, TC class maps |
| `E6/e6_config.json` | Header keywords + merge config |
| `E7/e7_config.json` | Columns, VC4 filter, rates/cutover |
| `E9/e9_config.json` | Columns / unsettled filter |
| `E10/e10_config.json` | TC class exclude, column aliases, VRN lane maps |
| `E11/e11_config.json` | Header keywords, columns, date formats |
| `E15/E15_config.json` | Header keywords, from-plaza aliases, VRN merge |
| Exempt query normalization JSONs / pass separator / valid-invalid configs | Header groups, pass types, journey filters |

### Related non-JSON stores

| Store | Purpose |
|---|---|
| `Header_Mapping/header_mapping.py` | Valid/invalid required columns + aliases (Python dict) |
| RDS via `db/nhit_file_process.py` | LC/ETC/VRN **header keywords** already partly in DB |
| Hardcoded fallbacks in some merge scripts | e.g. keyword lists in `merge_files.py` |

**Note:** Prefer unifying with the Website app DB later rather than inventing a second editable source of truth beside RDS.

---

## Suggested approach: store mappings in the app DB

### Goal

Siteadmin (or ops role) can add/remove aliases and canonical classes/MOPs in the UI; plaza ETL and exception programs read the same store.

### Schema sketch (one model for all “keyword” domains)

```
mapping_domains
  id, code (vehicle_class | mop | column_header | header_keyword | …),
  program_scope (nullable: plaza_etl | e5 | e6 | …)

mapping_canonicals
  id, domain_id, canonical_key, db_column (nullable),
  meta JSONB, is_active

mapping_aliases
  id, canonical_id, alias, normalize_rule,
  unique(domain, normalized_alias)

mapping_list_values
  id, domain_id, list_key (exclude | ignore | header_keywords),
  value, sort_order

plaza_config
  plaza_identifier PK/FK, entity_name, full_exempt_key, notes

plaza_asset_files
  full_exempt_key, asset_type (rates | approved_exemption), filename
```

#### Example — vehicle class

| Canonical | db_column | Aliases |
|---|---|---|
| BUS | vc_bus_2_axle | BUS, BUS-2-AXLE, MiniBus, … |

#### Example — MOP / column headers / E6 keywords

Same tables, different `domain` (and optional `program_scope`).

### Migration path (low risk)

1. Alembic create tables; **seed from current JSON** (and `excel_config.py` lists).
2. Adapter layer: `load_vehicle_class_mappings()` / mop loaders read **DB first, JSON file fallback**.
3. Siteadmin API + admin page: list / add alias / deactivate / manage exclude lists; audit who changed what.
4. Keep **Export JSON** for offline/CLI runs.
5. Later: fold program-specific configs (E5 `class_aliases`, E10 aliases, header keywords) into the same domain model with `program_scope`.
6. LC/ETC keywords already partly in RDS — unify naming with Website DB or leave RDS as source of truth with a thin sync.

### Product rules to decide up front

- Soft-delete / deactivate aliases (do not hard-delete if historical jobs depended on them).
- Normalize aliases the same way ETL does today (case, spaces, symbols).
- Unique constraint on normalized alias per domain (two classes cannot both claim `"BUS"`).
- Audit log: who changed what, when.
- Cache mappings in-process with short TTL or bust cache on save (ETL reads often).

### UI sketch

**Admin → Data mappings**

- Tabs: Vehicle class | MOP | Column headers | Program keywords (E4 / E5 / …)
- Each row: canonical, DB column, alias chips, Add alias, Exclude list
- Plaza tab: UUID ↔ entity name / Full Exempt key

That matches how users think (“add another word for BUS”) without editing JSON.

---

## Fragile areas from recent work (regression watchlist)

1. **Monthly input S3 protection** — Job cleanup must never delete `PlazaMonthlyExceptionInput` S3 keys (ghost File Upload files → HeadObject 404). Any new delete path must call the shared protected-key helper.
2. **Pipeline parallel enqueue** — Up to 2 ready exception steps + parallel analytics; dependents (e.g. E15) wait for produced slots (`full_exempt_final`).
3. **Frontend in Docker** — Static assets baked at build; UI fixes need a frontend image rebuild.
4. **Annexure assets** — Rates / Approved Exemption folders are often gitignored; Compose bind-mounts required.
5. **Incomplete plaza maps** — Empty `plaza_identifiers` in annexure config → Full Exempt disabled for that plaza.
6. **File Upload active batch restore** — Reopening plaza + month must reload queued/running batches (and analytics still in flight).

---

## Shared config files (first step toward editable mappings)

Consolidated unique config (vehicle class, MOP, column aliases, header
keywords, TC index map, journey types, pass values) lives at:

`Exeption Programs/common/shared_config/`

See that folder’s `README.md` and `index.json` for domains, sources merged,
and what must stay program-local. Seed future DB mapping tables from these
files; wire loaders next, then admin CRUD.

---

## Bottom line

**Blockers for a safe first production cut:** secrets hygiene (especially committed env credentials), prod flags, CORS/S3, migrations, plaza maps, TLS, and Selenium without `docker.sock` if the host is exposed.

**JSON limitation:** treat vehicle class / MOP / column aliases / header keywords as a shared **mapping domain in Postgres**, seed from `common/shared_config/`, switch loaders to DB, then give siteadmin a small CRUD UI. That is the right long-term fix; file edits + image rebuilds are only a temporary ops workaround.
