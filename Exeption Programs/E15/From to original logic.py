import os
import re
import pandas as pd
import numpy as np


# =========================================================
# PATH CONFIGURATION
# =========================================================

KHW_FOLDER = r"F:\NHIT Q2 26-27\Hebbalu\Exempt file\exempt file output"
ODKH_FOLDER = r"F:\NHIT Q2 26-27\Chalegiri\base\vrn excel'"
OUTPUT_FOLDER = r"F:\NHIT Q2 26-27\Hebbalu\hebbalu to chalegiri"

FALLBACK_KHW_FOLDER = "./khw_input"
FALLBACK_ODKH_FOLDER = "./odkh_input"
FALLBACK_OUTPUT_FOLDER = "./merged_output"


# =========================================================
# HELPERS
# =========================================================

def read_excel_smart(file_path):

    try:

        df_sample = pd.read_excel(
            file_path,
            header=None,
            nrows=25
        )

        header_keywords = {
            'LANE',
            'LANENO',
            'VEHREGNO',
            'VEHREGNO.',
            'VRN',
            'TRANSACTIONID',
            'DATE',
            'DATE&TIME',
            'TIME',
            'MOP',
            'CUSTOM',
            'TCCLASS'
        }

        detected_row = 0

        for idx, row in df_sample.iterrows():

            row_str_cells = [
                str(x).upper()
                .replace(' ', '')
                .replace('_', '')
                .replace('.', '')
                for x in row.dropna()
            ]

            matches = sum(
                1
                for cell in row_str_cells
                if any(
                    kw == cell or kw in cell
                    for kw in header_keywords
                )
            )

            if matches >= 2:

                detected_row = idx
                break

        df = pd.read_excel(
            file_path,
            skiprows=detected_row
        )

    except Exception:

        df = pd.read_excel(file_path)

    df.columns = [
        str(c).strip()
        for c in df.columns
    ]

    return df


def robust_parse_time(series):

    def parse_single_val(val):

        if pd.isna(val):
            return pd.NaT

        if isinstance(val, pd.Timestamp):
            return val

        if isinstance(val, type(pd.NaT)):
            return pd.NaT

        if hasattr(val, 'hour') and hasattr(val, 'minute'):

            return pd.Timestamp(
                year=2000,
                month=1,
                day=1,
                hour=val.hour,
                minute=val.minute,
                second=getattr(val, 'second', 0)
            )

        if isinstance(val, (int, float)):

            total_seconds = int(
                round(val * 86400)
            )

            hours = (
                total_seconds // 3600
            ) % 24

            minutes = (
                total_seconds % 3600
            ) // 60

            seconds = total_seconds % 60

            return pd.Timestamp(
                year=2000,
                month=1,
                day=1,
                hour=hours,
                minute=minutes,
                second=seconds
            )

        val_str = str(val).strip()

        if not val_str or val_str.lower() in [
            'nan',
            'nat',
            'none',
            'null'
        ]:
            return pd.NaT

        formats = [
            '%I:%M:%S %p',
            '%H:%M:%S',
            '%I:%M %p',
            '%H:%M',
            '%I:%M:%S%p',
            '%I:%M%p',
            '%H:%M:%S.%f'
        ]

        for fmt in formats:

            try:

                parsed = pd.to_datetime(
                    val_str,
                    format=fmt
                )

                if pd.notna(parsed):
                    return parsed

            except Exception:
                continue

        try:

            parsed = pd.to_datetime(
                val_str,
                format='mixed'
            )

            if pd.notna(parsed):
                return parsed

        except Exception:
            pass

        return pd.NaT

    parsed_dt = series.apply(parse_single_val)

    return pd.to_datetime(
        parsed_dt,
        errors='coerce'
    )


def robust_parse_datetime(series):

    if series is None or series.empty:

        return pd.Series(
            dtype='datetime64[ns]'
        )

    if pd.api.types.is_datetime64_any_dtype(series):

        return pd.to_datetime(series)

    cleaned = (
        series
        .astype(str)
        .str.strip()
    )

    try:

        parsed = pd.to_datetime(
            cleaned,
            format='mixed',
            errors='coerce'
        )

    except Exception:

        parsed = pd.to_datetime(
            cleaned,
            errors='coerce'
        )

    formats = [
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %I:%M:%S %p',
        '%d-%m-%Y %H:%M:%S',
        '%d/%m/%Y %H:%M:%S',
        '%d-%b-%Y %I:%M:%S %p',
        '%d-%b-%Y %H:%M:%S',
        '%d-%m-%Y %I:%M:%S %p',
        '%d/%m/%Y %I:%M:%S %p'
    ]

    for fmt in formats:

        null_mask = parsed.isna()

        if not null_mask.any():
            break

        try:

            parsed[null_mask] = pd.to_datetime(
                cleaned[null_mask],
                format=fmt,
                errors='coerce'
            )

        except Exception:
            pass

    return parsed


def resolve_odkh_column_name(df, possible_sources):

    normalized_sources = [
        str(s)
        .upper()
        .replace(' ', '')
        .replace('.', '')
        .replace('_', '')
        for s in possible_sources
    ]

    for col in df.columns:

        col_normalized = (
            str(col)
            .upper()
            .replace(' ', '')
            .replace('.', '')
            .replace('_', '')
        )

        if col_normalized in normalized_sources:
            return col

    return None


def resolve_odkh_column(
    df,
    target_name,
    possible_sources
):

    if target_name in df.columns:
        return df[target_name]

    col_name = resolve_odkh_column_name(
        df,
        possible_sources
    )

    if col_name is not None:
        return df[col_name]

    print(
        f"Warning: Column matching "
        f"'{target_name}' not found. "
        f"Creating a blank column."
    )

    return pd.Series(
        np.nan,
        index=df.index
    )


# =========================================================
# MONTH-YEAR FILENAME MATCHING
# =========================================================

def extract_month_year(filename):

    filename_upper = str(filename).upper()

    months = [
        'JAN',
        'FEB',
        'MAR',
        'APR',
        'MAY',
        'JUN',
        'JUL',
        'AUG',
        'SEP',
        'OCT',
        'NOV',
        'DEC'
    ]

    found_month = None

    for m in months:

        if m in filename_upper:

            found_month = m.title()
            break

    if not found_month:
        return None

    year_match = re.search(
        r'20\d{2}',
        filename_upper
    )

    if year_match:

        return (
            found_month,
            year_match.group(0)
        )

    year_match_2d = re.search(
        r'[-_\s](\d{2})\b',
        filename_upper
    )

    if year_match_2d:

        return (
            found_month,
            "20" + year_match_2d.group(1)
        )

    year_match_end = re.search(
        r'(\d{2})\.(xlsx|xls|csv)',
        filename_upper,
        re.IGNORECASE
    )

    if year_match_end:

        return (
            found_month,
            "20" + year_match_end.group(1)
        )

    return (
        found_month,
        "2026"
    )


# =========================================================
# SIDE LOGIC
# =========================================================

def map_side_khw(lane_no):

    lane_no = (
        str(lane_no)
        .strip()
        .upper()
    )

    side_a = [
        "L1",
        "L2",
        "L3",
        "L4",
        "L5",
        "L6",
        "L7",
        "L8"
    ]

    side_b = [
        "L9",
        "L10",
        "L11", 
        "L12",
        "L13",
        "L14",
        "L15",
        "L16"
    ]

    if lane_no in side_a:

        return "Side A"

    elif lane_no in side_b:

        return "Side B"

    else:

        return "Unknown"


def map_side_odkh(lane_no):

    lane_no = (
        str(lane_no)
        .strip()
        .upper()
    )

    side_a = [
        "L1",
        "L2",
        "L3",
        "L4",
        "L5",
        "L6",
        "L7"
    ]

    side_b = ["L8","L9"," L10", "L11", "L12", "L13", "L14"
    ]
    

    if lane_no in side_a:

        return "Side A"

    elif lane_no in side_b:

        return "Side B"

    else:

        return "Unknown"


# =========================================================
# CORE MERGING ENGINE
# =========================================================

def process_and_merge(
    khw_path,
    odkh_path
):

    print(
        "\n--------------------------------------------------"
    )

    print(
        "Processing matched pair:"
    )

    print(
        f" KHW File:  {khw_path}"
    )

    print(
        f" ODKH File: {odkh_path}"
    )

    print(
        "--------------------------------------------------"
    )


    # =====================================================
    # LOAD FILES
    # =====================================================

    khw = read_excel_smart(khw_path)

    odkh = read_excel_smart(odkh_path)


    # =====================================================
    # CLEAN COLUMN NAMES
    # =====================================================

    khw.columns = [
        str(c).strip()
        for c in khw.columns
    ]

    odkh.columns = [
        str(c).strip().upper()
        for c in odkh.columns
    ]


    # =====================================================
    # NORMALIZE KHW COLUMN NAMES
    # =====================================================

    khw_rename = {}

    for col in khw.columns:

        col_clean = (
            str(col)
            .strip()
            .upper()
        )

        if col_clean in [
            'VEH REG NO.',
            'VEH REG NO',
            'VRN',
            'VEHICLE REG NO'
        ]:

            khw_rename[col] = 'Veh Reg No.'

        elif col_clean in [
            'LANE NO',
            'LANE',
            'LANE NO.'
        ]:

            khw_rename[col] = 'Lane No'

        elif col_clean == 'CUSTOM':

            khw_rename[col] = 'Custom'

        elif col_clean in [
            'DATE & TIME',
            'DATE AND TIME'
        ]:

            khw_rename[col] = 'Date & Time'

        elif col_clean == 'TIME':

            khw_rename[col] = 'TIME'


    khw = khw.rename(
        columns=khw_rename
    )


    # =====================================================
    # FILTER KHW - KEEP EXCEPTION
    # =====================================================

    if 'Custom' in khw.columns:

        khw['Custom'] = (
            khw['Custom']
            .astype(str)
            .str.strip()
            .str.lower()
        )

        khw = khw[
            khw['Custom'] == 'exception'
        ].copy()

    else:

        print(
            "Warning: 'Custom' column not found "
            "in KHW. Skipping exception filtering."
        )


    # =====================================================
    # CLEAN KHW VRN
    # =====================================================

    if 'Veh Reg No.' in khw.columns:

        khw['Veh Reg No.'] = (
            khw['Veh Reg No.']
            .astype(str)
            .str.upper()
            .str.replace(
                " ",
                "",
                regex=False
            )
            .str.strip()
        )

        khw = khw[
            khw['Veh Reg No.'].str.len() > 6
        ].copy()

    else:

        print(
            "Error: 'Veh Reg No.' "
            "column not found in KHW."
        )

        return None


    # =====================================================
    # MAP KHW SIDE
    # =====================================================

    if 'Lane No' in khw.columns:

        khw['SIDE'] = (
            khw['Lane No']
            .apply(map_side_khw)
        )

    else:

        khw['SIDE'] = 'Unknown'


    # =====================================================
    # MAP ODKH SIDE
    # =====================================================

    odkh_lane_col = resolve_odkh_column_name(
        odkh,
        [
            'LANE NO',
            'LANE',
            'LANE NO.'
        ]
    )

    if odkh_lane_col:

        odkh['SIDE'] = (
            odkh[odkh_lane_col]
            .apply(map_side_odkh)
        )

    else:

        odkh['SIDE'] = 'Unknown'


    # =====================================================
    # KHW DATE & TIME
    # =====================================================

    date_time_col = (
        'Date & Time'
        if 'Date & Time' in khw.columns
        else (
            'DATE & TIME'
            if 'DATE & TIME' in khw.columns
            else khw.columns[0]
        )
    )

    khw['DATE_TIME_KHW'] = (
        robust_parse_datetime(
            khw[date_time_col]
        )
    )


    # =====================================================
    # ODKH DATE & TIME
    # =====================================================

    odkh_date_col = resolve_odkh_column_name(
        odkh,
        [
            'DATE & TIME',
            'DATE AND TIME',
            'DATE',
            'TRANSACTION DATE'
        ]
    )

    if odkh_date_col:

        odkh['DATE_TIME_ODKH'] = (
            robust_parse_datetime(
                odkh[odkh_date_col]
            )
        )

    else:

        odkh['DATE_TIME_ODKH'] = pd.NaT


    # =====================================================
    # REMOVE INVALID DATETIME
    # =====================================================

    khw = khw[
        khw['DATE_TIME_KHW'].notna()
    ].copy()

    odkh = odkh[
        odkh['DATE_TIME_ODKH'].notna()
    ].copy()


    # =====================================================
    # CLEAN ODKH VRN
    # =====================================================

    vrn_col_odkh = resolve_odkh_column_name(
        odkh,
        [
            'VEH REG NO.',
            'VEH REG NO',
            'VRN',
            'VEHICLE NO',
            'VEHICLE REG NO'
        ]
    )

    if vrn_col_odkh:

        odkh['CLEAN_VRN'] = (
            odkh[vrn_col_odkh]
            .astype(str)
            .str.upper()
            .str.replace(
                " ",
                "",
                regex=False
            )
            .str.strip()
        )

    else:

        odkh['CLEAN_VRN'] = ''


    # =====================================================
    # SELECT ODKH COLUMNS
    # =====================================================

    odkh_subset = pd.DataFrame(
        index=odkh.index
    )

    odkh_subset['Veh Reg No.'] = (
        odkh['CLEAN_VRN']
    )

    odkh_subset['SIDE'] = (
        odkh['SIDE']
    )

    odkh_subset['DATE_TIME_ODKH'] = (
        odkh['DATE_TIME_ODKH']
    )

    odkh_subset['PAYMENT METHOD'] = (
        resolve_odkh_column(
            odkh,
            'PAYMENT METHOD',
            [
                'PAYMENT METHOD',
                'PAYMENT_METHOD',
                'MVC MOP',
                'SUB MOP',
                'MOP'
            ]
        )
    )

    odkh_subset['SVC FARE'] = (
        resolve_odkh_column(
            odkh,
            'SVC FARE',
            [
                'SVC FARE',
                'SVC',
                'FARE',
                'TOTAL FARE'
            ]
        )
    )

    odkh_subset['DESCRIPTION'] = (
        resolve_odkh_column(
            odkh,
            'DESCRIPTION',
            [
                'DESCRIPTION',
                'TC REMARK',
                'REMARK',
                'COMMENTS'
            ]
        )
    )

    odkh_subset['CCH TRANSACTION ID'] = (
        resolve_odkh_column(
            odkh,
            'CCH TRANSACTION ID',
            [
                'CCH TRANSACTION ID',
                'CCH TXN NO',
                'TRANSACTION NO',
                'TRANSACTION ID'
            ]
        )
    )


    # =====================================================
    # MERGE DATASETS
    # =====================================================

    merged = khw.merge(
        odkh_subset,
        on=[
            'Veh Reg No.',
            'SIDE'
        ],
        how='left',
        suffixes=(
            '',
            '_ODKH'
        )
    )


    # =====================================================
    # CALCULATE TIME DIFFERENCE
    # =====================================================

    merged['TIME_DIFF_HOURS'] = (
        (
            merged['DATE_TIME_KHW']
            -
            merged['DATE_TIME_ODKH']
        ).abs()
        /
        pd.Timedelta(hours=1)
    )


    # =====================================================
    # MATCH LOGIC
    # =====================================================

    merged['MATCH'] = (
        merged['TIME_DIFF_HOURS']
        .apply(
            lambda x:
                "Yes"
                if (
                    pd.notna(x)
                    and x <= 2
                )
                else "No"
        )
    )


    # =====================================================
    # FINAL FILTER
    #
    # KEEP ONLY:
    #
    # MATCH = YES
    #
    # AND
    #
    # PAYMENT METHOD != EXEMPT
    #
    # Therefore:
    #
    # MATCH YES + EXEMPT     = REMOVE
    # MATCH YES + NON-EXEMPT = KEEP
    # MATCH NO  + ANY        = REMOVE
    # =====================================================

    # -----------------------------------------------------
    # STEP 1: KEEP ONLY MATCH = YES
    # -----------------------------------------------------

    if 'MATCH' in merged.columns:

        match_clean = (
            merged['MATCH']
            .astype(str)
            .str.strip()
            .str.upper()
        )

        before_match_count = len(merged)

        merged = merged[
            match_clean == 'YES'
        ].copy()

        removed_match_count = (
            before_match_count - len(merged)
        )

        print(
            f"MATCH filter applied: "
            f"{removed_match_count} rows with "
            f"MATCH != YES removed."
        )

    else:

        print(
            "Warning: MATCH column not found."
        )


    # -----------------------------------------------------
    # STEP 2: REMOVE PAYMENT METHOD = EXEMPT
    # -----------------------------------------------------

    if 'PAYMENT METHOD' in merged.columns:

        payment_method_clean = (
            merged['PAYMENT METHOD']
            .astype(str)
            .str.strip()
            .str.upper()
        )

        before_exempt_count = len(merged)

        merged = merged[
            payment_method_clean != 'EXEMPT'
        ].copy()

        removed_exempt_count = (
            before_exempt_count - len(merged)
        )

        print(
            f"EXEMPT filter applied: "
            f"{removed_exempt_count} EXEMPT rows removed."
        )

    else:

        print(
            "Warning: PAYMENT METHOD column "
            "not found. EXEMPT filter skipped."
        )


    # =====================================================
    # KEEP LOWEST TIME DIFFERENCE
    # =====================================================

    if not merged.empty:

        merged = merged.sort_values(
            by='TIME_DIFF_HOURS',
            ascending=True
        )

        merged = merged.drop_duplicates(
            subset=[
                'Veh Reg No.',
                'DATE_TIME_KHW'
            ],
            keep='first'
        )


    # =====================================================
    # SUCCESS
    # =====================================================

    print(
        f"SUCCESS: Merged pair successfully. "
        f"Total Rows: {len(merged)}"
    )

    return merged


# =========================================================
# MAIN BATCH PROCESSING ROUTINE
# =========================================================

def main():

    # =====================================================
    # DETERMINE FOLDERS
    # =====================================================

    if (
        os.path.exists(KHW_FOLDER)
        and
        os.path.exists(ODKH_FOLDER)
    ):

        khw_dir = KHW_FOLDER
        odkh_dir = ODKH_FOLDER
        output_dir = OUTPUT_FOLDER

    else:

        print(
            "\nWarning: Could not access F: drive folders."
        )

        print(
            "\nCreating local folders for execution:"
        )

        khw_dir = FALLBACK_KHW_FOLDER
        odkh_dir = FALLBACK_ODKH_FOLDER
        output_dir = FALLBACK_OUTPUT_FOLDER

        os.makedirs(
            khw_dir,
            exist_ok=True
        )

        os.makedirs(
            odkh_dir,
            exist_ok=True
        )

        print(
            f" - Place KHW Excel files in: "
            f"'{khw_dir}'"
        )

        print(
            f" - Place ODKH Excel files in: "
            f"'{odkh_dir}'"
        )


    os.makedirs(
        output_dir,
        exist_ok=True
    )


    # =====================================================
    # SCAN DIRECTORIES
    # =====================================================

    khw_files = [
        f
        for f in os.listdir(khw_dir)
        if f.endswith(
            (
                '.xlsx',
                '.xls',
                '.csv'
            )
        )
        and not f.startswith('~$')
    ]

    odkh_files = [
        f
        for f in os.listdir(odkh_dir)
        if f.endswith(
            (
                '.xlsx',
                '.xls',
                '.csv'
            )
        )
        and not f.startswith('~$')
    ]


    print(
        "\nScanning Input Folders:"
    )

    print(
        f" -> KHW Folder ('{khw_dir}'): "
        f"found {len(khw_files)} files: "
        f"{khw_files}"
    )

    print(
        f" -> ODKH Folder ('{odkh_dir}'): "
        f"found {len(odkh_files)} files: "
        f"{odkh_files}"
    )


    # =====================================================
    # MAP KHW MONTHS
    # =====================================================

    khw_mapped = {}

    for f in khw_files:

        my = extract_month_year(f)

        if my:

            khw_mapped[my] = f


    # =====================================================
    # MATCH KHW AND ODKH FILES
    # =====================================================

    matches = []

    for f in odkh_files:

        my = extract_month_year(f)

        if (
            my
            and
            my in khw_mapped
        ):

            matches.append(
                {
                    'month_year': my,
                    'khw_file': khw_mapped[my],
                    'odkh_file': f
                }
            )


    # =====================================================
    # FALLBACK IF ONE FILE EACH
    # =====================================================

    if (
        not matches
        and
        len(khw_files) == 1
        and
        len(odkh_files) == 1
    ):

        print(
            "\nNo month-name matches found, "
            "but exactly 1 file exists in each folder."
        )

        print(
            "Merging them directly..."
        )

        matches.append(
            {
                'month_year': (
                    'Merged',
                    'Output'
                ),
                'khw_file': khw_files[0],
                'odkh_file': odkh_files[0]
            }
        )


    # =====================================================
    # NO MATCHING FILES
    # =====================================================

    if not matches:

        print(
            "\n===================================="
        )

        print(
            "NO MATCHING FILES FOUND TO PROCESS."
        )

        print(
            "Please check file names and "
            "month abbreviations."
        )

        print(
            "===================================="
        )

        return


    # =====================================================
    # DISPLAY MATCHED PAIRS
    # =====================================================

    print(
        f"\nFound {len(matches)} "
        f"matched pair(s) to process:"
    )


    for idx, match in enumerate(
        matches,
        1
    ):

        if isinstance(
            match['month_year'],
            tuple
        ):

            my_label = (
                f"{match['month_year'][0]}-"
                f"{match['month_year'][1]}"
            )

        else:

            my_label = str(
                match['month_year']
            )


        print(
            f" Pair {idx}: [{my_label}]"
        )

        print(
            f"   KHW  -> "
            f"{match['khw_file']}"
        )

        print(
            f"   ODKH -> "
            f"{match['odkh_file']}"
        )


    # =====================================================
    # PROCESS ALL FILES
    # =====================================================

    all_merged_dfs = []

    success_count = 0


    for match in matches:

        khw_path = os.path.join(
            khw_dir,
            match['khw_file']
        )

        odkh_path = os.path.join(
            odkh_dir,
            match['odkh_file']
        )


        try:

            merged_df = process_and_merge(
                khw_path,
                odkh_path
            )

            # -------------------------------------------------
            # IMPORTANT:
            # Even if all rows are removed by the final
            # MATCH / EXEMPT filter, do not create an empty
            # individual output file.
            # -------------------------------------------------

            if (
                merged_df is not None
                and
                not merged_df.empty
            ):

                # =================================================
                # ADD SOURCE MONTH
                # =================================================

                if isinstance(
                    match['month_year'],
                    tuple
                ):

                    month_label = (
                        f"{match['month_year'][0]} "
                        f"{match['month_year'][1]}"
                    )

                else:

                    month_label = "Merged"


                merged_df.insert(
                    0,
                    'Source Month',
                    month_label
                )


                # =================================================
                # SAVE INDIVIDUAL FILE
                # =================================================

                if isinstance(
                    match['month_year'],
                    tuple
                ):

                    ind_filename = (
                        f"mohtara_to_boharipar_"
                        f"{match['month_year'][0]}_"
                        f"{match['month_year'][1]}.xlsx"
                    )

                else:

                    ind_filename = (
                        "mohtara_to_boharipar_"
                        "individual.xlsx"
                    )


                ind_out_path = os.path.join(
                    output_dir,
                    ind_filename
                )


                merged_df.to_excel(
                    ind_out_path,
                    index=False
                )


                print(
                    f"Saved individual sheet to: "
                    f"{ind_out_path}"
                )


                # =================================================
                # ADD TO COMBINED LIST
                # =================================================

                all_merged_dfs.append(
                    merged_df
                )

                success_count += 1

            else:

                print(
                    "No data remaining after "
                    "MATCH = YES and "
                    "PAYMENT METHOD != EXEMPT filtering."
                )


        except Exception as e:

            print(
                f"ERROR processing pair: {e}"
            )


    # =========================================================
    # COMBINE ALL PROCESSED FILES
    # =========================================================

    if all_merged_dfs:

        print(
            "\nCombining all processed files "
            "into one single Excel file..."
        )


        final_combined_df = pd.concat(
            all_merged_dfs,
            ignore_index=True
        )


        # =====================================================
        # FINAL SAFETY FILTER
        #
        # This guarantees the combined output also contains
        # ONLY MATCH = YES and PAYMENT METHOD != EXEMPT.
        # =====================================================

        if 'MATCH' in final_combined_df.columns:

            final_combined_df = final_combined_df[
                final_combined_df['MATCH']
                .astype(str)
                .str.strip()
                .str.upper()
                == 'YES'
            ].copy()


        if 'PAYMENT METHOD' in final_combined_df.columns:

            final_combined_df = final_combined_df[
                final_combined_df['PAYMENT METHOD']
                .astype(str)
                .str.strip()
                .str.upper()
                != 'EXEMPT'
            ].copy()


        # =====================================================
        # FINAL OUTPUT PATH
        # =====================================================

        out_filename = (
            "mohtara_to_boharipar_combined.xlsx"
        )


        out_path = os.path.join(
            output_dir,
            out_filename
        )


        try:

            final_combined_df.to_excel(
                out_path,
                index=False
            )


            print(
                "\n===================================="
            )

            print(
                "COMBINED FILE EXPORTED SUCCESSFULLY"
            )

            print(
                "===================================="
            )

            print(
                f"Path: {out_path}"
            )

            print(
                f"Final Output Rows: "
                f"{len(final_combined_df)}"
            )


        except Exception as e:

            print(
                f"\nCould not write directly to "
                f"{out_path}"
            )

            print(
                f"Reason: {e}"
            )


            fallback_path = (
                "mohtara_to_boharipar_combined.xlsx"
            )


            print(
                f"Exporting to current folder: "
                f"{fallback_path}"
            )


            final_combined_df.to_excel(
                fallback_path,
                index=False
            )


            print(
                "COMBINED FILE EXPORTED "
                "SUCCESSFULLY TO FALLBACK PATH"
            )


    else:

        print(
            "\nNo data was successfully merged. "
            "Combined file was not created."
        )


    # =========================================================
    # COMPLETION MESSAGE
    # =========================================================

    print(
        "\n===================================="
    )

    print(
        f"BATCH RUN COMPLETED: "
        f"{success_count}/{len(matches)} "
        f"PAIRS PROCESSED SUCCESSFULLY"
    )

    print(
        f"Merged output saved in: "
        f"{output_dir}"
    )

    print(
        "FINAL CONDITION:"
    )

    print(
        "MATCH = YES"
    )

    print(
        "PAYMENT METHOD != EXEMPT"
    )

    print(
        "===================================="
    )


# =========================================================
# RUN SCRIPT
# =========================================================

if __name__ == "__main__":
    main()