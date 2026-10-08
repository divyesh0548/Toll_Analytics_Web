file_path = r"F:\NHIT Q2 26-27\odakhi\exempt files\August-26\August-vrn.csv"
def get_file_path():
    return file_path 

base_output_path = r"F:\NHIT Q2 26-27\odakhi\exempt files\August-26"

def get_base_output_path():
    return  base_output_path

file_name = "August-26.xlsx"
def put_file_name():
    return file_name

# ====== Plaza Configuration ======
plaza_name = "ODAKHI"

def get_plaza_name():
    return plaza_name

def get_local_code():
    import json
    import os
    
    json_path = os.path.join(os.path.dirname(__file__), 'codes_dump.json')
    try:
        with open(json_path, 'r') as f:
            codes = json.load(f)
            # Make case-insensitive lookup
            codes_upper = {k.upper().strip(): str(v) for k, v in codes.items()}
            raw_codes = codes_upper.get(plaza_name.upper().strip())
            
            if not raw_codes:
                return ()
            
            # Allow multiple codes separated by commas (e.g. "WB50, WB49")
            return tuple(code.strip() for code in raw_codes.replace('and', ',').split(',') if code.strip())
            
    except Exception as e:
        print(f"Warning: Could not read local code from codes_dump.json. Defaulting to null. Error: {e}")
        return ()
