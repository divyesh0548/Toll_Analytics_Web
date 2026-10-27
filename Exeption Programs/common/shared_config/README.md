# Shared exception / plaza config

Consolidated **unique** config data mined from E4–E15, Full Exempt
normalization, pass separator, valid/invalid lookup, and
`Plaza_db_update/config`.

These files are the **master reference** for shared domains. Program-specific
rules (weight ranges, scrape flags, journey exclude lists, rate cutovers,
plaza UUIDs) stay in each program’s own `eN_config.json` until loaders are
switched over.

Last updated: 2026-10-16

## Files

| File | Domain |
|---|---|
| `vehicle_class.json` | Canonical vehicle classes → `db_column` + aliases + exclude |
| `mop.json` | Canonical modes of payment → `db_column` + aliases + ignore |
| `column_aliases.json` | Logical field → Excel/CSV header name aliases |
| `header_keywords.json` | Header-detection keyword bags by source type |
| `tc_class_index_map.json` | TC class index 1–6 → normalized class aliases (rate lookup) |
| `journey_type_map.json` | Journey buckets (single / return / local) → value aliases |
| `pass_type_values.json` | MP / LT pass-type value sets |
| `detection_defaults.json` | Default `header_scan_rows` / `min_header_matches` |

## Sources merged

- `Plaza_db_update/config/vehicle_class.json`, `mop.json`, `excel_config.py`
- `E4/config.json`, `etc_merge_config.json`, `vrn_merge_config.json`
- `E5`–`E15` program configs (aliases / headers / journey / pass only)
- `LC_Normalization_Data.json`, `Normalization_JSON_Data.json`
- `pass_separator_config.JSON`, `valid_invalid_config.json` (shared pieces only)
- `Header_Mapping/header_mapping.py` (VRN / NPCI / settlement aliases)

## Intentionally NOT merged (stay program-local)

| Keep in program config | Why |
|---|---|
| E5 `plaza_identifier`, `scrape`, `class_aliases` pairing | Plaza/scrape-specific |
| E6 `reason_keep_values`, `permit_type_keep_values`, `journey_type_exclude` | E6 business filters |
| E7 / E9 entire small configs | Issuance / unsettled pipelines |
| E10 weight ranges, checkpost columns, std-weight lookup | Overweight logic |
| E15 from/to plaza columns, `match_max_hours`, datetime format packs | Inter-plaza match |
| E15 putting tractor/3W into TC index `1` | Conflicts with plaza 3WHEELER/TRACTOR |
| `rate_cutover_date` | Differs by program (Apr vs May 2026) |
| `annexure_plaza_config.json` | Plaza file ↔ UUID map |
| valid_invalid journey drop / NPCI_TO_TC / lifecycle class lists | Different domain semantics |
| Journey header including `MOP` (valid_invalid) | Unsafe globally |

## Conflict notes

1. **MiniBus** — plaza `vehicle_class.json` lists MiniBus under BUS; E5 scrape
   pairs MiniBus→Bus 2 Axle; TC index map puts minibus under LCV (index 2).
   Shared `vehicle_class.json` keeps MiniBus under **BUS** (plaza DB). TC map
   keeps minibus under **index 2 (LCV)** for rate lookup — different layers.
1b. **MAV** — shared canonical name is **MAV** (aliases include `TRUCK 4-6 AXLE`
   etc.). Plaza ETL historically also had a separate `vc_truck_4_6_axle`
   column; consolidating analytics to `vc_mav` may need a one-time column
   merge when loaders switch. `tc_class_index_map.json` index `5` is unchanged.
2. **Tata Ace** — plaza/LCV and valid_invalid NPCI maps disagree; listed under
   LCV here.
3. **CASH-UPI** — counted as **upi** (plaza mop); not dual-listed under cash.
4. **E15 TC index 1 extras** (tractor, 3wheeler) — omitted from shared map;
   keep as E15 overlay.

## Database tables

Empty tables are created by migration `0023_mapping_config`. They are **not**
filled on app startup.

From `Website/backend`, after `flask db upgrade`:

```text
flask --app run:app seed-shared-config
```

If rows already exist and you want to reload these JSON files:

```text
flask --app run:app seed-shared-config --replace
```

## Runtime

Plaza ETL and E4, E5, E6, E10, E11, and E15 read vehicle class, MOP, column
aliases, header keywords, TC index, journey type, pass-type values, and header
scan defaults from the mapping tables. Local JSON still holds program-only
rules (weights, scrape, rate cutover, plaza filters) and is the seed source
for `flask --app run:app seed-shared-config`.
