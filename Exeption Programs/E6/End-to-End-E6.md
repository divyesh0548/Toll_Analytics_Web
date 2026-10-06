# E6 — End-to-end guide

What this program does: finds ETC trips where the **toll that should have been charged** (from journey type + TC class rates) is **higher than what was settled**, treats the gap as **Loss**, and saves **monthly Loss totals** in the audit dashboard under exception **E6**.

In short: merge **local** ETC + **local** VRN (same month; no download) → get **TC Class** from VRN → normalize Journey Type → look up Applicable Rate → Loss = Applicable Rate − Net Settlement Amt → upsert months with positive Loss.

Settings live in **`e6_config.json`**. The JSON blocks under each step are copied from that file. If something changes, edit the JSON on disk.

---

## How to run

At the top of **E6_main.py**, set:

| What to set | Why |
|-------------|-----|
| Plaza name (`ENTITY_NAME`) | Must match the plaza key in `plaza_rates` (e.g. bassi) |
| Plaza identifier | Plaza UUID used for the database update |
| `ETC_INPUT_FOLDER` | Local folder of ETC Excel/CSV for the period (ETC is **not** downloaded) |
| `VRN_INPUT_FOLDER` | Local folder of VRN Excel/CSV for the **same** period (VRN is **not** downloaded) |

Also needed:

- E4 `.env` — only if `UPDATE_DB=True` (for `audit_exception_metrics`)

Then run:

```text
python E6_main.py
```

Or with CLI overrides:

```text
python E6_main.py <entity_name> <plaza_uuid>
```

If the enriched Excel is already ready and you only want to update the database:

```text
python e6_db_update.py
```

(set `DB_UPDATE_ONLY`, `MERGED_OUTPUT_FILE`, and `PLAZA_IDENTIFIER` in that file)

---

## What files are involved

| File | What it does |
|------|----------------|
| E6_main.py | Runs the full flow |
| e6_config.json | Header detect, ETC/VRN merge columns, journey/TC maps, rate cutover |
| vehicle_number_utils.py | Normalizes vehicle numbers for the VRN join |
| E4/plaza_rates.py | Single / return / local toll rates by class |
| E4 ETC / VRN merge scripts | Combine local ETC or VRN files (header detect + column map) |
| e6_db_update.py | Writes monthly Loss totals to the database |

**Files written under `output/`:**

- `{entity}_local_merged_etc.csv`  
- `{entity}_local_merged_vrn.csv`  
- `etc_enriched.xlsx` — enriched ETC (TC Class + rates + Loss)  

---

## Steps (in order)

### 1. Merge local ETC

Reads all Excel/CSV files under `ETC_INPUT_FOLDER` and merges them. No database download and no date-range lookup.

Columns we need after merge: vehicle number, Tag Read Date Time (or alias), Journey Type, Net Settlement Amt.

**Config used here:**

```json
"etc_merge": {
  "header_keywords": [
    "Agency Txn Id", "Settlement Amount", "Net Settlement Amt", "Plaza ID",
    "VEH REG NO", "Veh Reg No.", "Veh Reg No", "Journey Type", "Fare Type",
    "Date & Time", "Tag Read Date Time", "Txn Status"
  ],
  "header_scan_rows": 25,
  "min_header_matches": 3,
  "merge_columns": {
    "vehicle_reg_no": [
      "Veh Reg No", "Veh Reg No.", "Vehicle Reg No", "Vehicle Number",
      "Vehicle No", "Vehicle Reg. No.", "Reg No", "Licence Plate No"
    ],
    "read_datetime": [
      "Tag Read Date Time", "Tag Read Datetime", "TagRead Date Time",
      "Reader Read Time", "Date & Time", "Txn Date Time", "Transaction Date Time"
    ],
    "journey_type": [
      "Journey Type", "JourneyType", "Journey", "Fare Type", "TripType"
    ],
    "net_settlement_amt": [
      "Net Settlement Amt", "Net Settlement Amount", "Net Settlement",
      "Settlement Amount", "Settled Amount", "Net Settled Amount"
    ]
  }
}
```

**Column aliases used after load:**

```json
"columns": {
  "etc_vehicle": "vehicle_reg_no",
  "etc_vehicle_aliases": [
    "vehicle_reg_no", "Veh Reg No", "Veh Reg No.", "Vehicle Reg No",
    "Vehicle Number", "Vehicle No", "Reg No", "Licence Plate No"
  ],
  "tag_read_datetime": "read_datetime",
  "tag_read_datetime_aliases": [
    "read_datetime", "Tag Read Date Time", "Tag Read Datetime",
    "TagRead Date Time", "Date & Time", "Txn Date Time", "Transaction Date Time"
  ],
  "journey_type": "journey_type",
  "journey_type_aliases": [
    "journey_type", "Journey Type", "JourneyType", "Journey",
    "Fare Type", "TripType"
  ],
  "net_settlement": "net_settlement_amt",
  "net_settlement_aliases": [
    "net_settlement_amt", "Net Settlement Amt", "Net Settlement Amount",
    "Net Settlement", "Settlement Amount", "Settled Amount", "Net Settled Amount"
  ]
}
```

---

### 2. Merge local VRN and attach TC Class

Reads all Excel/CSV files under `VRN_INPUT_FOLDER` (same period as ETC; no download). Builds a map **normalized vehicle → first non-empty TC Class**, then adds **TC Class** on every ETC row.

**Config used here:**

```json
"vrn_merge": {
  "header_keywords": [
    "Veh Reg No", "Veh Reg No.", "VEH REG NO", "VEH. REG. NO",
    "DATE", "TIME", "DATE TIME", "Date & Time",
    "TC Class", "TC CLASS", "MVC", "Vehicle Class"
  ],
  "header_scan_rows": 25,
  "min_header_matches": 2,
  "merge_columns": {
    "vehicle_reg_no": [
      "VEH REG NO", "Veh Reg No.", "Veh Reg No", "VEH. REG. NO", "Vehicle Reg No"
    ],
    "tc_class": ["MVC", "TC Class", "TC CLASS", "TcClass", "Vehicle Class"],
    "read_datetime": [
      "DATE TIME", "Date Time", "Date and Time", "Date & Time",
      "Txn Date Time", "Txn Date & Time", "Transaction Date Time"
    ],
    "date_part": ["DATE", "Date"],
    "time_part": ["TIME", "Time"]
  }
},
"columns": {
  "tc_class": "TC Class",
  "tc_class_aliases": [
    "TC Class", "Tc Class", "TcClass", "tc_class",
    "Operator Class", "Vehicle Class"
  ],
  "tc_class_output": "TC Class"
}
```

---

### 3. Normalize Journey Type

Maps raw journey labels to one of: **`single`**, **`return`**, **`local`**.

Labels in **`journey_type_exclude`** are cleared (blank) and skipped for rating later. Any other unknown label **stops the run**.

**Config used here:**

```json
"journey_type_map": {
  "single": [
    "single", "single journey", "s", "sj", "annualpass", "annual pass",
    "annual-pass", "first journey", "1st journey", "Local Cont."
  ],
  "return": [
    "return", "return journey", "Cont. Journey", "r", "rj",
    "round trip", "roundtrip"
  ],
  "local": [
    "local", "local journey", "l", "lj", "monthly pass",
    "local pass", "Local Single"
  ]
},
"journey_type_exclude": [
  "DISCOUNTMP",
  "BLKLISTTAG",
  "EXEMPTED",
  "IHMCL_Exemption",
  "DUPLICATE",
  "Local Non Commercial"
],
"columns": {
  "journey_type_normalized_output": "journey_type"
}
```

---

### 4. Applicable Rate and Loss

For each row with a usable journey category, TC Class, and Tag Read date:

1. Map TC Class → class index **1–6** via `tc_class_index_map`  
2. Skip classes in `tc_class_skip_list` (no rate / no Loss)  
3. Pick rate book: before cutover → `PLAZA_RATES`; on/after cutover → `Plaza_Rates_Apr26_onwards`  
4. Look up rate for **this plaza** (`ENTITY_NAME`) + journey (`single` / `return` / `local`) + class index  
5. **Applicable Rate** = that toll  
6. **Loss** = Applicable Rate − Net Settlement Amt  

Unknown TC Class (not in skip list and not in the map) **stops the run**.

**Config used here:**

```json
"rate_cutover_date": "2026-05-01",
"tc_class_skip_list": [
  "auto", "3wheeler", "3 wheeler", "three wheeler", "tractor"
],
"tc_class_index_map": {
  "1": [
    "car", "carjeep", "car jeep", "car/jeep", "car\\jeep",
    "car / jeep / van", "car/jeep/van"
  ],
  "2": ["lcv", "minibus", "lcv/mini bus", "lcv mini bus"],
  "3": [
    "truck", "truck/bus", "bus/truck", "bus", "bus 2 axle",
    "bus-2 axle", "truck 2 axle", "truck-2 axle"
  ],
  "4": [
    "bus 3 ax", "bus/truck 3 axle", "bus-3 axle", "truck 3 axle",
    "truck-3 axle", "truck3x", "truck-3ax"
  ],
  "5": [
    "mav", "hcm/mav", "mav (4 to 6 axle)", "mav 4 ax", "mav 4 axle",
    "mav 4 axle -2t", "mav 5 ax", "mav 5 axle", "mav 5 axle - 5t",
    "mav 5 axle - 5t1", "mav 5 axle - 5t4", "mav 5 axle -2t",
    "mav 5 axle -3t", "mav 6 ax", "mav 6 axle", "mav 6 axle - 6t1",
    "truck 4-6 axle"
  ],
  "6": ["osv"]
},
"columns": {
  "applicable_rate_output": "Applicable Rate",
  "loss_output": "Loss"
}
```

Final enriched sheet is written to `ETC_OUTPUT_FILE` (default `output/etc_enriched.xlsx`).

---

### 5. Update the database

When `UPDATE_DB=True`, groups by **month of Tag Read Date Time** and writes:

- **Count** — rows where Loss is **positive** (empty / zero / negative Loss are excluded)  
- **Amount** — sum of those Loss values  

Exception type id = **6**.

If a month already exists for this plaza + E6, it is updated only when the new count **or** amount is **higher**.

Plaza UUID is set in `E6_main.py` / `e6_db_update.py` (not in the JSON config).

Columns the DB step expects:

| Needed for | Column on the sheet |
|------------|---------------------|
| Month | Tag Read Date Time / `read_datetime` |
| Amount | Loss |

---

## Columns added along the way

| Step | What gets added |
|------|-----------------|
| 1 Merge local ETC | Vehicle, datetime, Journey Type, Net Settlement (named via merge / aliases) |
| 2 VRN TC Class | **TC Class** |
| 3 Journey normalize | Normalized **journey_type** (`single` / `return` / `local`, or blank if excluded) |
| 4 Rates | **Applicable Rate**, **Loss** |
| 5 Database | Uses trip month and Loss (positive only) |

---

## One line for stakeholders

**E6** compares what the plaza rate book says a trip should cost with what ETC actually settled, and reports monthly positive Loss as exception E6.
