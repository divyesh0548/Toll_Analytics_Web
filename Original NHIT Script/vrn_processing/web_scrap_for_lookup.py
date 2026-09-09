"""
VRN web scraping entry point for the automation pipeline.

Uses the Chhattisgarh Checkpost Tax portal flow (state, service, weight extraction,
and database upsert) from web_scrape_chhattisgarh.py.
"""
import pandas as pd

from web_scrape_chhattisgarh import scrape_vehicle_weights

__all__ = ["scrape_vehicle_weights"]


if __name__ == "__main__":
    EXCEL_PATH = "vehicle_check_results.xlsx"
    SHEET_NAME = "Not Found"

    df_not_found = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME, dtype=str)
    print(f"Loaded {len(df_not_found)} vehicles from Excel")

    df_updated = scrape_vehicle_weights(df_not_found)

    with pd.ExcelFile(EXCEL_PATH) as xls:
        sheets_dict = {sheet: pd.read_excel(xls, sheet_name=sheet) for sheet in xls.sheet_names}

    sheets_dict[SHEET_NAME] = df_updated

    with pd.ExcelWriter(EXCEL_PATH, engine="openpyxl") as writer:
        for sheet, data in sheets_dict.items():
            data.to_excel(writer, sheet_name=sheet, index=False)

    print(f"[OK] Results saved back to '{EXCEL_PATH}'")
