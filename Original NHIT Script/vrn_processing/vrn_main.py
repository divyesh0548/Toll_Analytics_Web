from data_lookup import process_vehicle_data
from web_scrap_for_lookup import scrape_vehicle_weights
from filter_capacity import filter_by_capacity
from add_weight import add_weights_to_vrn_file
from class_validation import validate_vehicle_classes
from header_remover import remove_duplicate_headers
import pandas as pd


# Step 1: Get found and not found dataframes
print("STEP 1: Processing VRN file...")

def get_first_sheet_name(file_path: str) -> str:
    # Load Excel file metadata without reading data
    excel_file = pd.ExcelFile(file_path)
    # Get list of all sheet names
    sheet_names = excel_file.sheet_names
    # Return the first sheet name
    return sheet_names[0]

excel_file = "vrn_file.xlsx"
sheet_name = get_first_sheet_name(excel_file)


cleaned_file, header_index = remove_duplicate_headers(
        vrn_file_path=excel_file,
        sheet_name=sheet_name
    )

df_found, df_not_found = process_vehicle_data(cleaned_file, sheet_name, header_index=header_index)


# Step 2: Scrape weights for not found vehicles
print("\nSTEP 2: Scraping weights for not found vehicles...")
df_not_found_with_weights = scrape_vehicle_weights(df_not_found)

# Step 3: Add weights to VRN file
print("\nSTEP 3: Adding weights to VRN file...")
updated_vrn_file = add_weights_to_vrn_file(
    df_found=df_found,
    df_not_found_with_weights=df_not_found_with_weights,
    vrn_file='vrn_file.xlsx',
    sheet_name=sheet_name,
    header_index=header_index
)

print("\nSTEP 4: Validating vehicle classes...")
validated_vrn_file = validate_vehicle_classes(
    vrn_file_path=updated_vrn_file,
    sheet_name=sheet_name,
    header_index=header_index
)
# final_vrn_output = filter_result_column(
#     validated_file_path=validated_vrn_file,
#     sheet_name=sheet_name,
#     header_index=header_index
# )

print("\nSTEP 4: Filtering vehicles by capacity...")
capacity_dataframe = filter_by_capacity(df_found, df_not_found_with_weights, min_weight=2, max_weight=100)

# You can now combine or use them as needed
print(f"Found vehicles: {len(df_found)}")
print(f"Not found vehicles with scraped weights: {len(df_not_found_with_weights)}")
print(f"{df_not_found_with_weights.head(10)}")

# Summary
print("\n" + "=" * 80)
print("AUTOMATION WORKFLOW COMPLETED")
print("=" * 80)
print(f"Found vehicles: {len(df_found)}")
print(f"Not found vehicles (with scraped weights): {len(df_not_found_with_weights)}")
print(f"Capacity vehicles (weight 2-100): {len(capacity_dataframe)}")
print("=" * 80)

# Optional: Save capacity dataframe
capacity_dataframe.to_excel('capacity_vehicles.xlsx', index=False)
print(" Capacity vehicles saved to 'capacity_vehicles.xlsx'")