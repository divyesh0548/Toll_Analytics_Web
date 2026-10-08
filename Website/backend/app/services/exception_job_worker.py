"""Background worker: queue → download S3 inputs → run Full Exempt → update status."""

from __future__ import annotations

import gc
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

from app.extensions import db
from app.models.exception_job import ExceptionJob, ExceptionJobFile
from app.models.plaza import Plaza
from app.services.exception_job_s3 import (
    delete_keys,
    download_to_path,
    shorten_local_filename,
)
from app.services.exception_program_catalog import (
    FULL_EXEMPT_PROGRAM,
    exempt_portal_root,
)

logger = logging.getLogger(__name__)

_worker_started = False
_active_child_lock = threading.Lock()
_active_child: subprocess.Popen | None = None

_SLOT_TO_FOLDER = {
    "lc_etc": "lc_etc",
    "vrn": "vrn",
    "pass": "pass",
    "concessionaire": "concessionaire",
    "rates": "rates",
    "approved_exemption": "approved_exemption",
}


def _utc_now():
    return datetime.now(timezone.utc)


def _backend_env_path() -> Path:
    # .../Website/backend/app/services/this_file.py → Website/backend/.env
    return Path(__file__).resolve().parents[2] / ".env"


def _build_full_exempt_subprocess_env() -> dict[str, str]:
    """
    Build env for the Full Exempt subprocess.

    Header keywords load from RDS_DB_NAME=nhit (nhit_file_process).
    Metrics use Toll_Analytics_DB. Do not map DB_NAME → RDS_DB_NAME.

    Always re-read Website/backend/.env so a long-lived Flask process still
    picks up RDS_* even if it was started before those keys were added.
    """
    env: dict[str, str] = {
        str(k): str(v) for k, v in os.environ.items() if v is not None
    }

    for env_path in (
        _backend_env_path(),
        exempt_portal_root().parent / ".env",  # Exeption Programs/.env
    ):
        if not env_path.is_file():
            continue
        for key, value in dotenv_values(env_path).items():
            if value is None:
                continue
            text = str(value).strip()
            if text:
                env[str(key)] = text

    # Host/user/password fallbacks only — never DB_NAME → RDS_DB_NAME.
    if env.get("DB_HOST") and not env.get("RDS_HOST"):
        env["RDS_HOST"] = env["DB_HOST"]
    if env.get("DB_PORT") and not env.get("RDS_PORT"):
        env["RDS_PORT"] = env["DB_PORT"]
    if env.get("DB_USER") and not env.get("RDS_USER"):
        env["RDS_USER"] = env["DB_USER"]
    if env.get("DB_PASSWORD") and not env.get("RDS_PASSWORD"):
        env["RDS_PASSWORD"] = env["DB_PASSWORD"]
    if env.get("DB_NAME") and not env.get("Toll_Analytics_DB"):
        env["Toll_Analytics_DB"] = env["DB_NAME"]
    env.setdefault("Exception_Metrics_Table", "audit_exception_metrics")
    # Avoid Windows cp1252 crashes when child scripts print Unicode (e.g. →).
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    missing_rds = [
        key
        for key in ("RDS_HOST", "RDS_DB_NAME", "RDS_USER", "RDS_PASSWORD")
        if not str(env.get(key) or "").strip()
    ]
    if missing_rds:
        raise RuntimeError(
            "Missing Exempt Query DB settings (need nhit DB for header keywords): "
            + ", ".join(missing_rds)
            + f". Expected in {_backend_env_path()}"
        )
    return env


def recover_orphaned_running_jobs() -> int:
    """
    Mark jobs left as 'running' after a backend crash/restart as failed.

    The worker only picks up 'queued' jobs, so a stuck 'running' row blocks
    Retry until it is moved back to an editable status.
    """
    stuck = ExceptionJob.query.filter_by(status="running").all()
    if not stuck:
        return 0
    now = _utc_now()
    for job in stuck:
        job.status = "failed"
        job.error_message = (
            "Job was interrupted (backend stopped or crashed while status was "
            "running). Click Retry to run again."
        )
        job.progress_message = "Interrupted — marked failed on worker restart."
        job.finished_at = now
        logger.warning(
            "Recovered orphaned running job %s → failed", job.job_uuid
        )
    db.session.commit()
    return len(stuck)


def start_exception_job_worker(app) -> None:
    global _worker_started
    if _worker_started:
        return
    # Flask debug reloader spawns a parent + child; only the child has
    # WERKZEUG_RUN_MAIN=true. Without the reloader the var is unset — still start.
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    _worker_started = True

    with app.app_context():
        try:
            n = recover_orphaned_running_jobs()
            if n:
                logger.info("Recovered %s orphaned running exception job(s)", n)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to recover orphaned running jobs")

    def loop():
        while True:
            try:
                with app.app_context():
                    _process_one_queued_job()
            except Exception:  # noqa: BLE001
                logger.exception("Exception job worker loop error")
            time.sleep(3)

    thread = threading.Thread(target=loop, name="exception-job-worker", daemon=True)
    thread.start()
    logger.info("Exception job worker started")


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Force-kill child and grandchildren so Windows releases file locks."""
    if proc.poll() is not None:
        return
    pid = proc.pid
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to kill process tree for pid=%s", pid)
    try:
        proc.wait(timeout=8)
    except Exception:  # noqa: BLE001
        pass


def _release_job_resources(process_dir: Path | None, child: subprocess.Popen | None) -> None:
    """
    On failure/success end: kill pipeline child (closes its file handles),
    drop Python refs, then best-effort delete the workspace.
    """
    global _active_child
    if child is not None:
        _kill_process_tree(child)
    with _active_child_lock:
        if _active_child is child:
            _active_child = None
    # Encourage CPython to close any lingering file objects from this thread.
    gc.collect()
    time.sleep(0.4)
    if process_dir is not None:
        _safe_rmtree(process_dir)


def _process_one_queued_job() -> None:
    global _active_child

    job = (
        ExceptionJob.query.filter_by(status="queued")
        .order_by(ExceptionJob.id.asc())
        .first()
    )
    if job is None:
        return

    job.status = "running"
    job.started_at = _utc_now()
    job.progress_message = "Preparing workspace…"
    job.error_message = None
    db.session.commit()

    process_dir: Path | None = None
    child: subprocess.Popen | None = None
    failed = False
    try:
        if job.program_code != FULL_EXEMPT_PROGRAM["code"]:
            raise RuntimeError(f"Program {job.program_code!r} is not wired yet.")
        process_dir, child = _run_full_exempt_job(job)
        job.status = "succeeded"
        job.progress_message = "Completed successfully."
        job.finished_at = _utc_now()
        db.session.commit()
        _cleanup_input_files(job)
    except Exception as exc:  # noqa: BLE001
        failed = True
        logger.exception("Job %s failed", job.job_uuid)
        job.status = "failed"
        job.error_message = str(exc)
        job.progress_message = "Failed."
        job.finished_at = _utc_now()
        db.session.commit()
    finally:
        # Kill leftover children so Windows releases file locks.
        # Delete workspace only on failure (keep outputs after success).
        if failed:
            _release_job_resources(process_dir, child)
        else:
            with _active_child_lock:
                if _active_child is child:
                    _active_child = None
            gc.collect()


def _safe_rmtree(path: Path) -> bool:
    """Best-effort delete; Windows often locks Excel/CSV from a prior run."""
    if not path.exists():
        return True
    try:
        shutil.rmtree(path)
        return True
    except OSError:
        logger.warning("Could not remove locked workspace %s — leaving it", path)
        return False


def _run_full_exempt_job(
    job: ExceptionJob,
) -> tuple[Path, subprocess.Popen | None]:
    plaza = Plaza.query.filter_by(plaza_identifier=job.plaza_identifier).first()
    if plaza is None:
        raise RuntimeError(f"Plaza not found: {job.plaza_identifier}")

    # Short unique folder each run (deep portal paths hit Windows MAX_PATH).
    previous_process_name = str(job.process_name or "").strip()
    process_name = f"w_{job.job_uuid.replace('-', '')[:8]}_{uuid.uuid4().hex[:6]}"
    job.process_name = process_name
    job.progress_message = "Downloading inputs from S3…"
    db.session.commit()

    portal = exempt_portal_root()
    if not portal.is_dir():
        raise RuntimeError(f"Exempt portal not found at {portal}")

    pipeline_root = (
        portal / "File_Process" / "Exempt_Query" / "4_Full_Exempt_Pipeline"
    )
    if previous_process_name and previous_process_name != process_name:
        _safe_rmtree(pipeline_root / previous_process_name)

    process_dir = pipeline_root / process_name
    input_root = process_dir / "input"
    for folder in _SLOT_TO_FOLDER.values():
        (input_root / folder).mkdir(parents=True, exist_ok=True)
    (process_dir / "output" / "annexure").mkdir(parents=True, exist_ok=True)
    (process_dir / "Intermediate_Files").mkdir(parents=True, exist_ok=True)

    files = ExceptionJobFile.query.filter_by(job_id=job.id).all()
    if not files:
        raise RuntimeError("No input files on this job.")

    used_names: set[str] = set()
    for row in files:
        slot_folder = _SLOT_TO_FOLDER.get(row.slot)
        if not slot_folder:
            raise RuntimeError(f"Unknown input slot: {row.slot}")
        base_name = shorten_local_filename(Path(row.original_file_name).name)
        # Avoid two inputs writing the same dest name in one folder.
        if base_name.lower() in used_names:
            stem = Path(base_name).stem[:40]
            suffix = Path(base_name).suffix
            base_name = f"{stem}_{uuid.uuid4().hex[:6]}{suffix}"
        used_names.add(base_name.lower())
        dest = input_root / slot_folder / base_name
        download_to_path(row.s3_key, dest)

    job.progress_message = "Running Full Exempt Pipeline…"
    db.session.commit()

    runner = portal / "run_website_full_exempt_job.py"
    if not runner.is_file():
        raise RuntimeError(f"Runner script missing: {runner}")

    env = _build_full_exempt_subprocess_env()
    global _active_child
    child = subprocess.Popen(
        [
            sys.executable,
            str(runner),
            "--process-name",
            process_name,
            "--plaza-key",
            job.pipeline_plaza_key,
            "--plaza-identifier",
            job.plaza_identifier,
            "--update-metrics",
            "1",
        ],
        cwd=str(portal),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    with _active_child_lock:
        _active_child = child

    try:
        stdout, _ = child.communicate()
    except Exception:
        _kill_process_tree(child)
        raise

    combined = (stdout or "").strip()
    if combined:
        job.progress_message = combined[-4000:]
        db.session.commit()
    if child.returncode != 0:
        raise RuntimeError(
            combined[-2000:]
            if combined
            else f"Full Exempt Pipeline failed with exit code {child.returncode}"
        )
    return process_dir, child


def _cleanup_input_files(job: ExceptionJob) -> None:
    """Delete S3 input objects after success (keep DB rows for history of names)."""
    keys = [f.s3_key for f in job.files if f.s3_key]
    try:
        delete_keys(keys)
        job.progress_message = (
            (job.progress_message or "") + "\nInput files removed from S3."
        ).strip()
        db.session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to delete S3 inputs for job %s", job.job_uuid)
