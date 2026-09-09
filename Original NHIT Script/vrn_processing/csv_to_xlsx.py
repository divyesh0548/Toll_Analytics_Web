import pandas as pd
import os

def convert_csv_to_xlsx(csv_file_path, xlsx_file_path=None):
	try:
		# Validate input file exists
		if not os.path.exists(csv_file_path):
			print(f"[ERROR] File not found: {csv_file_path}")
			return None
		
		# Determine output path
		if xlsx_file_path is None:
			xlsx_file_path = os.path.splitext(csv_file_path)[0] + '.xlsx'
		
		# Read CSV
		df = pd.read_csv(csv_file_path)
		print(f"[OK] CSV file read successfully. Records: {len(df)}")
		
		# Save as XLSX
		df.to_excel(xlsx_file_path, index=False, sheet_name='VRNReport')
		print(f"[OK] Converted to XLSX format")
		print(f"[OK] File saved as: {xlsx_file_path}")
		
		return xlsx_file_path
		
	except Exception as e:
		print(f"[ERROR] Conversion failed: {e}")
		return None

# Example usage
if __name__ == "__main__":
	# Method 1: Auto-name (input.csv -> input.xlsx)
	# result = convert_csv_to_xlsx('data.csv')
	
	# Method 2: Specify output name
	result = convert_csv_to_xlsx('vrn_file.csv', 'vrn_file.xlsx')
	
	if result:
		print(f"Final file: {result}")
