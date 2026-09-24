# Plaza analytics ETL

## Run (main entry)

```bash
cd Plaza_db_update
python run_plaza_etl.py
# or
python run_plaza_etl.py "D:\path\to\input"
```

Set in `config/settings.py`:

- `PLAZA_IDENTIFIER` — UUID from website plaza master
- `PLAZA_NAME` — display name
- `INPUT_FOLDER` — default folder of Excel/CSV files

## Pipeline

One parse per file → writes all tables:

| Module | Table |
|---|---|
| `insights/mop_distribution_per_class.py` | `mop_distribution_per_class` |
| `insights/class_distribution_per_lane.py` | `class_distribution_per_lane` |
| `insights/mop_distribution_per_lane.py` | `mop_distribution_per_lane` |
| `insights/gap_distribution_per_lane.py` | `gap_distribution_per_lane` |

Shared Excel mapping/normalization: `config/excel_config.py` + `excel_common.py`.

Legacy `module1.py` / `module2.py` / `module3.py` are superseded by `run_plaza_etl.py`.

## Module 4 (standalone — ETC revenue by class)

```bash
cd Plaza_db_update
# Edit FROM_DATE / TO_DATE / ENTITY_NAME in module4.py
python module4.py
```

Downloads ETC files via `etc_file_url` into `etc_downloads/{entity_name}/…`, then upserts hourly
`revenue_distribution_per_class` (unique on plaza + date + hour + vehicle_class; overwrite only
when new revenue is greater).