# E10 — End-to-end guide

What this program does: finds vehicles that were **overweight** at the plaza, figures out **why** (WIM vs SWB issue), and saves **monthly totals** in the audit dashboard under E10 (with three sub-types: A, B, and C).

In short: take lane VRN data → get checkpost weight → match ETC for NPCI class → pick the right toll rate → keep rows with positive overweight.

Settings live in **`e10_config.json`**. The JSON blocks under each step are copied from that file. If something changes, edit the JSON on disk.

---

## How to run

At the top of **Main_E10.py**, set:

| What to set | Why |
|-------------|-----|
| Plaza name (entity) | Must match the plaza in the rates file (e.g. bassi) |
| Plaza identifier | Plaza UUID used for the database update |
| VRN folder | Local folder of VRN Excel/CSV files (VRN is **not** downloaded) |
| ETC folder | Local folder of ETC Excel/CSV for the same period (ETC is **not** downloaded) |

Also needed:

- Website backend `.env` — database login and source DB for ETC files  
- E4 `.env` — checkpost database name and table  
- Excel file **OW multiple LSW std weights.xlsx** in the E10 folder (standard-weight lookup)

Then run:

```text
python Main_E10.py
```

If the final CSV is already ready and you only want to update the database:

```text
python Update_DB_E10.py
```

---

## What files are involved

| File | What it does |
|------|----------------|
| Main_E10.py | Runs the full flow |
| e10_config.json | Column names, filters, weight rules, rate cutover |
| vehicle-class.py | Maps weight bands to class numbers 1–6 |
| E4/plaza_rates.py | Single-journey toll rates by class |
| E4 VRN / ETC merge scripts | Combine local VRN and ETC files (header detect + column map) |
| Update_DB_E10.py | Writes E10 / E10-A / E10-B / E10-C totals to the database |

**Files written under `output/`:**

- Combined VRN  
- VRN with checkpost Weight  
- Combined ETC  
- Final result (overweight cases)

---

## Steps (in order)

### 1. Combine local VRN files

Pulls all Excel/CSV files from the VRN folder. Finds the header row, keeps the columns we need, and if date and time are in separate columns, joins them into one date-time.

**What you get on the sheet (friendly names):**

| Meaning | Column name after merge |
|---------|-------------------------|
| Vehicle number | Veh Reg No. style → kept as vehicle number |
| Vehicle class at plaza | TC Class / MVC |
| When the vehicle passed | Date & Time |
| SWB weight | SWB Wt/Std. Weight |
| Lane weight | Lane Weight |
| Lane standard weight | Lane/Chg Standard Weight |
| Lane overload fee | LANE OVERLOAD AMT |
| SWB fee | SWB AMT |

**Config used here:**

```json
"vrn_merge": {
  "header_keywords": [
    "Veh Reg No", "Veh Reg No.", "VEH REG NO", "VEH. REG. NO",
    "DATE", "TIME", "DATE TIME", "Date & Time",
    "TC Class", "TC CLASS", "MVC", "Vehicle Class",
    "Lane", "LANE", "MOP", "PAYMENT METHOD",
    "LANE WEIGHT", "LANE STD WEIGHT", "SWB WEIGHT", "SWB Wt/Std. Weight",
    "LANE OVERLOAD AMT", "OVERLOAD AMT", "SWB AMT", "Plaza"
  ],
  "header_scan_rows": 25,
  "min_header_matches": 3,
  "merge_columns": {
    "vehicle_reg_no": ["VEH REG NO", "Veh Reg No.", "Veh Reg No", "VEH. REG. NO", "Vehicle Reg No"],
    "tc_class": ["MVC", "TC Class", "TC CLASS", "TcClass"],
    "read_datetime": [
      "DATE TIME", "Date Time", "Date and Time", "Date & Time",
      "Txn Date Time", "Txn Date & Time", "Transaction Date Time",
      "Transaction Date & Time", "Tag Read Date Time", "Transaction Date"
    ],
    "date_part": ["DATE", "Date"],
    "time_part": ["TIME", "Time"],
    "swb_wt_std_weight": ["SWB WEIGHT", "SWB Wt/Std. Weight"],
    "lane_weight": ["LANE WEIGHT", "Lane Weight"],
    "lane_chg_standard_weight": ["LANE STD WEIGHT", "Lane/Chg Standard Weight"],
    "lane_overload_amt": ["LANE OVERLOAD AMT", "OVERLOAD AMT"],
    "swb_amt": ["SWB AMT"]
  }
}
```

```json
"vrn_lane_columns": {
  "swb_wt_std_weight": { "output": "SWB Wt/Std. Weight", "aliases": ["SWB WEIGHT", "SWB Wt/Std. Weight"] },
  "lane_weight": { "output": "Lane Weight", "aliases": ["LANE WEIGHT", "Lane Weight"] },
  "lane_chg_standard_weight": { "output": "Lane/Chg Standard Weight", "aliases": ["LANE STD WEIGHT", "Lane/Chg Standard Weight"] },
  "lane_overload_amt": { "output": "LANE OVERLOAD AMT", "aliases": ["LANE OVERLOAD AMT", "OVERLOAD AMT"] },
  "swb_amt": { "output": "SWB AMT", "aliases": ["SWB AMT"] }
}
```

---

### 2. Decide the ETC download period

Looks at the earliest and latest dates in the VRN data. That range is used to download ETC for the same period. No new columns — just sets the date window.

**Config used here:**

```json
"datetime_column_aliases": [
  "read_datetime", "DATE TIME", "Date Time", "Date & Time", "Date and Time",
  "DATE", "Date", "Txn Date Time", "Tag Read Date Time"
]
```

---

### 3. Drop some vehicle classes

Removes buses and similar classes so they are not treated as overweight exceptions.

Dropped by default: BUS, MAXI CAB, MOTOR CAB, OMNI BUS.

**Config used here:**

```json
"tc_class_exclude": ["BUS", "MAXI CAB", "MOTOR CAB", "OMNI BUS"],
"tc_class_column_aliases": [
  "tc_class", "TC Class", "TC CLASS", "Tc Class", "TcClass",
  "MVC", "Vehicle Class", "vehicle class"
]
```

---

### 4. Attach checkpost Weight

Looks up each vehicle number in the checkpost database and adds a **Weight** column.

Then removes rows with no weight, zero weight, or blank/invalid weight.

Intermediate file: VRN with Weight.

**Config used here:**

```json
"vehicle_column_aliases": [
  "vehicle_reg_no", "Veh Reg No.", "Veh Reg No", "VEH REG NO",
  "VEH. REG. NO", "Vehicle Reg No", "Unique Vehicle Number"
],
"checkpost_vehicle_column": "Unique Vehicle Number",
"checkpost_weight_column": "weight",
"weight_output_column": "Weight",
"weight_invalid_values": ["", "0", "0.0", "n/a", "na", "null", "none", "nan"],
"checkpost_fetch_batch_size": 1000
```

---

### 5. Load and combine local ETC

Reads ETC Excel/CSV from the ETC folder (same date range as VRN). No download from the database.

We mainly need vehicle number, Reader Read Time (or Date & Time), settlement amount, and NPCI class.

**Config used here (datetime prefers Reader Read Time for bank-portal files):**

```json
"etc_merge": {
  "header_keywords": [
    "Plaza Name", "Settlement Amount", "Net Settlement Amt", "Plaza ID",
    "Veh Reg No", "Veh Reg No.", "TC Class", "Journey Type", "MOP",
    "Date & Time", "Tag Read Date Time", "Reader Read Time",
    "NPCI Class Desc", "NPCI Class", "Txn ID", "Agency Txn Id"
  ],
  "header_scan_rows": 25,
  "min_header_matches": 3,
  "merge_columns": {
    "vehicle_reg_no": [
      "Veh Reg No", "Veh Reg No.", "Vehicle Reg No", "Vehicle Reg. No.",
      "Vehicle Number", "Vehicle No", "Reg No", "Licence Plate No"
    ],
    "read_datetime": [
      "Reader Read Time",
      "Date & Time", "Date and Time", "Txn Date Time", "Txn Date & Time",
      "Transaction Date Time", "Transaction Date & Time",
      "Tag Read Date Time", "Acquirer Receive Time", "Transaction Date"
    ],
    "net_settlement_amt": [
      "Net Settlement Amt", "Net Settlement Amount", "Net Settlement",
      "Settlement Amount", "Settled Amount", "Net Settled Amount"
    ],
    "npci_class": [
      "NPCI Class Desc", "NPCI Class", "NPCI CLass", "NPCIClass",
      "NPCI Class Description", "Mapper VC"
    ]
  }
}
```

---

### 6. Match VRN with ETC

VRN often has **DATE** and **TIME** in two columns; the program joins them into one date-time first.

Links each VRN row to ETC using **same vehicle number** and **same calendar date + hour**.

**Adds two columns:**

- **Net Settlement Amount** — from ETC  
- **NPCI Class** — from ETC  

If no ETC match, those two stay blank. All VRN columns stay as they are.

---

### 7. Add Custom (broad weight band)

Uses checkpost **Weight** to put the vehicle into a broad band, stored in **Custom**.

Examples: `<=7500 Kgs`, `>7500 Kgs but <=12,000 Kgs`, …, `>60,000 Kgs`.

This is used later only to pick the toll class / rate — not for the standard-weight Excel lookup.

**Config used here:**

```json
"weight_range_output_column": "Custom",
"weight_ranges": [
  { "max_weight": 7500, "label": "<=7500 Kgs" },
  { "max_weight": 12000, "label": ">7500 Kgs but <=12,000 Kgs" },
  { "max_weight": 18500, "label": "> 12,000 Kgs but <= 18,500 Kgs" },
  { "max_weight": 28000, "label": "> 18,500 Kgs but <= 28,000 Kgs" },
  { "max_weight": 60000, "label": "> 28,000 Kgs but <= 60,000 Kgs" }
],
"weight_range_above_max_label": ">60,000 Kgs"
```

Class numbers (from vehicle-class.py): up to 7500 → Car (1), 12000 → LCV (2), 18500 → Truck (3), 28000 → Truck 3-axle (4), 55000 → MAV (5), heavier → OSV (6).

---

### 8. Add Weight Group (finer band)

Uses **Weight** and sometimes **NPCI Class** to assign a finer **Weight Group**.

That can be a number like `7875` (exact standard) or a cleaned range label like `>7500but<11990` / `<7500`.

After the rules run, **Kgs** and spaces are stripped from Weight Group (same as Power Query Replaced Value steps), so the stored label matches expected output.

Rows with no Weight Group are removed.

**Config used here:**

```json
"weight_group_output_column": "Weight Group",
"weight_group_rules": [
  { "type": "eq", "weight": 7500, "label": "7875" },
  { "type": "lt", "weight": 7500, "label": "<7500" },
  { "type": "eq", "weight": 11990, "label": "12600" },
  { "type": "between", "gt": 7500, "lt": 11990, "label": ">7500but<11990" },
  { "type": "eq", "weight": 18500, "label": "19425" },
  { "type": "between", "gt": 11990, "lt": 18500, "label": ">11990but<18500" },
  { "type": "eq", "weight": 28000, "label": "29400" },
  { "type": "between", "gt": 18500, "lt": 28000, "label": ">18500but<28000" },
  { "type": "eq", "weight": 30000, "label": "31500" },
  { "type": "between", "gt": 28000, "lt": 30000, "label": ">28000but<30000" },
  { "type": "eq", "weight": 35000, "label": "36750" },
  { "type": "between", "gt": 30000, "lt": 35000, "label": ">30000but<35000" },
  { "type": "eq", "weight": 39500, "label": "41475" },
  { "type": "between", "gt": 35000, "lt": 39500, "label": ">35000but<39500" },
  { "type": "eq", "weight": 41500, "label": "43575" },
  {
    "type": "between", "gt": 39500, "lt": 41500,
    "npci_any": ["Truck 4 - axle", "Truck 4-axle", "4 axle", "4 - axle"],
    "label": ">39500but<41500"
  },
  { "type": "eq", "weight": 42000, "label": "44100" },
  { "type": "between", "gt": 41500, "lt": 42000, "label": ">41500but<42000" },
  { "type": "eq", "weight": 41000, "label": "43050" },
  {
    "type": "between", "gt": 39500, "lt": 41000,
    "npci_any": [
      "Truck 5 - axle", "Truck 6 - axle", "Truck 5-axle", "Truck 6-axle",
      "5 axle", "6 axle", "5 - axle", "6 - axle"
    ],
    "label": ">39500but<41000"
  },
  { "type": "eq", "weight": 46500, "label": "48825" },
  { "type": "between", "gt": 42000, "lt": 45500, "label": ">42000but<45500" },
  { "type": "eq", "weight": 45500, "label": "47775" },
  { "type": "between", "gt": 45500, "lt": 46500, "label": ">45500but<46500" },
  { "type": "eq", "weight": 49000, "label": "51450" },
  { "type": "between", "gt": 46500, "lt": 49000, "label": ">46500but<49000" },
  { "type": "eq", "weight": 51000, "label": "53550" },
  { "type": "between", "gt": 49000, "lt": 51000, "label": ">49000but<51000" },
  { "type": "eq", "weight": 55000, "label": "57750" },
  { "type": "gt", "weight": 51000, "label": ">51000" }
]
```

---

### 9. Look up Std Weight

Finds the **allowed / standard weight** for that vehicle and writes it in a new column: **Std Weight**.

Uses the Excel file **OW multiple LSW std weights.xlsx** (Weight, Weight Group, Std Weight columns).

**How the match is tried (first success wins):**

1. Match on **Weight Group** in the Excel sheet  
2. If that fails, match on checkpost **Weight**  
3. If Weight Group is already a plain number (like `7875`), use that as Std Weight  
4. If still nothing, copy checkpost **Weight** into **Std Weight**

**Config used here:**

```json
"std_weight_lookup": {
  "file": "OW multiple LSW std weights.xlsx",
  "sheet": "Sheet1",
  "weight_column": "Weight",
  "weight_range_column": "Weight Group",
  "std_weight_column": "Std Weight",
  "output_column": "Std Weight"
}
```

---

### 10. Add Applicable Rate

Uses **Custom** (broad band) to pick a class number 1–6, then looks up the plaza’s **single-journey** toll for that class.

**Adds:**

- **Class Index** — 1 to 6  
- **Applicable Rate** — toll amount for that class on that day  

Rates change after a cutover date (default May 2026): older dates use the old rate book, later dates use the April-2026-onwards book.

**Config used here:**

```json
"rate_cutover_date": "2026-05-01",
"class_index_output_column": "Class Index",
"applicable_rate_output": "Applicable Rate"
```

Actual rupee amounts are in **E4/plaza_rates.py** (per plaza, single journey only).

---

### 11. Overweight, filters, and OW Status

Uses lane / SWB weights and **Std Weight** to decide if the vehicle was overweight and how to label it.

**Adds:**

- **Overweight** — if SWB weight &gt; 0: SWB minus Std Weight; otherwise Lane Weight minus Std Weight  
- **Overweight %** — overweight as a percent of Std Weight  
- **OW Status** — one of:
  - **OW At WIM** — lane standard matches Std Weight, and SWB weight is zero  
  - **Not Charged At SWB** — lane standard matches Std Weight, but SWB weight is not zero  
  - **Altered at WIM/SWB** — lane standard does not match Std Weight  

**Blank / empty SWB weight is set to 0** (row is **kept**). Overweight then uses Lane Weight minus Std Weight — same as expected Aug output where most SWB values are 0.

**Keeps only rows where Overweight is greater than zero.**

Lane overload amount and SWB amount are **not** used as a filter (Aug expected file includes rows with non-zero fee amounts).

That final sheet is the main E10 output.

*(Older Power Query also filtered April and Custom ≤7500 only — this program does not.)*

---

### 12. Update the database

Takes the final CSV, groups by **month of the trip**, and writes:

- **Count** — number of rows  
- **Amount** — sum of Applicable Rate  

**Three segments:**

| Code | Meaning |
|------|---------|
| E10-A | Lane/Chg Standard Weight **less than** Std Weight |
| E10-B | Lane standard **≥** Std Weight, and SWB weight is **zero** |
| E10-C | Lane standard **≥** Std Weight, and SWB weight is **not zero** |

**E10** (parent) = A + B + C for that month.

If a month already exists in the DB, it is updated only when the new count or amount is **higher**.

Plaza UUID is set in Main_E10 / Update_DB_E10 (not in the JSON config).

Columns the DB step expects on the final CSV:

| Needed for | Column on the sheet |
|------------|---------------------|
| Month | Date & Time of the trip |
| Amount | Applicable Rate |
| Segment logic | SWB Wt/Std. Weight, Lane/Chg Standard Weight, Std Weight |

---

## Columns added along the way

| Step | What gets added |
|------|-----------------|
| 1 Combine VRN | Lane / SWB weight and amount columns (named as above) |
| 3 Drop classes | — (only removes rows) |
| 4 Checkpost | **Weight** |
| 6 Match ETC | **Net Settlement Amount**, **NPCI Class** |
| 7 Custom band | **Custom** |
| 8 Weight Group | **Weight Group** (rows without a group are dropped) |
| 9 Std Weight | **Std Weight** |
| 10 Rate | **Class Index**, **Applicable Rate** |
| 11 Overweight | **Overweight**, **Overweight %**, **OW Status** (blank SWB→0; keep Overweight &gt; 0 only) |
| 12 Database | Uses trip month, Applicable Rate, Std Weight, SWB and lane standard |

---

## One line for stakeholders

**E10** finds overweight vehicles at the plaza, puts a toll rate and a status on each case, then reports monthly counts and amounts as E10-A (WIM undercharge), E10-B (not charged at SWB), and E10-C (weights altered).
