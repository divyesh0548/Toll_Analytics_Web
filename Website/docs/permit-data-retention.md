# Permit data retention (E6)

Last updated: 2026-10-28

Scraped permit rows are stored in the analytics database, in `permit_scrape_cache`. The table is not tied to a plaza. A vehicle saved from one plaza is reused for every plaza.

## What is stored

One row per vehicle number. The number is stored with spaces and symbols removed, in upper case.

| Column | Meaning |
|---|---|
| `vehicle_reg_no` | Vehicle number. Unique. |
| `permit_type` | Permit Type |
| `permit_authorization_no` | Permit/Authorization No |
| `permit_validity` | Permit Validity, kept as text (for example `23-12-2030`) |
| `scraped_at` | When that row was last saved |

Rows with no real permit value are not saved. A scrape that returns blank or `none` is left out, so that vehicle can be scraped again.

## How long rows are kept

Rows are kept permanently. There is no 7-day expiry.

A later scrape of the same vehicle replaces that row. The previous permit type, number, validity, and `scraped_at` are overwritten.

Deleting an exception job, a File Upload batch, or a local job folder does not delete these rows.

## How E6 uses the table

When no permit file was uploaded for the run:

1. Look up each ETC vehicle in `permit_scrape_cache`.
2. Scrape Parivahan only for vehicles that are not in the table.
3. While a scrape is running, save newly scraped rows every 5 minutes, and again when that batch finishes.

The File Upload page counts “already stored” vehicles from this table.

## What is not the permit store

E6 does not read or write a shared permit Excel cache. `permit_data.xlsx` and the `E6/permit_cache` folder are not used.

An optional permit file uploaded for one job is used only for that job. It does not replace the table for later runs.

The exception result file (`etc_enriched.xlsx`) still contains the permit columns for the rows in that run. That file is the exception output, not the permit store.
