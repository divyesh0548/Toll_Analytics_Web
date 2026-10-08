# E7 — End-to-end guide

What this program does: finds **local passes** issued for **VC4** (car/jeep class) where the fee charged is **too low** relative to a fixed monthly rate, treats the shortfall as **Loss**, and saves **monthly totals** in the audit dashboard under exception **E07** (*Local passes issued at a lower or zero charge*).

In short: read pass Excel/CSV files → keep **VC4** only → count calendar months between start and end effective dates → **Loss = Months × 360 − Issuance Fees** (only when &gt; 0) → write monthly summary → upsert `audit_exception_metrics`.

Settings live in **`e7_config.json`**. Column names and the monthly rate come from that file. If something changes, edit the JSON on disk.

---

## How to run

At the top of **Main_E7.py**, set:

| What to set | Why |
|-------------|-----|
| `PASS_INPUT_FOLDER` | Folder of pass Excel/CSV files for this plaza |
| `PLAZA_IDENTIFIER` | Plaza UUID used for the database update |

Also needed:

- `Website/backend/.env` — analytics DB login (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` / `ANALYTICS_DB_NAME` / `NHIT_DB`)

Then run:

```text
python Main_E7.py
```

There is no separate “DB-only” script. Metrics are updated every successful run after the CSV is written. There is currently **no** S3 output upload in this program.

---

## What files are involved

| File | What it does |
|------|----------------|
| `Main_E7.py` | Runs the full flow (read → filter → Loss → CSV → DB) |
| `e7_config.json` | Column names, VC4 value, monthly rate |
| `Website/backend/.env` | Analytics DB connection for metrics |

**Files written under `output/`:**

- `e7_vc4_loss.csv` — one row per **start-date** year/month (not one row per pass)

---

## Config (`e7_config.json`)

```json
{
  "npci_vehicle_class": "NPCI Vehicle Class",
  "vehicle_class_value": "VC4",
  "start_effective_date": "Start Effective Date",
  "end_effective_date": "End Effective Date",
  "issuance_fees": "Issuance Fees (Rs.)",
  "months": "Months",
  "loss": "Loss",
  "monthly_rate": 360
}
```

| Key | Meaning |
|-----|---------|
| `npci_vehicle_class` | Header name for vehicle class on the pass sheet |
| `vehicle_class_value` | Value to keep (default `VC4`; compared after stripping non-alphanumerics) |
| `start_effective_date` / `end_effective_date` | Pass validity window |
| `issuance_fees` | Fee actually charged at issuance |
| `months` / `loss` | Output column names used while calculating (not written to the final monthly CSV) |
| `monthly_rate` | ₹ per month used in the Loss formula (360) |

---

## Steps (in order)

### 1. Load config and list pass files

- Reads `e7_config.json` and checks that all required keys exist.
- Lists every `.xlsx` / `.xls` / `.xlsm` / `.csv` in `PASS_INPUT_FOLDER` (skips Excel lock files `~$…`).
- Fails if the folder is missing or empty.

---

### 2. Read each pass file (header detection)

For each file:

1. Load as text (no type guessing), **sheet 0** for Excel.
2. Scan the first **25** rows for a header that matches at least **3** of the configured column names:
   - `NPCI Vehicle Class`
   - `Start Effective Date`
   - `End Effective Date`
   - `Issuance Fees (Rs.)`
3. Use that row as column headers; the rows below become data.
4. Drop fully empty rows.

All files are concatenated into one merged frame.

---

### 3. Resolve required columns

On the merged sheet, find each config column by name (case-insensitive, whitespace-normalized). If any are missing, the run stops and lists available headers.

---

### 4. Keep VC4 only

Keep rows where **NPCI Vehicle Class** equals the configured value (`VC4`).

Comparison ignores spaces and punctuation (e.g. `VC-4` / `VC 4` still match `VC4`).

All later calculation uses only these rows, and only these four input columns:

| Column | Role |
|--------|------|
| NPCI Vehicle Class | Filter |
| Start Effective Date | Month span + monthly bucket |
| End Effective Date | Month span |
| Issuance Fees (Rs.) | Subtracted from Months × 360 |

---

### 5. Count months (day of month ignored)

Dates are parsed with common formats (`DD-MM-YYYY`, `YYYY-MM-DD`, with or without time). Blank / NA dates leave Months and Loss blank.

**Month count:**

```text
Months = (end.year − start.year) × 12 + (end.month − start.month)
```

The **day** is ignored. Example from the original rule:

| Start | End | Months |
|-------|-----|--------|
| 18-03-2026 | 31-12-2028 | 33 |

---

### 6. Calculate Loss

```text
Loss = Months × monthly_rate − Issuance Fees
```

With default config: `monthly_rate = 360`.

Rules:

| Situation | Result |
|-----------|--------|
| Unreadable start or end date | Months / Loss left blank |
| Non-numeric issuance fee | Months filled; Loss left blank |
| Blank / empty fee | Treated as **0** |
| `Loss ≤ 0` | Stored as blank (not counted in totals) |
| `Loss > 0` | Stored rounded to 2 decimals |

Currency symbols (`₹`, `Rs.`) and commas in the fee are stripped before parsing.

---

### 7. Summarize by start-date month

The program does **not** write one output row per pass.

It groups every VC4 row by the **year and month of Start Effective Date**:

| Output column | Meaning |
|---------------|---------|
| `year` | Start date year |
| `month` | Start date month (1–12) |
| `rows` | Number of VC4 pass rows in that start month (including rows with blank Loss) |
| `total_loss` | Sum of positive Loss values for that month |

Rows with an unreadable start date are skipped for this summary.

This summary is written to:

```text
output/e7_vc4_loss.csv
```

---

### 8. Update audit metrics (always)

Uses `PLAZA_IDENTIFIER` and `EXCEPTION_TYPE_ID = 7`.

For each summary row, upserts into `audit_exception_metrics`:

| Field | Value |
|-------|--------|
| `plaza_identifier` | From `PLAZA_IDENTIFIER` |
| `exception_type_id` | 7 (E07) |
| `year` / `month` | From the summary |
| `total_count` | `rows` |
| `total_amount` | `total_loss` |

Behaviour:

- Checks that exception type id **7** exists and the plaza UUID exists in `plazas`.
- `ON CONFLICT` on plaza + type + year + month → **overwrites** `total_amount` and `total_count` with the new values (not a “only increase” rule like some other exceptions).

DB name is taken from Website `.env` (`NHIT_DB` → else `ANALYTICS_DB_NAME` → else `DB_NAME`).

---

## Process flow (diagram)

```text
PASS_INPUT_FOLDER (Excel/CSV)
        │
        ▼
 Header detect + merge all pass files
        │
        ▼
 Keep NPCI Vehicle Class = VC4
        │
        ▼
 Months = calendar months (start → end, day ignored)
        │
        ▼
 Loss = Months × 360 − Issuance Fees   (only if > 0)
        │
        ▼
 Group by Start Effective Date year/month
        │
        ├──────────────────────────────►  output/e7_vc4_loss.csv
        │
        ▼
 Upsert audit_exception_metrics (exception_type_id = 7)
```

---

## Worked example

Pass row:

| Field | Value |
|-------|--------|
| NPCI Vehicle Class | VC4 |
| Start Effective Date | 18-03-2026 00:00:00 |
| End Effective Date | 31-12-2028 00:00:00 |
| Issuance Fees (Rs.) | 1,000 |

Calculation:

```text
Months = (2028 − 2026) × 12 + (12 − 3) = 33
Loss   = 33 × 360 − 1000 = 11880 − 1000 = 10880
```

That Loss is added into the **2026-03** bucket (start month), and that month’s `rows` count includes this pass.

If Issuance Fees were `12,000`, then `33 × 360 − 12000 = −120` → Loss left blank (not stored).

---

## What is *not* in E7 (today)

- No VRN / ETC merge  
- No plaza rate card lookup  
- No download from submissions DB  
- No S3 upload of the output file  
- No on/off flag for metrics (`Metrics_DB_Update`) — DB update always runs after a successful CSV write  
- No row-level detail export (only monthly aggregates)

---

## Checklist before a run

1. Put pass files in `PASS_INPUT_FOLDER`.  
2. Confirm sheets have the four headers named in `e7_config.json` (or update the JSON to match your export).  
3. Set `PLAZA_IDENTIFIER` to the correct plaza UUID.  
4. Confirm Website `.env` points at the analytics database.  
5. Run `python Main_E7.py` and check `output/e7_vc4_loss.csv` plus the console metric lines.

---

**E7** finds under-charged **VC4** local passes, measures the shortfall as **Months × ₹360 − fee**, reports it by **pass start month**, and stores those totals as audit exception **E07**.
