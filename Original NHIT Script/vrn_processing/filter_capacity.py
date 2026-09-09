import pandas as pd

def filter_by_capacity(df_found, df_not_found_with_weights, min_weight=2, max_weight=100):
    print("=" * 80)
    print("FILTERING VEHICLES BY CAPACITY")
    print("=" * 80)
    
    # Combine both dataframes
    combined_df = pd.concat([df_found, df_not_found_with_weights], ignore_index=True)
    print(f"Total vehicles (found + not found): {len(combined_df)}")
    
    # Convert Weight column to numeric, handling errors
    # This handles cases like "N/A", "Error", empty strings, etc.
    combined_df['Weight_Numeric'] = pd.to_numeric(combined_df['Weight'], errors='coerce')
    
    # Filter by weight criteria (greater than min_weight and less than max_weight)
    capacity_dataframe = combined_df[
        (combined_df['Weight_Numeric'] > min_weight) & 
        (combined_df['Weight_Numeric'] < max_weight)
    ].copy()
    
    # Drop the temporary numeric column
    capacity_dataframe = capacity_dataframe.drop(columns=['Weight_Numeric'])
    
    # Calculate statistics
    valid_weights = combined_df['Weight_Numeric'].notna().sum()
    filtered_count = len(capacity_dataframe)
    excluded_count = valid_weights - filtered_count
    
    print(f"\nFiltering criteria:")
    print(f"  - Weight > {min_weight}")
    print(f"  - Weight < {max_weight}")
    print(f"\nResults:")
    print(f"  - Total vehicles with valid weights: {valid_weights}")
    print(f"  - Vehicles matching criteria: {filtered_count}")
    print(f"  - Vehicles excluded: {excluded_count}")
    
    if len(capacity_dataframe) > 0:
        print(f"\nWeight statistics for filtered vehicles:")
        print(f"  - Min weight: {capacity_dataframe['Weight'].astype(float).min():.2f}")
        print(f"  - Max weight: {capacity_dataframe['Weight'].astype(float).max():.2f}")
        print(f"  - Average weight: {capacity_dataframe['Weight'].astype(float).mean():.2f}")
    
    print("=" * 80)
    print(" Filtering completed successfully!")
    
    return capacity_dataframe


# Example usage when running standalone
if __name__ == "__main__":
    # For testing - load from Excel
    EXCEL_PATH = "vehicle_check_results.xlsx"
    
    df_found = pd.read_excel(EXCEL_PATH, sheet_name='Found')
    df_not_found = pd.read_excel(EXCEL_PATH, sheet_name='Not Found')
    
    print(f"Loaded {len(df_found)} found vehicles")
    print(f"Loaded {len(df_not_found)} not found vehicles")
    
    # Filter by capacity
    capacity_df = filter_by_capacity(df_found, df_not_found, min_weight=2, max_weight=100)
    
    print(f"\nCapacity DataFrame preview:")
    print(capacity_df.head(10))
    
    # Optional: Save to Excel
    output_file = 'capacity_vehicles.xlsx'
    capacity_df.to_excel(output_file, index=False)
    print(f"\n Capacity dataframe saved to '{output_file}'")
