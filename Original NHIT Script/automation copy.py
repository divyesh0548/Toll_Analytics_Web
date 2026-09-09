import os
import shutil
import requests
import psycopg2
from io import BytesIO
from datetime import datetime
from pathlib import Path
from vrn_processing.utility_functions import upload_file_to_s3, send_email_to_plaza, read_csv_with_header_detection
import subprocess
import time
import sys
import threading
import pandas as pd
from urllib.parse import urlparse
import re
from vrn_processing.env_loader import load_env_file, get_env, get_env_int

load_env_file()

DB_HOST = get_env("AUTOMATION_DB_HOST")
DB_PORT = get_env_int("AUTOMATION_DB_PORT", 5432)
DB_NAME = get_env("AUTOMATION_DB_NAME")
DB_USER = get_env("AUTOMATION_DB_USER")
DB_PASSWORD = get_env("AUTOMATION_DB_PASSWORD")


# Database connection
def get_db_connection():
    """Create and return a PostgreSQL database connection"""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        return conn
    except psycopg2.Error as e:
        print(f"Error connecting to database: {e}")
        return None


class VRNProcessingAutomation:
    
    def __init__(self, working_dir: str = "./vrn_processing", allowed_entities: list = None):
        self.working_dir = working_dir
        self.output_dir = os.path.join(working_dir, "Output_file")
        self.conn = None
        self.allowed_entities = allowed_entities if allowed_entities else []
        self._setup_directories()
        
        if self.allowed_entities:
            print(f"[OK] Entity filter enabled: {len(self.allowed_entities)} allowed entities")
            print(f"  Allowed entities: {', '.join(self.allowed_entities)}")
        else:
            print("[OK] No entity filter - processing all entities")
    
    def _setup_directories(self):
        """Create necessary directories"""
        os.makedirs(self.working_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        print(f"[OK] Working directory: {self.working_dir}")
        print(f"[OK] Output directory: {self.output_dir}")
    
    def download_file_from_s3(self, s3_url: str, local_filename: str) -> bool:
        try:
            print(f"  Downloading from: {s3_url}")
            response = requests.get(s3_url, timeout=30)
            response.raise_for_status()
            
            with open(local_filename, 'wb') as f:
                f.write(response.content)
            
            print(f"  [OK] Downloaded and saved as: {local_filename}")
            return True
            
        except requests.RequestException as e:
            print(f"  [ERROR] Download failed: {e}")
            return False
    
    def sanitize_excel_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Remove or replace invalid Excel characters from DataFrame.
        Excel doesn't support control characters (0x00-0x1F) except tab, newline, and carriage return.
        """
        df_clean = df.copy()
        
        for col in df_clean.columns:
            if df_clean[col].dtype == 'object':  # String columns
                df_clean[col] = df_clean[col].astype(str).apply(
                    lambda x: self._sanitize_string(x) if pd.notna(x) and x != 'nan' else x
                )
        
        return df_clean
    
    def _sanitize_string(self, text: str) -> str:
        """
        Remove invalid Excel characters from a string.
        Keeps printable characters and common whitespace (tab, newline, carriage return).
        """
        if not isinstance(text, str):
            return text
        
        # Remove control characters except tab (0x09), newline (0x0A), and carriage return (0x0D)
        # Control characters are 0x00-0x1F, but we want to keep 0x09, 0x0A, 0x0D
        sanitized = ''.join(
            char for char in text 
            if ord(char) >= 32 or char in '\t\n\r'  # Keep printable chars and allowed control chars
        )
        
        return sanitized


    
    def rename_to_vrn_file(self, local_path: str) -> bool:
        """Rename or convert the downloaded file to vrn_file.xlsx"""
        try:
            vrn_file_path = os.path.join(self.working_dir, "vrn_file.xlsx")
    
            # Detect extension
            _, ext = os.path.splitext(local_path)
            ext = ext.lower()

            # If CSV - convert to XLSX
            if ext == ".csv":
                print("  [INFO] CSV detected - converting to XLSX...")
                try: 
                    df = pd.read_csv(local_path)
                except Exception as e:
                    print(f"  [WARN] Direct read failed: {e}")
                    print("  [INFO] Trying header-detection fallback...")
                    df = read_csv_with_header_detection(local_path)
                
                # Sanitize data to remove invalid Excel characters
                print("  [INFO] Sanitizing data for Excel compatibility...")
                df = self.sanitize_excel_data(df)
                
                # Save as xlsx
                df.to_excel(vrn_file_path, index=False)
    
                # Remove the original .csv
                os.remove(local_path)
    
                print("  [OK] Conversion complete & saved as vrn_file.xlsx")
                return True
    
            # If XLSX - just rename
            elif ext == ".xlsx":
                shutil.move(local_path, vrn_file_path)
                print("  [OK] Renamed to vrn_file.xlsx")
                return True
    
            else:
                print(f"  [ERROR] Unsupported file type: {ext}")
                return False
    
        except Exception as e:
            print(f"  [ERROR] Rename/Conversion failed: {e}")
            return False

    
    def run_vrn_main_script(self):
        original_dir = os.getcwd()
        output_lines = []
        output_lock = threading.Lock()
        
        def read_output(pipe):
            """Read output from subprocess in a separate thread"""
            try:
                for line in pipe:
                    line = line.rstrip()
                    if line:  # Only process non-empty lines
                        with output_lock:
                            output_lines.append(line)
                        print(f"  [SCRIPT] {line}")
                        sys.stdout.flush()
            except Exception as e:
                print(f"  [ERROR] Error reading output: {e}")
        
        try:
            print("  Running VRN processing script...")
            print("  [LOG] Output will be streamed in real-time below:")
            print("  [LOG] Web-scraping progress will be visible here")
            print("  " + "-"*70)
            
            # Change to working directory for script execution
            os.chdir(self.working_dir)
            
            # Execute vrn_main.py with real-time output streaming
            process = subprocess.Popen(
                ["python", "vrn_main.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Combine stderr with stdout
                text=True,
                bufsize=1,  # Line buffered
                universal_newlines=True
            )
            
            # Start thread to read output in real-time
            output_thread = threading.Thread(target=read_output, args=(process.stdout,), daemon=True)
            output_thread.start()
            
            # Wait for process to complete with timeout (3 hours for web-scraping)
            try:
                return_code = process.wait(timeout=360000)  # 3 hours timeout (10800 seconds)
                # Wait for output thread to finish reading remaining output
                output_thread.join(timeout=5)
            except subprocess.TimeoutExpired:
                print("\n  [TIMEOUT] VRN processing timeout after 3 hours")
                print("  [WARNING] Web-scraping did not complete - workflow depends on this data")
                print("  [LOG] Record will be retried in next iteration (not marked as failed)")
                print("  [LOG] Last output before timeout:")
                with output_lock:
                    if output_lines:
                        for line in output_lines[-10:]:
                            print(f"    {line}")
                process.kill()
                process.wait()
                os.chdir(original_dir)
                return "timeout"  # Special return value to indicate timeout
            
            os.chdir(original_dir)
            
            if return_code == 0:
                print("  " + "-"*70)
                print("  [OK] VRN processing completed successfully")
                return True
            else:
                print("  " + "-"*70)
                print(f"  [ERROR] VRN processing failed with return code: {return_code}")
                with output_lock:
                    if output_lines:
                        print("  Last 20 lines of output:")
                        for line in output_lines[-20:]:
                            print(f"    {line}")
                return False
                
        except subprocess.TimeoutExpired:
            print("  [ERROR] VRN processing timeout")
            os.chdir(original_dir)
            return False
        except Exception as e:
            print(f"  [ERROR] Error running script: {e}")
            import traceback
            print(f"  Traceback:\n{traceback.format_exc()}")
            os.chdir(original_dir)
            return False
    
    def rename_output_file(self, date_str: str, shift: str) -> str:
        try:
            original_file = os.path.join(self.working_dir, "vrn_file_updated.xlsx")
            final_output_file = os.path.join(self.working_dir, "vrn_file_updated_filtered.xlsx")
            
            if not os.path.exists(original_file):
                print(f"  [ERROR] Output file not found: {original_file}")
                return None
            if not os.path.exists(final_output_file):
                print(f"  [ERROR] Output file not found: {final_output_file}")
                return None
            
            # Convert date format YYYY-MM-DD to YYYYMMDD
            date_formatted = date_str.replace("-", "")
            
            # Ensure shift format
            if not shift.startswith("Shift"):
                shift = f"Shift-{shift}"
            
            new_filename = f"vrn_file_validated_{date_formatted}_{shift}.xlsx"
            new_file_path = os.path.join(self.output_dir, new_filename)
            
            final_filename = f"vrn_file_updated_filtered_{date_formatted}_{shift}.xlsx"
            final_output_filename = os.path.join(self.output_dir, final_filename)
            
            shutil.move(original_file, new_file_path)
            shutil.move(final_output_file, final_output_filename)
            print(f"  [OK] Output renamed to: {new_filename}")
            
            return new_filename, final_filename
            
        except Exception as e:
            print(f"  [ERROR] Rename output failed: {e}")
            return None
    
    def upload_to_s3_wrapper(self, file_path: str, entity_name: str, 
                            file_type: str = "vrn_validated", shift: str = "A") -> str:
        try:
            with open(file_path, 'rb') as f:
                # Extract filename from file path
                filename = os.path.basename(file_path)
                content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                
                # Use your existing upload_file_to_s3 function
                s3_url = upload_file_to_s3(
                    file=f,
                    entity_name=entity_name,
                    file_type=file_type,
                    shift=shift,
                    filename=filename,
                    content_type=content_type
                )
                
                if s3_url:
                    print(f"  [OK] Uploaded to S3: {s3_url}")
                    return s3_url
                else:
                    print(f"  [ERROR] S3 upload failed")
                    return None
                    
        except Exception as e:
            print(f"  [ERROR] Error uploading to S3: {e}")
            return None
    
    def update_database(self, checkpost_id: int, file_status: int, 
                       file_link: str = None, final_file_link: str = None) -> bool:
        try:
            conn = get_db_connection()
            if conn is None:
                return False
            
            with conn.cursor() as cursor:
                if file_link:
                    update_query = """
                        UPDATE submissions
                        SET file_status = %s, raw_output_file = %s, file_link = %s
                        WHERE id = %s
                    """
                    cursor.execute(update_query, (file_status, file_link, final_file_link, checkpost_id))
                else:
                    update_query = """
                        UPDATE submissions
                        SET file_status = %s
                        WHERE id = %s
                    """
                    cursor.execute(update_query, (file_status, checkpost_id))
                
                conn.commit()
                print(f"  [OK] Database updated (file_status={file_status})")
                return True
                
        except psycopg2.Error as e:
            print(f"  [ERROR] Database update failed: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()
    
    def update_email_sent_status(self, record_id: int, email_sent: int = 1) -> bool:
        """Update email_sent status in submissions table"""
        try:
            conn = get_db_connection()
            if conn is None:
                return False
            
            with conn.cursor() as cursor:
                update_query = """
                    UPDATE submissions
                    SET email_sent = %s
                    WHERE id = %s
                """
                cursor.execute(update_query, (email_sent, record_id))
                conn.commit()
                print(f"  [OK] Email sent status updated (email_sent={email_sent})")
                return True
                
        except psycopg2.Error as e:
            print(f"  [ERROR] Database update failed: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()
    
    def cleanup_working_files(self):
        """Delete downloaded vrn_file.xlsx after processing"""
        try:
            vrn_file_path = os.path.join(self.working_dir, "vrn_file.xlsx")
            if os.path.exists(vrn_file_path):
                os.remove(vrn_file_path)
                print(f"  [OK] Cleaned up: vrn_file.xlsx")
            
            # Optional: Clean other temporary files
            cleaned_file = os.path.join(self.working_dir, "cleaned_file.xlsx")
            if os.path.exists(cleaned_file):
                os.remove(cleaned_file)
                print(f"  [OK] Cleaned up: cleaned_file.xlsx")
                
        except Exception as e:
            print(f"  [ERROR] Cleanup failed: {e}")
    
    def cleanup_output_file(self, file_path: str) -> bool:
        """Delete output file from Output_file folder after successful S3 upload"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                filename = os.path.basename(file_path)
                print(f"  [OK] Deleted output file: {filename}")
                return True
            else:
                print(f"  [WARNING] Output file not found: {file_path}")
                return False
        except Exception as e:
            print(f"  [ERROR] Failed to delete output file: {e}")
            return False
    
    def get_shift_name(self, shift: str) -> str:
        """
        Map shift value to shift name.
        Mapping: 12_8 -> 12AM to 8AM, 8_4 -> 8AM to 4PM, 4-12 -> 4PM to 12AM
        """
        # Normalize shift value (remove "Shift-" prefix if present)
        normalized_shift = shift.replace("Shift-", "").strip()
        
        shift_mapping = {
            "12_8": "12AM to 8AM",
            "8_4": "8AM to 4PM",
            "4_12": "4PM to 12AM"
        }
        
        return shift_mapping.get(normalized_shift, normalized_shift)
    
    def check_pending_emails_old(self) -> list:
        try:
            conn = get_db_connection()
            if conn is None:
                return []
            
            with conn.cursor() as cursor:
                query = """
                    SELECT id
                    FROM submissions
                    WHERE (email_sent IS NULL OR email_sent = 0 OR email_sent::text = '')
                    AND file_status = 1
                    AND timestamp IS NOT NULL
                    AND timestamp::text != ''
                    AND (timestamp AT TIME ZONE 'Asia/Kolkata') > NOW() - INTERVAL '22 hours'
                    ORDER BY id ASC
                """
                cursor.execute(query)
                records = cursor.fetchall()
                
                record_ids = [record[0] for record in records]
                
                if record_ids:
                    print(f"[OK] Found {len(record_ids)} pending email(s) to send")
                else:
                    print("[OK] No pending emails found")
                
                return record_ids
                
        except psycopg2.Error as e:
            print(f"[ERROR] Error checking pending emails: {e}")
            return []
        finally:
            if conn:
                conn.close()
    
    def check_pending_emails(self, date: str = None, shift: str = None) -> list:
        try:
            conn = get_db_connection()
            if conn is None:
                return []
            
            with conn.cursor() as cursor:
                
                base_query = """
                    SELECT id
                    FROM submissions
                    WHERE (email_sent IS NULL OR email_sent = 0 OR email_sent::text = '')
                    AND file_status = 1
                """
                params = []
    
                if date:
                    base_query += " AND date = %s::date"
                    params.append(date)
    
                # Optional shift filter
                if shift:
                    base_query += " AND shift = %s"
                    params.append(shift)
    
                base_query += " ORDER BY created_at ASC"
    
                cursor.execute(base_query, tuple(params))
                records = cursor.fetchall()
                
                record_ids = [record[0] for record in records]
                
                if record_ids:
                    print(f"[OK] Found {len(record_ids)} pending email(s) to send")
                else:
                    print("[OK] No pending emails found")
                
                return record_ids
                
        except psycopg2.Error as e:
            print(f"[ERROR] Error checking pending emails: {e}")
            return []
        finally:
            if conn:
                conn.close()
    
    
    def fetch_email_data(self, record_id: int) -> dict:
        try:
            conn = get_db_connection()
            if conn is None:
                return None
            
            with conn.cursor() as cursor:
                # Fetch data from submissions table
                query_submissions = """
                    SELECT email, entity_name, shift, date, file_link
                    FROM submissions
                    WHERE id = %s
                """
                cursor.execute(query_submissions, (record_id,))
                submission_data = cursor.fetchone()
                
                if not submission_data:
                    print(f"  [ERROR] Record ID {record_id} not found in submissions table")
                    return None
                
                email_from_submissions, entity_name, shift, date, file_link = submission_data
                
                # Fetch email_id from email_data table where plaza_name matches entity_name
                query_email_data = """
                    SELECT email_id
                    FROM email_data
                    WHERE plaza_name = %s
                """
                cursor.execute(query_email_data, (entity_name,))
                email_data_result = cursor.fetchone()
                
                email_from_email_data = email_data_result[0] if email_data_result else None
                
                # Compare the two emails
                emails_to_send = []
                
                if email_from_submissions:
                    emails_to_send.append(email_from_submissions)
                
                if email_from_email_data:
                    # Only add if it's different from the submission email
                    if email_from_email_data != email_from_submissions:
                        emails_to_send.append(email_from_email_data)
                
                # If both are same or one is None, emails_to_send will have only one
                # If both are different, emails_to_send will have both
                
                # Get shift name from shift value
                shift_name = self.get_shift_name(shift) if shift else None
                
                result = {
                    'emails': emails_to_send,
                    'entity_name': entity_name,
                    'shift': shift,
                    'shift_name': shift_name,
                    'date': date,
                    'file_link': file_link,
                    'record_id': record_id
                }
                
                print(f"  [OK] Fetched email data for Record ID {record_id}")
                print(f"    Entity: {entity_name}, Date: {date}, Shift: {shift_name}, Emails: {emails_to_send}")
                
                return result
                
        except psycopg2.Error as e:
            print(f"  [ERROR] Error fetching email data: {e}")
            return None
        finally:
            if conn:
                conn.close()
    
    def check_and_process_pending_emails(self, date=None, shift=None):
        pending_email_ids = self.check_pending_emails(date=date, shift=shift)
        # pending_email_ids =self.check_pending_emails_old()
        
        if not pending_email_ids:
            print("No pending emails to process")
            return
        
        email_data_list = []
        for record_id in pending_email_ids:
            email_data = self.fetch_email_data(record_id)
            if email_data:
                email_data_list.append(email_data)
        
        if not email_data_list:
            print("\n[ERROR] Failed to fetch email data for pending emails")
            return []
        
        print(f"\n[OK] Prepared {len(email_data_list)} email data record(s) for sending")
        
        # Send emails and update database
        successful_sends = 0
        failed_sends = 0
        
        for email_data in email_data_list:
            record_id = email_data.get('record_id')
            entity_name = email_data.get('entity_name', 'Unknown')
            
            print(f"\n  Sending email for Record ID: {record_id} ({entity_name})...")
            
            # Send email
            if send_email_to_plaza(email_data):
                # Update email_sent status to 1
                if self.update_email_sent_status(record_id, email_sent=1):
                    successful_sends += 1
                    print(f"  [OK] Email sent and database updated for Record ID {record_id}")
                else:
                    failed_sends += 1
                    print(f"  [WARNING] Email sent but database update failed for Record ID {record_id}")
            else:
                failed_sends += 1
                print(f"  [ERROR] Failed to send email for Record ID {record_id}")
        
        print(f"\n[SUMMARY] Email sending completed:")
        print(f"  Successful: {successful_sends}")
        print(f"  Failed: {failed_sends}")
        
        return email_data_list
    
    def fetch_pending_files_old(self) -> list:
        try:
            conn = get_db_connection()
            if conn is None:
                return []
            
            with conn.cursor() as cursor:
                # Build query with entity filter if allowed_entities is specified
                if self.allowed_entities:
                    
                    #Old and default query ==========================
                    
                    # placeholders = ','.join(['%s'] * len(self.allowed_entities))
                    # query = f"""
                    #     SELECT id, vrn_file_url, date, shift, entity_name
                    #     FROM submissions
                    #     WHERE (file_status IS NULL OR file_status = 0 OR file_status::text = '')
                    #     AND entity_name IN ({placeholders})
                    #     ORDER BY created_at ASC
                    # """
                    # cursor.execute(query, tuple(self.allowed_entities))
                    
                    
                    #New query with time filter
                    placeholders = ','.join(['%s'] * len(self.allowed_entities))
                    query = f"""
                        SELECT id, vrn_file_url, date, shift, entity_name
                        FROM submissions
                        WHERE (file_status IS NULL OR file_status = 0 OR file_status::text = '')
                        AND entity_name IN ({placeholders})
                        AND timestamp IS NOT NULL
                        AND timestamp::text != ''
                        AND (timestamp AT TIME ZONE 'Asia/Kolkata') > NOW() - INTERVAL '40 hours'
                        ORDER BY id ASC
                    """
                    # AND timestamp < NOW() - INTERVAL '10 hours'
                    cursor.execute(query, tuple(self.allowed_entities))
                else:
                    query = f"""
                        SELECT id, vrn_file_url, date, shift, entity_name
                        FROM submissions
                        WHERE (file_status IS NULL OR file_status = 0 OR file_status::text = '')
                        AND timestamp IS NOT NULL
                        AND timestamp::text != ''
                        AND (timestamp AT TIME ZONE 'Asia/Kolkata') > NOW() - INTERVAL '20 hours'
                        ORDER BY id ASC
                    """
                    cursor.execute(query)
                
                records = cursor.fetchall()
                
                if self.allowed_entities:
                    print(f"[OK] Found {len(records)} pending files to process (filtered by {len(self.allowed_entities)} entities)")
                else:
                    print(f"[OK] Found {len(records)} pending files to process")
                
                return records
                
        except psycopg2.Error as e:
            print(f"[ERROR] Error fetching records: {e}")
            return []
        finally:
            if conn:
                conn.close()
    
    def fetch_pending_files(self, date: str = None, shift: str = None) -> list:
        try:
            conn = get_db_connection()
            if conn is None:
                return []
            
            with conn.cursor() as cursor:
    
                # Base query
                base_query = """
                    SELECT id, vrn_file_url, date, shift, entity_name
                    FROM submissions
                    WHERE (file_status IS NULL OR file_status = 0 OR file_status::text = '')
                """
    
                params = []
    
                # Add allowed_entities filter
                if self.allowed_entities:
                    placeholders = ','.join(['%s'] * len(self.allowed_entities))
                    base_query += f" AND entity_name IN ({placeholders})"
                    params.extend(self.allowed_entities)
    
                # Add optional date filter
                if date:
                    base_query += " AND date = %s"
                    params.append(date)
    
                # Add optional shift filter
                if shift:
                    base_query += " AND shift = %s"
                    params.append(shift)
    
                # Sort by oldest first
                base_query += " ORDER BY created_at ASC"
    
                cursor.execute(base_query, tuple(params))
                records = cursor.fetchall()
    
                if self.allowed_entities:
                    print(f"[OK] Found {len(records)} pending files to process (filtered by entities)")
                else:
                    print(f"[OK] Found {len(records)} pending files to process")
    
                return records
    
        except psycopg2.Error as e:
            print(f"[ERROR] Error fetching records: {e}")
            return []
        finally:
            if conn:
                conn.close()

    
    def process_all_files(self):
        print("\n" + "="*80)
        print("VRN FILE BATCH PROCESSING AUTOMATION - CONTINUOUS MODE")
        print("="*80)
        print("Program will keep running. Press Ctrl+C to stop.")
        print("="*80)
        
        iteration = 0
        
        while True:
            iteration += 1
            if iteration > 10000:
                iteration = 1
            
            print(f"\n{'='*80}")
            print(f"ITERATION {iteration} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*80}")
            
            # Fetch all pending files
            pending_files = self.fetch_pending_files_old()
            # pending_files = self.fetch_pending_files(date="2026-02-07", shift="4_12")
            
            if not pending_files:
                print("No pending files to process")
            else:
                # Process each file
                for idx, (record_id, vrn_url, date, shift, entity_name) in enumerate(pending_files, 1):
                    # Additional safety check: skip if entity not in allowed list
                    if self.allowed_entities and entity_name not in self.allowed_entities:
                        print(f"\n[{idx}/{len(pending_files)}] Skipping Record ID: {record_id}")
                        print(f"  Entity '{entity_name}' not in allowed list")
                        continue
                    
                    print(f"\n[{idx}/{len(pending_files)}] Processing Record ID: {record_id}")
                    print(f"  URL: {vrn_url}")
                    print(f"  Date: {date} | Shift: {shift} | Entity: {entity_name}")
                    
                    try:
                        # Step 1: Download file
                        print("\n  STEP 1: Downloading file...")
                        url_path = urlparse(vrn_url).path 
                        _, ext = os.path.splitext(url_path)
                        temp_filename = os.path.join(
                            self.working_dir, 
                            f"vrn_temp_{record_id}{ext}"
                        )
                        
                        if not self.download_file_from_s3(vrn_url, temp_filename):
                            print("  [WARNING] Download failed, skipping this file")
                            continue
                        
                        # 2. Rename to vrn_file.xlsx
                        print("\n  STEP 2: Renaming file...")
                        if not self.rename_to_vrn_file(temp_filename):
                            print("  [WARNING] Rename failed, skipping this file")
                            continue
                        
                        # Step 3: Run VRN processing script
                        print("\n  STEP 3: Running VRN processing script...")
                        script_result = self.run_vrn_main_script()
                        
                        if script_result == "timeout":
                            # Timeout occurred - web-scraping incomplete
                            print("\n  [WARNING] Processing incomplete due to timeout")
                            print("  [INFO] Record will remain pending and be retried in next iteration")
                            print("  [INFO] Skipping remaining steps as workflow depends on web-scraping data")
                            self.cleanup_working_files()
                            continue  # Skip to next record, this one will be retried
                        elif not script_result:
                            # Script failed (not timeout)
                            print("  [WARNING] Script processing failed, skipping remaining steps")
                            self.cleanup_working_files()
                            continue
                        
                        # Step 4: Rename output file
                        print("\n  STEP 4: Renaming output file...")
                        new_filename, final_filename = self.rename_output_file(str(date), shift)
                        if not new_filename:
                            print("  [WARNING] Output file rename failed")
                            self.cleanup_working_files()
                            continue
                        
                        # Step 5: Cleanup working files (keep output files)
                        print("\n  STEP 5: Cleaning up working files...")
                        self.cleanup_working_files()
                        
                        print(f"  [OK] Record ID {record_id} processed successfully!")
                        print(f"  [INFO] Output files saved in: {self.output_dir}")
                        print(f"    - {new_filename}")
                        print(f"    - {final_filename}")
                        
                    except Exception as e:
                        print(f"  [ERROR] Unexpected error: {e}")
                        import traceback
                        print(traceback.format_exc())
                        self.cleanup_working_files()
            
            # Wait before next iteration (30 seconds)
            print(f"\n{'='*80}")
            print("Waiting 30 seconds before next check...")
            print(f"{'='*80}\n")
            time.sleep(30)


# Main execution
if __name__ == "__main__":
    # Define allowed entities (leave empty list to process all entities)
    allowed_entities = [
        "aroli",
        "dhaneshwar",
        "dukkavanipalem",
        "undavariya",
        "usaka",
        "kelapur",
        "bhojpuree",
        "boharipar",
        "khawasa",
        "khemana",
        "kherwasani",
        "kognoli",
        "madai",
        "galia",
"maigalganj",
        "chalageri",
        "daroda",
        "madapam",
        "mahasamudram",
        "tarapongi",
 "dahalapara",
        "mudhipar",
      "bankapur",
        "pullur",
        "raibha",
        "mohtara",
        "bahadrabad",
        "balibhasa",
        "odhaki_paipkhar",
        "raksha",
        "patgaon",
        "chhapar",
        "hattargi",
        "hebbalu",
        "bassi",
        # "veeravalli",   
"faridpur",
    ]
    
    # Initialize automation with entity filter
    automation = VRNProcessingAutomation(
        working_dir="./vrn_processing",
        allowed_entities=allowed_entities if allowed_entities else None
    )
    
    # Run continuous batch processing
    try:
        automation.process_all_files()
    except KeyboardInterrupt:
        print("\n\n" + "="*80)
        print("SHUTDOWN REQUESTED - Stopping automation...")
        print("="*80)
        print("Program stopped by user.")
    except Exception as e:
        print(f"\n\n[FATAL ERROR] Unexpected error: {e}")
        print("Program will exit.")
