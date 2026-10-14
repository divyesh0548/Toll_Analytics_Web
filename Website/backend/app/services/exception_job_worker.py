"""Background worker: queue → download S3 inputs → run Full Exempt → update status."""

from __future__ import annotations

import gc
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

from app.extensions import db
from app.models.audit_exception import AuditExceptionOutputFile
from app.models.exception_job import ExceptionJob, ExceptionJobFile
from app.models.plaza import Plaza
from app.services.analytics_program_catalog import (
    ANALYTICS_VRN_ETC_PROGRAM,
    plaza_db_update_root,
)
from app.services.exception_job_cleanup import cleanup_expired_exception_jobs
from app.services.exception_job_s3 import (
    delete_keys,
    download_to_path,
    shorten_local_filename,
    upload_bytes,
)
from app.services.exception_program_catalog import (
    E04_PROGRAM,
    E05_MAIN_PROCESS,
    E06_PROGRAM,
    E07_PROGRAM,
    E09_PROGRAM,
    E10_PROGRAM,
    E11_PROGRAM,
    E15_PROGRAM,
    FULL_EXEMPT_PROGRAM,
    VALID_INVALID_PROGRAM,
    e4_program_root,
    e5_program_root,
    e6_program_root,
    e7_program_root,
    e9_program_root,
    e10_program_root,
    e11_program_root,
    e15_program_root,
    exempt_portal_root,
    valid_invalid_script_dir,
)
from app.services.plaza_entity_map import require_entity_name
from app.services.staging_output_cleanup import cleanup_expired_staging_outputs

logger = logging.getLogger(__name__)

_SCRAPE_MODE_RE = re.compile(r"^\[\[scrape_mode=(live|export)\]\]\s*", re.I)
_SCRAPE_MODE_PN_RE = re.compile(r"\|sm=(live|export)$", re.I)
SCRAPE_EXPORT_EXIT_CODE = 42
SCRAPE_EXPORT_SLOT = "scrape_vehicles"
SCRAPE_EXPORT_FAIL_MESSAGE = (
    "Scrape skipped — download the vehicle list from this job, scrape offline, "
    "upload the scraped file, then Start again."
)

_worker_started = False
_active_child_lock = threading.Lock()
_active_children: set[subprocess.Popen] = set()
_pending_scrape_modes_lock = threading.Lock()
# Survives progress_message overwrites within this process (gunicorn 1 worker).
_pending_scrape_modes: dict[str, str] = {}
_WORKER_MAX_PARALLEL = 2
_last_staging_cleanup_at: float = 0.0
_STAGING_CLEANUP_INTERVAL_SEC = 3600
_last_job_cleanup_at: float = 0.0
_JOB_CLEANUP_INTERVAL_SEC = 12 * 3600  # every 12 hours


def remember_scrape_mode(job_uuid: str, mode: str) -> None:
    """Persist scrape mode for the worker (memory + process_name marker)."""
    cleaned = str(mode or "").strip().lower()
    if cleaned not in {"live", "export"}:
        cleaned = "live"
    with _pending_scrape_modes_lock:
        _pending_scrape_modes[str(job_uuid)] = cleaned


def encode_scrape_mode_on_process_name(job: ExceptionJob, mode: str) -> None:
    """Encode |sm=live|export on process_name so restart recovery can restore it."""
    cleaned = str(mode or "").strip().lower()
    if cleaned not in {"live", "export"}:
        cleaned = "live"
    base = str(job.process_name or "").strip()
    base = _SCRAPE_MODE_PN_RE.sub("", base).rstrip("|").strip()
    if not base:
        base = f"web_{str(job.job_uuid).replace('-', '')[:16]}"
    job.process_name = f"{base}|sm={cleaned}"


def _read_scrape_mode_from_process_name(job: ExceptionJob) -> str | None:
    pn = str(job.process_name or "")
    match = _SCRAPE_MODE_PN_RE.search(pn)
    if not match:
        return None
    return match.group(1).lower()


def _register_active_child(child: subprocess.Popen | None) -> None:
    if child is None:
        return
    with _active_child_lock:
        _active_children.add(child)


def _unregister_active_child(child: subprocess.Popen | None) -> None:
    if child is None:
        return
    with _active_child_lock:
        _active_children.discard(child)


def kill_active_job_children() -> int:
    """Force-kill every registered job subprocess (used when stopping a pipeline)."""
    with _active_child_lock:
        children = list(_active_children)
    killed = 0
    for child in children:
        try:
            if child.poll() is None:
                _kill_process_tree(child)
                killed += 1
        except Exception:  # noqa: BLE001
            logger.exception("Failed killing active child pid=%s", getattr(child, "pid", None))
        finally:
            _unregister_active_child(child)
    return killed


def remove_auto_chrome_nodes() -> int:
    """
    Force-remove Selenium Grid Chrome nodes started by E5/E6 auto-manage
    (container names like auto-chrome-node-YYYYMMDDHHMMSS-N).
    """
    try:
        listed = subprocess.run(
            ["docker", "ps", "-aq", "--filter", "name=auto-chrome-node-"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Could not list auto-chrome-node containers")
        return 0

    ids = [line.strip() for line in (listed.stdout or "").splitlines() if line.strip()]
    if not ids:
        return 0

    removed = 0
    for container_id in ids:
        try:
            result = subprocess.run(
                ["docker", "rm", "-f", container_id],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                removed += 1
            else:
                logger.warning(
                    "Failed removing chrome node %s: %s",
                    container_id,
                    (result.stderr or result.stdout or "").strip(),
                )
        except Exception:  # noqa: BLE001
            logger.exception("Failed removing chrome node %s", container_id)
    if removed:
        logger.info("Removed %s auto-chrome-node container(s)", removed)
    return removed


def stop_job_runtime_resources() -> dict[str, int]:
    """
    Kill active exception-job subprocess trees and remove auto Selenium nodes.
    Used by Mark-as-failed / pipeline stop.
    """
    killed = kill_active_job_children()
    nodes = remove_auto_chrome_nodes()
    return {"killed_children": killed, "removed_chrome_nodes": nodes}


def _job_marked_cancelled(job: ExceptionJob) -> bool:
    """True if stop/mark-failed API already stopped this job (other DB session)."""
    try:
        db.session.expire(job)
        db.session.refresh(job)
    except Exception:  # noqa: BLE001
        fresh = ExceptionJob.query.get(job.id)
        if fresh is None:
            return False
        return str(fresh.status or "") in {"cancelled", "failed"}
    return str(job.status or "") in {"cancelled", "failed"}


def _apply_external_stop_status(job: ExceptionJob) -> str:
    """
    Keep mark-failed → failed, pipeline stop → cancelled.
    Returns the status that was applied.
    """
    current = str(job.status or "")
    if current == "failed":
        # Mark-as-failed already wrote error/progress — don't overwrite.
        if job.finished_at is None:
            job.finished_at = _utc_now()
        return "failed"
    job.status = "cancelled"
    job.error_message = job.error_message or "Stopped by user"
    job.progress_message = "Stopped by user."
    job.finished_at = _utc_now()
    return "cancelled"

_SLOT_TO_FOLDER = {
    "lc_etc": "lc_etc",
    "vrn": "vrn",
    "etc": "etc",
    "pass": "pass",
    "permit": "permit",
    "from_plaza": "from_plaza",
    "concessionaire": "concessionaire",
    "rates": "rates",
    "approved_exemption": "approved_exemption",
    "lifecycle": "lifecycle",
    "invalid_table": "invalid_table",
    "ihmcl": "ihmcl",
}


def _utc_now():
    return datetime.now(timezone.utc)


def _format_runtime(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _print_job_runtime(job: ExceptionJob, elapsed_sec: float, *, ok: bool) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    outcome = "succeeded" if ok else "failed"
    print(
        f"{stamp}  JOB {job.program_code} {job.job_uuid} {outcome} "
        f"— total runtime {_format_runtime(elapsed_sec)} "
        f"({elapsed_sec:.1f}s)",
        flush=True,
    )


def _backend_env_path() -> Path:
    from app.services.repo_paths import backend_env_path

    return backend_env_path()


def _build_job_subprocess_env(*, require_rds: bool = False) -> dict[str, str]:
    """
    Single source of truth: Website/backend/.env (+ process env).

    Do not load Exeption Programs/.env or E4/.env — merge those keys into
    backend/.env instead (see backend/.env.example).
    """
    from app.services.repo_paths import (
        backend_root,
        exception_programs_root,
        plaza_db_update_root,
        repo_root,
    )

    env: dict[str, str] = {
        str(k): str(v) for k, v in os.environ.items() if v is not None
    }
    # File Upload pipeline mode sets these on the worker process. dotenv must
    # not overwrite them back to audit_exception_metrics / output_files.
    pipeline_mode = str(os.environ.get("PIPELINE_BATCH_MODE") or "").strip() == "1"
    pipeline_preserve = {
        key: str(os.environ[key])
        for key in (
            "Exception_Metrics_Table",
            "EXCEPTION_METRICS_TABLE",
            "Plaza_analytics_Table_NAME",
            "PLAZA_ANALYTICS_TABLE_NAME",
            "EXCEPTION_OUTPUT_FILES_TABLE",
            "Exception_Output_Files_Table",
            "PIPELINE_BATCH_MODE",
        )
        if pipeline_mode and os.environ.get(key)
    }

    env_path = _backend_env_path()
    if env_path.is_file():
        for key, value in dotenv_values(env_path).items():
            if value is None:
                continue
            text = str(value).strip()
            if text:
                env[str(key)] = text

    if pipeline_preserve:
        env.update(pipeline_preserve)

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
    # Path roots for scripts inside the container / local checkout.
    env.setdefault("TOLL_REPO_ROOT", str(repo_root()))
    env.setdefault("EXCEPTION_PROGRAMS_ROOT", str(exception_programs_root()))
    env.setdefault("PLAZA_DB_UPDATE_ROOT", str(plaza_db_update_root()))
    env.setdefault("WEBSITE_BACKEND_ROOT", str(backend_root()))
    # Avoid Windows cp1252 crashes when child scripts print Unicode (e.g. →).
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    if require_rds:
        missing_rds = [
            key
            for key in ("RDS_HOST", "RDS_DB_NAME", "RDS_USER", "RDS_PASSWORD")
            if not str(env.get(key) or "").strip()
        ]
        if missing_rds:
            raise RuntimeError(
                "Missing Exempt Query DB settings (need nhit DB for header keywords): "
                + ", ".join(missing_rds)
                + f". Expected in {env_path}"
            )
    return env


def _build_full_exempt_subprocess_env() -> dict[str, str]:
    """Full Exempt: RDS nhit for headers + Toll_Analytics_DB for metrics."""
    return _build_job_subprocess_env(require_rds=True)


def _build_e4_subprocess_env() -> dict[str, str]:
    """Shared env for E4–E15 / analytics job subprocesses."""
    return _build_job_subprocess_env(require_rds=False)


def _popen_job(cmd: list[str], *, cwd: str, env: dict[str, str]) -> subprocess.Popen:
    """Start a job child; new session on Linux so we can kill the process group."""
    kwargs: dict = {
        "cwd": cwd,
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "bufsize": 1,
    }
    if os.name != "nt":
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def _stream_child_output(job: ExceptionJob, child: subprocess.Popen) -> str:
    """
    Read child stdout line-by-line, keep a combined log, and promote scrape-count
    banners into job.progress_message so the website shows how many vehicles
    need scraping while the job is still running.
    """
    chunks: list[str] = []
    if child.stdout is None:
        child.wait()
        return ""
    for line in child.stdout:
        chunks.append(line)
        stripped = line.strip()
        if not stripped:
            continue
        promote = (
            "VEHICLES TO SCRAPE:" in stripped
            or stripped.startswith("Permit cache hits:")
            or stripped.startswith("Unique VRNs to scrape")
        )
        if promote:
            job.progress_message = stripped[:500]
            try:
                db.session.commit()
            except Exception:  # noqa: BLE001
                db.session.rollback()
    child.wait()
    return "".join(chunks)


def _job_failure_message(combined: str, *, limit: int = 2000) -> str:
    """Prefer the last RuntimeError/ERROR line over a mid-traceback tail slice."""
    text = (combined or "").strip()
    if not text:
        return "Job failed with no output"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in reversed(lines):
        if ln.startswith("RuntimeError:") or ln.startswith("[ERROR]"):
            return ln[:limit]
    return text[-limit:]


def recover_orphaned_running_jobs() -> int:
    """
    Re-queue jobs left as 'running' after a backend restart.

    The previous process is gone, so 'running' cannot make progress. Putting
    them back to 'queued' lets the new worker finish them (and preserves a
    real pipeline error if they fail again).

    Jobs whose parent pipeline batch is already terminal are cancelled instead,
    so they do not block a newer File Upload run after restart.
    """
    from app.models.exception_pipeline import (
        ExceptionPipelineBatch,
        ExceptionPipelineBatchStep,
    )

    stuck = ExceptionJob.query.filter_by(status="running").all()
    if not stuck:
        return 0
    recovered = 0
    cancelled = 0
    now = _utc_now()
    for job in stuck:
        parent_batch = None
        step = ExceptionPipelineBatchStep.query.filter_by(
            child_job_uuid=job.job_uuid
        ).first()
        if step is not None:
            parent_batch = step.batch
        if parent_batch is None:
            parent_batch = ExceptionPipelineBatch.query.filter_by(
                analytics_job_uuid=job.job_uuid
            ).first()

        if parent_batch is not None and str(parent_batch.status or "") in {
            "cancelled",
            "failed",
            "succeeded",
        }:
            job.status = "cancelled"
            job.error_message = (
                f"Stopped — parent batch already {parent_batch.status}."
            )
            job.progress_message = "Cancelled on restart (batch no longer active)."
            job.finished_at = now
            cancelled += 1
            logger.warning(
                "Cancelled orphaned job %s (batch %s is %s)",
                job.job_uuid,
                parent_batch.batch_uuid,
                parent_batch.status,
            )
            continue

        job.status = "queued"
        job.error_message = None
        # Preserve scrape mode across restart (was previously wiped → always live).
        saved_mode = _read_scrape_mode_from_process_name(job) or "live"
        remember_scrape_mode(job.job_uuid, saved_mode)
        job.progress_message = (
            f"[[scrape_mode={saved_mode}]]"
            "Re-queued after backend restart — worker will pick this up again."
        )
        job.finished_at = None
        recovered += 1
        logger.warning(
            "Recovered orphaned running job %s → queued (scrape_mode=%s)",
            job.job_uuid,
            saved_mode,
        )
    db.session.commit()
    if cancelled:
        logger.info(
            "Cancelled %s orphaned job(s) tied to finished batches", cancelled
        )
    return recovered


def _maybe_cleanup_staging() -> None:
    global _last_staging_cleanup_at
    now = time.time()
    if now - _last_staging_cleanup_at < _STAGING_CLEANUP_INTERVAL_SEC:
        return
    _last_staging_cleanup_at = now
    try:
        n = cleanup_expired_staging_outputs()
        if n:
            logger.info("Staging cleanup removed %s file(s)", n)
    except Exception:  # noqa: BLE001
        logger.exception("Staging output cleanup failed")


def _maybe_cleanup_expired_jobs() -> None:
    """Delete exception jobs older than 7 days (outputs kept). Runs every 12h."""
    global _last_job_cleanup_at
    now = time.time()
    if now - _last_job_cleanup_at < _JOB_CLEANUP_INTERVAL_SEC:
        return
    _last_job_cleanup_at = now
    try:
        n = cleanup_expired_exception_jobs()
        if n:
            logger.info("Expired job cleanup removed %s job(s)", n)
    except Exception:  # noqa: BLE001
        logger.exception("Expired exception job cleanup failed")


def _pop_scrape_mode(job: ExceptionJob) -> str:
    """
    Resolve live|export for this run.

    Priority: in-memory (same process) → process_name |sm= → progress_message prefix.
    Defaults to live only when nothing was recorded.
    """
    mode: str | None = None
    with _pending_scrape_modes_lock:
        mode = _pending_scrape_modes.pop(str(job.job_uuid), None)

    if mode not in {"live", "export"}:
        mode = _read_scrape_mode_from_process_name(job)

    msg = job.progress_message or ""
    match = _SCRAPE_MODE_RE.match(msg)
    if match:
        if mode not in {"live", "export"}:
            mode = match.group(1).lower()
        rest = msg[match.end() :].strip()
        job.progress_message = rest or None

    # Strip |sm= from process_name before the runner assigns a fresh folder name.
    pn = str(job.process_name or "")
    pn_match = _SCRAPE_MODE_PN_RE.search(pn)
    if pn_match:
        job.process_name = pn[: pn_match.start()].rstrip("|").strip() or None

    if mode not in {"live", "export"}:
        mode = "live"
    db.session.commit()
    logger.info("Job %s scrape_mode=%s", job.job_uuid, mode)
    return mode


def _attach_scrape_vehicles_export(job: ExceptionJob, export_path: Path) -> ExceptionJobFile:
    """Upload exported VRN CSV onto the job as slot=scrape_vehicles for download."""
    path = Path(export_path)
    if not path.is_file():
        raise RuntimeError(f"Scrape export file missing: {path}")

    plaza_name = (
        job.plaza.plaza_name
        if job.plaza is not None
        else (job.pipeline_plaza_key or job.plaza_identifier)
    )
    original_name = path.name
    data = path.read_bytes()
    uploaded = upload_bytes(
        body=data,
        plaza_name=str(plaza_name or "unknown"),
        job_uuid=job.job_uuid,
        slot=SCRAPE_EXPORT_SLOT,
        original_file_name=original_name,
        content_type="text/csv",
    )

    # Replace any previous export on this job.
    for old in ExceptionJobFile.query.filter_by(
        job_id=job.id, slot=SCRAPE_EXPORT_SLOT
    ).all():
        db.session.delete(old)

    row = ExceptionJobFile(
        job_id=job.id,
        slot=SCRAPE_EXPORT_SLOT,
        original_file_name=original_name,
        s3_key=uploaded["s3_key"],
        file_url=uploaded.get("file_url"),
        file_size_bytes=uploaded.get("file_size_bytes") or len(data),
    )
    db.session.add(row)
    db.session.commit()
    return row


def _parse_scrape_export_path(stdout: str) -> Path | None:
    marker = "SCRAPE_EXPORT_READY:"
    for line in (stdout or "").splitlines():
        text = line.strip()
        if text.startswith(marker):
            raw = text[len(marker) :].strip().strip('"')
            if raw:
                return Path(raw)
    return None


def _raise_if_scrape_export(
    job: ExceptionJob,
    *,
    returncode: int | None,
    stdout: str,
    search_dirs: list[Path] | None = None,
) -> None:
    """If the child exited with the export code, attach CSV and fail intentionally."""
    if int(returncode or 0) != SCRAPE_EXPORT_EXIT_CODE:
        return

    export_path = _parse_scrape_export_path(stdout or "")
    if export_path is None or not Path(export_path).is_file():
        for folder in search_dirs or []:
            if folder is None or not Path(folder).is_dir():
                continue
            matches = sorted(Path(folder).glob("*_vehicles_to_scrape_*.csv"))
            if matches:
                export_path = matches[-1]
                break

    if export_path is not None and Path(export_path).is_file():
        try:
            _attach_scrape_vehicles_export(job, Path(export_path))
        except Exception:  # noqa: BLE001
            logger.exception("Failed to attach scrape export for job %s", job.job_uuid)
            raise RuntimeError(
                f"{SCRAPE_EXPORT_FAIL_MESSAGE} (upload of export file failed)"
            ) from None

    raise RuntimeError(SCRAPE_EXPORT_FAIL_MESSAGE)


def start_exception_job_worker(app) -> None:
    global _worker_started
    if _worker_started:
        return
    # Always start here. run.py uses use_reloader=False so there is no
    # reloader parent/child split. The old guard
    # (debug and WERKZEUG_RUN_MAIN != "true") skipped startup entirely when
    # the reloader was off — jobs stayed "queued" forever.
    _worker_started = True

    with app.app_context():
        try:
            n = recover_orphaned_running_jobs()
            if n:
                logger.info("Recovered %s orphaned running exception job(s)", n)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to recover orphaned running jobs")
        try:
            from app.services.exception_pipeline_service import (
                reconcile_duplicate_active_batches,
            )

            n = reconcile_duplicate_active_batches()
            if n:
                logger.info(
                    "Cancelled %s older active pipeline batch(es) after restart",
                    n,
                )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to reconcile duplicate pipeline batches")
        try:
            _maybe_cleanup_staging()
        except Exception:  # noqa: BLE001
            logger.exception("Initial staging cleanup failed")
        try:
            # Runs once on startup, then every 12h from the worker loop.
            _maybe_cleanup_expired_jobs()
        except Exception:  # noqa: BLE001
            logger.exception("Initial expired job cleanup failed")

    def _run_job_in_thread(job_id: int) -> None:
        with app.app_context():
            try:
                _process_claimed_job(job_id)
            except Exception:  # noqa: BLE001
                logger.exception("Exception job worker thread error for job_id=%s", job_id)

    def loop():
        futures: set = set()
        with ThreadPoolExecutor(
            max_workers=_WORKER_MAX_PARALLEL,
            thread_name_prefix="exc-job",
        ) as pool:
            while True:
                try:
                    with app.app_context():
                        _maybe_cleanup_staging()
                        _maybe_cleanup_expired_jobs()
                        futures = {f for f in futures if not f.done()}
                        while len(futures) < _WORKER_MAX_PARALLEL:
                            job_id = _claim_next_queued_job_id()
                            if job_id is None:
                                break
                            futures.add(pool.submit(_run_job_in_thread, job_id))
                except Exception:  # noqa: BLE001
                    logger.exception("Exception job worker loop error")
                time.sleep(1 if futures else 3)

    thread = threading.Thread(target=loop, name="exception-job-worker", daemon=True)
    thread.start()
    logger.info(
        "Exception job worker started (max_parallel=%s)",
        _WORKER_MAX_PARALLEL,
    )
    print(
        f"Exception job worker started (max_parallel={_WORKER_MAX_PARALLEL})",
        flush=True,
    )


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Force-kill child and grandchildren (file locks / Chrome leftovers)."""
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
            import signal

            try:
                os.killpg(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
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
    if child is not None:
        _kill_process_tree(child)
    _unregister_active_child(child)
    # Encourage CPython to close any lingering file objects from this thread.
    gc.collect()
    time.sleep(0.4)
    if process_dir is not None:
        _safe_rmtree(process_dir)


def _claim_next_queued_job_id() -> int | None:
    """Atomically move one queued job to running; return its id (or None)."""
    job = (
        ExceptionJob.query.filter_by(status="queued")
        .order_by(ExceptionJob.id.asc())
        .first()
    )
    if job is None:
        return None
    job.status = "running"
    job.started_at = _utc_now()
    # Keep [[scrape_mode=…]] prefix from /start — _pop_scrape_mode reads it later.
    prior = job.progress_message or ""
    mode_match = _SCRAPE_MODE_RE.match(prior)
    mode_prefix = mode_match.group(0) if mode_match else ""
    job.progress_message = f"{mode_prefix}Preparing workspace…"
    job.error_message = None
    # Keep pipeline step row in sync so File Upload UI shows running, not queued.
    try:
        from app.models.exception_pipeline import ExceptionPipelineBatchStep

        step = ExceptionPipelineBatchStep.query.filter_by(
            child_job_uuid=job.job_uuid
        ).first()
        if step is not None and step.status in {"queued", "pending"}:
            step.status = "running"
            if step.started_at is None:
                step.started_at = job.started_at
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed updating pipeline step status for job %s", job.job_uuid
        )
    db.session.commit()
    return int(job.id)


def _process_one_queued_job() -> None:
    """Claim and run one queued job (used by tests / single-shot callers)."""
    job_id = _claim_next_queued_job_id()
    if job_id is None:
        return
    _process_claimed_job(job_id)


def _process_claimed_job(job_id: int) -> None:
    job = ExceptionJob.query.get(job_id)
    if job is None:
        return

    from app.services.exception_pipeline_service import (
        apply_pipeline_env_for_job,
        clear_pipeline_env,
        is_pipeline_analytics_job,
        on_analytics_job_finished,
        on_pipeline_child_finished,
        register_full_exempt_final_local,
    )

    pipeline_mode = apply_pipeline_env_for_job(job)
    pipeline_analytics = is_pipeline_analytics_job(job.job_uuid)
    process_dir: Path | None = None
    child: subprocess.Popen | None = None
    failed = False
    t0 = time.perf_counter()
    try:
        if job.program_code == FULL_EXEMPT_PROGRAM["code"]:
            process_dir, child = _run_full_exempt_job(job)
        elif job.program_code == E04_PROGRAM["code"]:
            process_dir, child = _run_e4_job(job)
        elif job.program_code == VALID_INVALID_PROGRAM["code"]:
            process_dir, child = _run_valid_invalid_job(job)
        elif job.program_code == E05_MAIN_PROCESS["code"]:
            process_dir, child = _run_e5_job(job)
        elif job.program_code == E06_PROGRAM["code"]:
            process_dir, child = _run_e6_job(job)
        elif job.program_code == E07_PROGRAM["code"]:
            process_dir, child = _run_e7_job(job)
        elif job.program_code == E09_PROGRAM["code"]:
            process_dir, child = _run_e9_job(job)
        elif job.program_code == E10_PROGRAM["code"]:
            process_dir, child = _run_e10_job(job)
        elif job.program_code == E11_PROGRAM["code"]:
            process_dir, child = _run_e11_job(job)
        elif job.program_code == E15_PROGRAM["code"]:
            process_dir, child = _run_e15_job(job)
        elif job.program_code == ANALYTICS_VRN_ETC_PROGRAM["code"]:
            process_dir, child = _run_analytics_vrn_etc_job(job)
        else:
            raise RuntimeError(f"Program {job.program_code!r} is not wired yet.")
        if _job_marked_cancelled(job):
            failed = True
            _apply_external_stop_status(job)
            db.session.commit()
            _print_job_runtime(job, time.perf_counter() - t0, ok=False)
        else:
            job.status = "succeeded"
            job.progress_message = "Completed successfully."
            job.finished_at = _utc_now()
            db.session.commit()
            # Save *_final.xlsx to S3 (monthly full_exempt_final) for E15 — pipeline
            # and separate Exempt Query jobs.
            if (
                job.program_code == FULL_EXEMPT_PROGRAM["code"]
                and process_dir is not None
            ):
                try:
                    register_full_exempt_final_local(job, process_dir)
                except Exception:  # noqa: BLE001
                    logger.exception("full_exempt_final S3 register failed")
            _print_job_runtime(job, time.perf_counter() - t0, ok=True)
            # Delete S3 inputs only after a fully successful run (retry keeps them).
            # Pipeline children / parallel analytics re-use monthly S3 keys — keep them.
            # full_exempt_final lives under monthly/ keys (not job.files) so it survives.
            if not pipeline_mode and not pipeline_analytics:
                _cleanup_input_files(job)
            # Analytics has no downloadable outputs — free local scratch.
            if job.program_code == ANALYTICS_VRN_ETC_PROGRAM["code"]:
                _release_job_resources(process_dir, child)
                process_dir = None
                child = None
    except Exception as exc:  # noqa: BLE001
        failed = True
        logger.exception("Job %s failed", job.job_uuid)
        if _job_marked_cancelled(job):
            _apply_external_stop_status(job)
        else:
            job.status = "failed"
            job.error_message = str(exc)
            job.progress_message = "Failed."
            job.finished_at = _utc_now()
        db.session.commit()
        _print_job_runtime(job, time.perf_counter() - t0, ok=False)
    finally:
        if pipeline_mode:
            try:
                on_pipeline_child_finished(job)
            except Exception:  # noqa: BLE001
                logger.exception("Pipeline batch advance failed for %s", job.job_uuid)
            clear_pipeline_env()
        if pipeline_analytics:
            try:
                on_analytics_job_finished(job)
            except Exception:  # noqa: BLE001
                logger.exception("Pipeline analytics finish hook failed for %s", job.job_uuid)
        # Kill leftover children so Windows releases file locks.
        # Delete workspace only on failure (keep outputs after success).
        # Analytics success already cleaned above; failed analytics also cleans.
        if failed:
            _release_job_resources(process_dir, child)
        else:
            _unregister_active_child(child)
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


def _stage_full_exempt_annexure_defaults(
    *,
    portal: Path,
    input_root: Path,
    plaza_key: str,
) -> None:
    """
    Copy mapped RatesAfter April / Approved Exmption defaults into the process
    input folders when the Website job did not upload those slots.
    """
    import shutil
    import sys

    key = str(plaza_key or "").strip().upper()
    if not key:
        raise RuntimeError("pipeline_plaza_key is required for Full Exempt rates lookup.")

    final_dir = (
        portal / "Scripts" / "Excempy_Query" / "Final_7_scripts"
    )
    if str(final_dir) not in sys.path:
        sys.path.insert(0, str(final_dir))
    try:
        from annexure_plaza_config import (  # noqa: WPS433
            resolve_approved_exemption_file,
            resolve_rates_file,
            uses_approved_exemption_script,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Could not load annexure_plaza_config for rates lookup: {exc}"
        ) from exc

    rates_dir = input_root / "rates"
    rates_dir.mkdir(parents=True, exist_ok=True)
    if not any(rates_dir.iterdir()):
        rates_src = resolve_rates_file(key)
        if rates_src is None or not rates_src.is_file():
            raise RuntimeError(
                f"No rates file for plaza {key!r}. "
                "Add it under Scripts/Excempy_Query/RatesAfter April "
                "(see annexure_plaza_config.json rates_files), or upload a rates file."
            )
        shutil.copy2(rates_src, rates_dir / rates_src.name)

    if uses_approved_exemption_script(key):
        approved_dir = input_root / "approved_exemption"
        approved_dir.mkdir(parents=True, exist_ok=True)
        if not any(approved_dir.iterdir()):
            approved_src = resolve_approved_exemption_file(key)
            if approved_src is None or not approved_src.is_file():
                raise RuntimeError(
                    f"Plaza {key!r} needs an Approved Exemption file. "
                    "Add it under Scripts/Excempy_Query/Approved Exmption "
                    "(see annexure_plaza_config.json), or upload one."
                )
            shutil.copy2(approved_src, approved_dir / approved_src.name)


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

    # Stage plaza default rates / approved-exemption when not uploaded on the job.
    plaza_key = str(job.pipeline_plaza_key or "").strip().upper()
    _stage_full_exempt_annexure_defaults(
        portal=portal,
        input_root=input_root,
        plaza_key=plaza_key,
    )

    job.progress_message = "Running Full Exempt Pipeline…"
    db.session.commit()

    runner = portal / "run_website_full_exempt_job.py"
    if not runner.is_file():
        raise RuntimeError(f"Runner script missing: {runner}")

    env = _build_full_exempt_subprocess_env()
    child = _popen_job(
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
    )
    _register_active_child(child)

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
            _job_failure_message(combined)
            if combined
            else f"Full Exempt Pipeline failed with exit code {child.returncode}"
        )
    return process_dir, child


def _run_e4_job(job: ExceptionJob) -> tuple[Path, subprocess.Popen | None]:
    plaza = Plaza.query.filter_by(plaza_identifier=job.plaza_identifier).first()
    if plaza is None:
        raise RuntimeError(f"Plaza not found: {job.plaza_identifier}")

    # Ensure entity_name exists before starting downloads.
    entity_name = require_entity_name(job.plaza_identifier)

    previous_process_name = str(job.process_name or "").strip()
    process_name = f"e4_{job.job_uuid.replace('-', '')[:8]}_{uuid.uuid4().hex[:6]}"
    job.process_name = process_name
    job.progress_message = f"Downloading pass files from S3 (entity={entity_name})…"
    db.session.commit()

    e4_root = e4_program_root()
    if not e4_root.is_dir():
        raise RuntimeError(f"E4 program folder not found at {e4_root}")

    jobs_root = e4_root / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    if previous_process_name and previous_process_name != process_name:
        _safe_rmtree(jobs_root / previous_process_name)

    process_dir = jobs_root / process_name
    pass_dir = process_dir / "pass"
    output_dir = process_dir / "output"
    pass_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = (
        ExceptionJobFile.query.filter_by(job_id=job.id, slot="pass")
        .order_by(ExceptionJobFile.id.asc())
        .all()
    )
    if not files:
        raise RuntimeError("No pass files on this E4 job.")

    used_names: set[str] = set()
    for row in files:
        base_name = shorten_local_filename(Path(row.original_file_name).name)
        if base_name.lower() in used_names:
            stem = Path(base_name).stem[:40]
            suffix = Path(base_name).suffix
            base_name = f"{stem}_{uuid.uuid4().hex[:6]}{suffix}"
        used_names.add(base_name.lower())
        dest = pass_dir / base_name
        download_to_path(row.s3_key, dest)

    job.progress_message = "Running E4 pipeline (pass → ETC/VRN → rates → metrics)…"
    db.session.commit()

    runner = e4_root / "run_website_e4_job.py"
    if not runner.is_file():
        raise RuntimeError(f"E4 runner script missing: {runner}")

    output_file = output_dir / "merged_pass_files.xlsx"
    env = _build_e4_subprocess_env()
    child = _popen_job(
        [
            sys.executable,
            str(runner),
            "--pass-folder",
            str(pass_dir),
            "--plaza-identifier",
            job.plaza_identifier,
            "--output-file",
            str(output_file),
            "--update-metrics",
            "1",
            "--upload-output",
            "1",
        ],
        cwd=str(e4_root),
        env=env,
    )
    _register_active_child(child)

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
            _job_failure_message(combined)
            if combined
            else f"E4 failed with exit code {child.returncode}"
        )
    return process_dir, child


def _cleanup_input_files(job: ExceptionJob) -> None:
    """Delete S3 input objects after success (keep DB rows for history of names).

    Do not delete staging invalid_table objects (is_final_output=False) — they
    expire via the 7-day staging cleanup.

    Do not delete Full Exempt finals registered as monthly inputs
    (slot=full_exempt_final) — E15 may re-attach them on later jobs.
    """
    from app.models.exception_pipeline import PlazaMonthlyExceptionInput

    staging_keys = {
        row.s3_key
        for row in AuditExceptionOutputFile.query.filter_by(is_final_output=False).all()
        if row.s3_key
    }
    monthly_exempt_keys = {
        row.s3_key
        for row in PlazaMonthlyExceptionInput.query.filter_by(
            slot="full_exempt_final"
        ).all()
        if row.s3_key
    }
    protected = staging_keys | monthly_exempt_keys
    keys = [
        f.s3_key
        for f in job.files
        if f.s3_key and f.s3_key not in protected
    ]
    if not keys:
        return
    try:
        delete_keys(keys)
        job.progress_message = (
            (job.progress_message or "") + "\nInput files removed from S3."
        ).strip()
        db.session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to delete S3 inputs for job %s", job.job_uuid)


def _run_valid_invalid_job(job: ExceptionJob) -> tuple[Path, subprocess.Popen | None]:
    entity_name = require_entity_name(job.plaza_identifier)
    previous_process_name = str(job.process_name or "").strip()
    process_name = f"vil_{job.job_uuid.replace('-', '')[:8]}_{uuid.uuid4().hex[:6]}"
    job.process_name = process_name
    job.progress_message = (
        f"Downloading lifecycle file (entity={entity_name})…"
    )
    db.session.commit()

    script_dir = valid_invalid_script_dir()
    if not script_dir.is_dir():
        raise RuntimeError(f"Valid/Invalid script folder not found: {script_dir}")

    jobs_root = script_dir / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    if previous_process_name and previous_process_name != process_name:
        _safe_rmtree(jobs_root / previous_process_name)

    process_dir = jobs_root / process_name
    input_dir = process_dir / "input"
    output_dir = process_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = (
        ExceptionJobFile.query.filter_by(job_id=job.id, slot="lifecycle")
        .order_by(ExceptionJobFile.id.asc())
        .all()
    )
    if not files:
        raise RuntimeError("No lifecycle file on this Valid/Invalid job.")

    dest = input_dir / shorten_local_filename(Path(files[0].original_file_name).name)
    download_to_path(files[0].s3_key, dest)

    job.progress_message = "Running Valid/Invalid Lookup (checkpostmaster + rates)…"
    db.session.commit()

    runner = script_dir / "run_website_valid_invalid_job.py"
    if not runner.is_file():
        raise RuntimeError(f"Valid/Invalid runner missing: {runner}")

    env = _build_full_exempt_subprocess_env()
    # Entity / plaza rates key from shared map (not Scripts plaza_rates).
    env["VALID_INVALID_PLAZA_NAME"] = entity_name
    child = _popen_job(
        [
            sys.executable,
            str(runner),
            "--lifecycle-file",
            str(dest),
            "--plaza-identifier",
            job.plaza_identifier,
            "--entity-name",
            entity_name,
            "--output-dir",
            str(output_dir),
            "--upload-staging",
            "1",
        ],
        cwd=str(script_dir),
        env=env,
    )
    _register_active_child(child)

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
            _job_failure_message(combined)
            if combined
            else f"Valid/Invalid Lookup failed with exit code {child.returncode}"
        )
    return process_dir, child


def _run_e5_job(job: ExceptionJob) -> tuple[Path, subprocess.Popen | None]:
    """
    Single E05 pipeline:
      1) lifecycle/ETC → Valid/Invalid Lookup → invalid_table.csv
      2) invalid_table + IHMCL file, or live scrape / export VRNs
    """
    scrape_mode = _pop_scrape_mode(job)
    entity_name = require_entity_name(job.plaza_identifier)
    previous_process_name = str(job.process_name or "").strip()
    process_name = f"e5_{job.job_uuid.replace('-', '')[:8]}_{uuid.uuid4().hex[:6]}"
    job.process_name = process_name
    job.progress_message = f"Downloading E05 inputs (entity={entity_name})…"
    db.session.commit()

    e5_root = e5_program_root()
    if not e5_root.is_dir():
        raise RuntimeError(f"E5 program folder not found at {e5_root}")

    script_dir = valid_invalid_script_dir()
    if not script_dir.is_dir():
        raise RuntimeError(f"Valid/Invalid script folder not found: {script_dir}")

    jobs_root = e5_root / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    if previous_process_name and previous_process_name != process_name:
        _safe_rmtree(jobs_root / previous_process_name)

    process_dir = jobs_root / process_name
    lifecycle_dir = process_dir / "lifecycle"
    ihmcl_dir = process_dir / "ihmcl"
    vil_output_dir = process_dir / "valid_invalid_output"
    e5_output_dir = process_dir / "output"
    for folder in (lifecycle_dir, ihmcl_dir, vil_output_dir, e5_output_dir):
        folder.mkdir(parents=True, exist_ok=True)

    lifecycle_paths = _download_slot_files(job, "lifecycle", lifecycle_dir)
    if not lifecycle_paths:
        raise RuntimeError("No lifecycle / ETC file on this E05 job.")
    lifecycle_dest = lifecycle_paths[0]

    ihmcl_paths = _download_slot_files(job, "ihmcl", ihmcl_dir)
    ihmcl_dest = ihmcl_paths[0] if ihmcl_paths else None
    if ihmcl_dest is None and scrape_mode not in {"live", "export"}:
        raise RuntimeError(
            "No scraped IHMCL file. Upload one, or Start with live scrape / "
            "download vehicles."
        )

    # --- Step 1: Valid / Invalid Lookup ---
    job.progress_message = "Running Valid/Invalid Lookup (checkpostmaster + rates)…"
    db.session.commit()

    vil_runner = script_dir / "run_website_valid_invalid_job.py"
    if not vil_runner.is_file():
        raise RuntimeError(f"Valid/Invalid runner missing: {vil_runner}")

    # Full-exempt env for RDS checkpostmaster / header keywords.
    vil_env = _build_full_exempt_subprocess_env()
    vil_env["VALID_INVALID_PLAZA_NAME"] = entity_name

    vil_child = _popen_job(
        [
            sys.executable,
            str(vil_runner),
            "--lifecycle-file",
            str(lifecycle_dest),
            "--plaza-identifier",
            job.plaza_identifier,
            "--entity-name",
            entity_name,
            "--output-dir",
            str(vil_output_dir),
            "--upload-staging",
            "0",
        ],
        cwd=str(script_dir),
        env=vil_env,
    )
    _register_active_child(vil_child)

    try:
        vil_stdout, _ = vil_child.communicate()
    except Exception:
        _kill_process_tree(vil_child)
        raise

    vil_combined = (vil_stdout or "").strip()
    if vil_combined:
        job.progress_message = vil_combined[-4000:]
        db.session.commit()
    if vil_child.returncode != 0:
        raise RuntimeError(
            _job_failure_message(vil_combined)
            if vil_combined
            else f"Valid/Invalid Lookup failed with exit code {vil_child.returncode}"
        )

    invalid_dest = vil_output_dir / "invalid_table.csv"
    if not invalid_dest.is_file():
        raise RuntimeError(
            f"Valid/Invalid did not produce invalid_table.csv at {invalid_dest}"
        )

    # --- Step 2: Incorrect FASTag (uploaded scrape, live scrape, or export VRNs) ---
    if ihmcl_dest is not None:
        job.progress_message = "Running E05 with uploaded IHMCL scrape file…"
        effective_scrape_mode = "live"  # unused when ihmcl present
    elif scrape_mode == "export":
        job.progress_message = "Running E05 — exporting vehicles to scrape…"
        effective_scrape_mode = "export"
    else:
        job.progress_message = (
            "Running E05 with live IHMCL scrape (SCRAPE_* in Website/backend/.env)…"
        )
        effective_scrape_mode = "live"
    db.session.commit()

    e5_runner = e5_root / "run_website_e5_job.py"
    if not e5_runner.is_file():
        raise RuntimeError(f"E5 runner script missing: {e5_runner}")

    e5_env = _build_e4_subprocess_env()
    if ihmcl_dest is None:
        e5_env["E5_SCRAPE_MODE"] = effective_scrape_mode
    logger.info(
        "E05 job %s effective_scrape_mode=%s ihmcl_upload=%s",
        job.job_uuid,
        effective_scrape_mode,
        ihmcl_dest is not None,
    )
    e5_cmd = [
        sys.executable,
        str(e5_runner),
        "--invalid-table",
        str(invalid_dest),
        "--plaza-identifier",
        job.plaza_identifier,
        "--entity-name",
        entity_name,
        "--output-dir",
        str(e5_output_dir),
        "--update-metrics",
        "1",
        "--upload-output",
        "1",
    ]
    if ihmcl_dest is not None:
        e5_cmd.extend(["--ihmcl-file", str(ihmcl_dest)])
    else:
        e5_cmd.extend(["--scrape-mode", effective_scrape_mode])

    child = _popen_job(
        e5_cmd,
        cwd=str(e5_root),
        env=e5_env,
    )
    _register_active_child(child)

    try:
        stdout = _stream_child_output(job, child)
    except Exception:
        _kill_process_tree(child)
        raise

    combined = (stdout or "").strip()
    if combined:
        # Keep a bit of Valid/Invalid context + E5 tail.
        merged = ((vil_combined[-1500:] + "\n---\n" if vil_combined else "") + combined)[
            -4000:
        ]
        job.progress_message = merged
        db.session.commit()
    _raise_if_scrape_export(
        job,
        returncode=child.returncode,
        stdout=combined,
        search_dirs=[e5_output_dir, process_dir],
    )
    if child.returncode != 0:
        raise RuntimeError(
            _job_failure_message(combined)
            if combined
            else f"E5 failed with exit code {child.returncode}"
        )
    return process_dir, child


def _download_slot_files(job: ExceptionJob, slot: str, dest_dir: Path) -> list[Path]:
    """Download all job files for a slot into dest_dir; return local paths."""
    files = (
        ExceptionJobFile.query.filter_by(job_id=job.id, slot=slot)
        .order_by(ExceptionJobFile.id.asc())
        .all()
    )
    if not files:
        return []
    dest_dir.mkdir(parents=True, exist_ok=True)
    used_names: set[str] = set()
    paths: list[Path] = []
    for row in files:
        base_name = shorten_local_filename(Path(row.original_file_name).name)
        if base_name.lower() in used_names:
            stem = Path(base_name).stem[:40]
            suffix = Path(base_name).suffix
            base_name = f"{stem}_{uuid.uuid4().hex[:6]}{suffix}"
        used_names.add(base_name.lower())
        dest = dest_dir / base_name
        paths.append(download_to_path(row.s3_key, dest))
    return paths


def _run_e6_job(job: ExceptionJob) -> tuple[Path, subprocess.Popen | None]:
    scrape_mode = _pop_scrape_mode(job)
    entity_name = require_entity_name(job.plaza_identifier)
    previous_process_name = str(job.process_name or "").strip()
    process_name = f"e6_{job.job_uuid.replace('-', '')[:8]}_{uuid.uuid4().hex[:6]}"
    job.process_name = process_name
    job.progress_message = f"Downloading E06 inputs (entity={entity_name})…"
    db.session.commit()

    e6_root = e6_program_root()
    if not e6_root.is_dir():
        raise RuntimeError(f"E6 program folder not found at {e6_root}")

    jobs_root = e6_root / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    if previous_process_name and previous_process_name != process_name:
        _safe_rmtree(jobs_root / previous_process_name)

    process_dir = jobs_root / process_name
    etc_dir = process_dir / "etc"
    vrn_dir = process_dir / "vrn"
    permit_dir = process_dir / "permit"
    output_dir = process_dir / "output"
    etc_dir.mkdir(parents=True, exist_ok=True)
    vrn_dir.mkdir(parents=True, exist_ok=True)
    permit_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    etc_paths = _download_slot_files(job, "etc", etc_dir)
    if not etc_paths:
        raise RuntimeError("No ETC files on this E06 job.")
    vrn_paths = _download_slot_files(job, "vrn", vrn_dir)
    if not vrn_paths:
        raise RuntimeError("No VRN files on this E06 job.")
    permit_paths = _download_slot_files(job, "permit", permit_dir)

    if permit_paths:
        job.progress_message = "Running E06 with uploaded permit files…"
        effective_scrape_mode = "live"
    elif scrape_mode == "export":
        job.progress_message = "Running E06 — exporting vehicles to scrape…"
        effective_scrape_mode = "export"
    else:
        job.progress_message = (
            "Running E06 (live permit scrape — see SCRAPE_* in Website/backend/.env)…"
        )
        effective_scrape_mode = "live"
    db.session.commit()

    runner = e6_root / "run_website_e6_job.py"
    if not runner.is_file():
        raise RuntimeError(f"E6 runner script missing: {runner}")

    env = _build_e4_subprocess_env()
    # Force mode into child env (CLI also sets it; this survives dotenv quirks).
    if not permit_paths:
        env["E6_SCRAPE_MODE"] = effective_scrape_mode
    logger.info(
        "E06 job %s effective_scrape_mode=%s permit_upload=%s",
        job.job_uuid,
        effective_scrape_mode,
        bool(permit_paths),
    )

    output_file = output_dir / "etc_enriched.xlsx"
    cmd = [
        sys.executable,
        str(runner),
        "--etc-folder",
        str(etc_dir),
        "--vrn-folder",
        str(vrn_dir),
        "--plaza-identifier",
        job.plaza_identifier,
        "--entity-name",
        entity_name,
        "--output-file",
        str(output_file),
        "--update-metrics",
        "1",
        "--upload-output",
        "1",
    ]
    if permit_paths:
        cmd.extend(["--permit-folder", str(permit_dir)])
    else:
        cmd.extend(["--scrape-mode", effective_scrape_mode])

    child = _popen_job(
        cmd,
        cwd=str(e6_root),
        env=env,
    )
    _register_active_child(child)

    try:
        stdout = _stream_child_output(job, child)
    except Exception:
        _kill_process_tree(child)
        raise

    combined = (stdout or "").strip()
    if combined:
        job.progress_message = combined[-4000:]
        db.session.commit()
    _raise_if_scrape_export(
        job,
        returncode=child.returncode,
        stdout=combined,
        search_dirs=[output_dir, process_dir, e6_root / "permit_cache", e6_root / "output"],
    )
    if child.returncode != 0:
        raise RuntimeError(
            _job_failure_message(combined)
            if combined
            else f"E6 failed with exit code {child.returncode}"
        )
    return process_dir, child


def _run_e7_job(job: ExceptionJob) -> tuple[Path, subprocess.Popen | None]:
    plaza = Plaza.query.filter_by(plaza_identifier=job.plaza_identifier).first()
    if plaza is None:
        raise RuntimeError(f"Plaza not found: {job.plaza_identifier}")

    previous_process_name = str(job.process_name or "").strip()
    process_name = f"e7_{job.job_uuid.replace('-', '')[:8]}_{uuid.uuid4().hex[:6]}"
    job.process_name = process_name
    job.progress_message = "Downloading E07 pass files from S3…"
    db.session.commit()

    e7_root = e7_program_root()
    if not e7_root.is_dir():
        raise RuntimeError(f"E7 program folder not found at {e7_root}")

    jobs_root = e7_root / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    if previous_process_name and previous_process_name != process_name:
        _safe_rmtree(jobs_root / previous_process_name)

    process_dir = jobs_root / process_name
    pass_dir = process_dir / "pass"
    output_dir = process_dir / "output"
    pass_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = (
        ExceptionJobFile.query.filter_by(job_id=job.id, slot="pass")
        .order_by(ExceptionJobFile.id.asc())
        .all()
    )
    if not files:
        raise RuntimeError("No pass files on this E07 job.")

    used_names: set[str] = set()
    for row in files:
        base_name = shorten_local_filename(Path(row.original_file_name).name)
        if base_name.lower() in used_names:
            stem = Path(base_name).stem[:40]
            suffix = Path(base_name).suffix
            base_name = f"{stem}_{uuid.uuid4().hex[:6]}{suffix}"
        used_names.add(base_name.lower())
        dest = pass_dir / base_name
        download_to_path(row.s3_key, dest)

    job.progress_message = "Running E07 (VC4 pass Loss → metrics → S3)…"
    db.session.commit()

    runner = e7_root / "run_website_e7_job.py"
    if not runner.is_file():
        raise RuntimeError(f"E7 runner script missing: {runner}")

    output_file = output_dir / "e7_vc4_loss.csv"
    env = _build_e4_subprocess_env()

    cmd = [
        sys.executable,
        str(runner),
        "--pass-folder",
        str(pass_dir),
        "--plaza-identifier",
        job.plaza_identifier,
        "--output-file",
        str(output_file),
        "--update-metrics",
        "1",
        "--upload-output",
        "1",
    ]
    # Full pipeline: roll metrics + S3 label into the batch year/month so the
    # pipeline metrics view and download match this run (even when Loss is 0).
    try:
        from app.services.exception_pipeline_service import find_batch_step_for_job

        step = find_batch_step_for_job(job.job_uuid)
        if step is not None and step.batch is not None:
            cmd.extend(
                [
                    "--period-year",
                    str(int(step.batch.year)),
                    "--period-month",
                    str(int(step.batch.month)),
                ]
            )
    except Exception:  # noqa: BLE001
        logger.exception(
            "E07 could not resolve pipeline period for job %s", job.job_uuid
        )

    child = _popen_job(
        cmd,
        cwd=str(e7_root),
        env=env,
    )
    _register_active_child(child)

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
            _job_failure_message(combined)
            if combined
            else f"E7 failed with exit code {child.returncode}"
        )
    return process_dir, child


def _run_e9_job(job: ExceptionJob) -> tuple[Path, subprocess.Popen | None]:
    plaza = Plaza.query.filter_by(plaza_identifier=job.plaza_identifier).first()
    if plaza is None:
        raise RuntimeError(f"Plaza not found: {job.plaza_identifier}")

    previous_process_name = str(job.process_name or "").strip()
    process_name = f"e9_{job.job_uuid.replace('-', '')[:8]}_{uuid.uuid4().hex[:6]}"
    job.process_name = process_name
    job.progress_message = "Downloading E09 ETC files from S3…"
    db.session.commit()

    e9_root = e9_program_root()
    if not e9_root.is_dir():
        raise RuntimeError(f"E9 program folder not found at {e9_root}")

    jobs_root = e9_root / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    if previous_process_name and previous_process_name != process_name:
        _safe_rmtree(jobs_root / previous_process_name)

    process_dir = jobs_root / process_name
    etc_dir = process_dir / "etc"
    output_dir = process_dir / "output"
    etc_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    etc_paths = _download_slot_files(job, "etc", etc_dir)
    if not etc_paths:
        raise RuntimeError("No ETC files on this E09 job.")

    job.progress_message = "Running E09 (UNSETTLED totals → metrics → S3)…"
    db.session.commit()

    runner = e9_root / "run_website_e9_job.py"
    if not runner.is_file():
        raise RuntimeError(f"E9 runner script missing: {runner}")

    output_file = output_dir / "e9_unsettled.csv"
    env = _build_e4_subprocess_env()

    child = _popen_job(
        [
            sys.executable,
            str(runner),
            "--etc-folder",
            str(etc_dir),
            "--plaza-identifier",
            job.plaza_identifier,
            "--output-file",
            str(output_file),
            "--update-metrics",
            "1",
            "--upload-output",
            "1",
        ],
        cwd=str(e9_root),
        env=env,
    )
    _register_active_child(child)

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
            _job_failure_message(combined)
            if combined
            else f"E9 failed with exit code {child.returncode}"
        )
    return process_dir, child


def _run_e10_job(job: ExceptionJob) -> tuple[Path, subprocess.Popen | None]:
    entity_name = require_entity_name(job.plaza_identifier)
    previous_process_name = str(job.process_name or "").strip()
    process_name = f"e10_{job.job_uuid.replace('-', '')[:8]}_{uuid.uuid4().hex[:6]}"
    job.process_name = process_name
    job.progress_message = f"Downloading E10 inputs (entity={entity_name})…"
    db.session.commit()

    e10_root = e10_program_root()
    if not e10_root.is_dir():
        raise RuntimeError(f"E10 program folder not found at {e10_root}")

    jobs_root = e10_root / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    if previous_process_name and previous_process_name != process_name:
        _safe_rmtree(jobs_root / previous_process_name)

    process_dir = jobs_root / process_name
    vrn_dir = process_dir / "vrn"
    etc_dir = process_dir / "etc"
    output_dir = process_dir / "output"
    vrn_dir.mkdir(parents=True, exist_ok=True)
    etc_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    vrn_paths = _download_slot_files(job, "vrn", vrn_dir)
    if not vrn_paths:
        raise RuntimeError("No VRN files on this E10 job.")
    etc_paths = _download_slot_files(job, "etc", etc_dir)
    if not etc_paths:
        raise RuntimeError("No ETC files on this E10 job.")

    job.progress_message = (
        "Running E10 (VRN+weight+ETC → E10-A/B/C metrics + segment S3)…"
    )
    db.session.commit()

    runner = e10_root / "run_website_e10_job.py"
    if not runner.is_file():
        raise RuntimeError(f"E10 runner script missing: {runner}")

    output_file = output_dir / "e10_vrn_etc_merged.csv"
    env = _build_e4_subprocess_env()

    child = _popen_job(
        [
            sys.executable,
            str(runner),
            "--vrn-folder",
            str(vrn_dir),
            "--etc-folder",
            str(etc_dir),
            "--plaza-identifier",
            job.plaza_identifier,
            "--entity-name",
            entity_name,
            "--output-file",
            str(output_file),
            "--update-metrics",
            "1",
            "--upload-output",
            "1",
        ],
        cwd=str(e10_root),
        env=env,
    )
    _register_active_child(child)

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
            _job_failure_message(combined)
            if combined
            else f"E10 failed with exit code {child.returncode}"
        )
    return process_dir, child


def _run_e11_job(job: ExceptionJob) -> tuple[Path, subprocess.Popen | None]:
    entity_name = require_entity_name(job.plaza_identifier)
    previous_process_name = str(job.process_name or "").strip()
    process_name = f"e11_{job.job_uuid.replace('-', '')[:8]}_{uuid.uuid4().hex[:6]}"
    job.process_name = process_name
    job.progress_message = f"Downloading E11 VRN files (entity={entity_name})…"
    db.session.commit()

    e11_root = e11_program_root()
    if not e11_root.is_dir():
        raise RuntimeError(f"E11 program folder not found at {e11_root}")

    jobs_root = e11_root / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    if previous_process_name and previous_process_name != process_name:
        _safe_rmtree(jobs_root / previous_process_name)

    process_dir = jobs_root / process_name
    vrn_dir = process_dir / "vrn"
    output_dir = process_dir / "output"
    vrn_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    vrn_paths = _download_slot_files(job, "vrn", vrn_dir)
    if not vrn_paths:
        raise RuntimeError("No VRN files on this E11 job.")

    job.progress_message = "Running E11 (AVC pivot → metrics → S3)…"
    db.session.commit()

    runner = e11_root / "run_website_e11_job.py"
    if not runner.is_file():
        raise RuntimeError(f"E11 runner script missing: {runner}")

    env = _build_e4_subprocess_env()
    cmd = [
        sys.executable,
        str(runner),
        "--vrn-folder",
        str(vrn_dir),
        "--plaza-identifier",
        job.plaza_identifier,
        "--entity-name",
        entity_name,
        "--output-dir",
        str(output_dir),
        "--update-metrics",
        "1",
        "--upload-output",
        "1",
    ]
    try:
        from app.services.exception_pipeline_service import find_batch_step_for_job

        step = find_batch_step_for_job(job.job_uuid)
        if step is not None and step.batch is not None:
            cmd.extend(
                [
                    "--period-year",
                    str(int(step.batch.year)),
                    "--period-month",
                    str(int(step.batch.month)),
                ]
            )
    except Exception:  # noqa: BLE001
        logger.exception(
            "E11 could not resolve pipeline period for job %s", job.job_uuid
        )

    child = _popen_job(
        cmd,
        cwd=str(e11_root),
        env=env,
    )
    _register_active_child(child)

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
            _job_failure_message(combined)
            if combined
            else f"E11 failed with exit code {child.returncode}"
        )
    return process_dir, child


def _run_e15_job(job: ExceptionJob) -> tuple[Path, subprocess.Popen | None]:
    entity_name = require_entity_name(job.plaza_identifier)
    previous_process_name = str(job.process_name or "").strip()
    process_name = f"e15_{job.job_uuid.replace('-', '')[:8]}_{uuid.uuid4().hex[:6]}"
    job.process_name = process_name
    job.progress_message = f"Downloading E15 inputs (entity={entity_name})…"
    db.session.commit()

    e15_root = e15_program_root()
    if not e15_root.is_dir():
        raise RuntimeError(f"E15 program folder not found at {e15_root}")

    jobs_root = e15_root / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    if previous_process_name and previous_process_name != process_name:
        _safe_rmtree(jobs_root / previous_process_name)

    process_dir = jobs_root / process_name
    from_dir = process_dir / "from_plaza"
    vrn_dir = process_dir / "vrn"
    output_dir = process_dir / "output"
    from_dir.mkdir(parents=True, exist_ok=True)
    vrn_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    from_paths = _download_slot_files(job, "from_plaza", from_dir)
    if not from_paths:
        raise RuntimeError("No From-plaza exempt files on this E15 job.")
    vrn_paths = _download_slot_files(job, "vrn", vrn_dir)
    if not vrn_paths:
        raise RuntimeError("No To-plaza VRN files on this E15 job.")

    job.progress_message = (
        "Running E15 (From-To merge → rates → metrics → S3)…"
    )
    db.session.commit()

    runner = e15_root / "run_website_e15_job.py"
    if not runner.is_file():
        raise RuntimeError(f"E15 runner script missing: {runner}")

    output_file = output_dir / "from_to_combined.xlsx"
    env = _build_e4_subprocess_env()

    cmd = [
        sys.executable,
        str(runner),
        "--from-folder",
        str(from_dir),
        "--vrn-folder",
        str(vrn_dir),
        "--plaza-identifier",
        job.plaza_identifier,
        "--entity-name",
        entity_name,
        "--output-file",
        str(output_file),
        "--update-metrics",
        "1",
        "--upload-output",
        "1",
    ]
    try:
        from app.services.exception_pipeline_service import find_batch_step_for_job

        step = find_batch_step_for_job(job.job_uuid)
        if step is not None and step.batch is not None:
            cmd.extend(
                [
                    "--period-year",
                    str(int(step.batch.year)),
                    "--period-month",
                    str(int(step.batch.month)),
                ]
            )
    except Exception:  # noqa: BLE001
        logger.exception(
            "E15 could not resolve pipeline period for job %s", job.job_uuid
        )

    child = _popen_job(
        cmd,
        cwd=str(e15_root),
        env=env,
    )
    _register_active_child(child)

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
            _job_failure_message(combined)
            if combined
            else f"E15 failed with exit code {child.returncode}"
        )
    return process_dir, child


def _run_analytics_vrn_etc_job(job: ExceptionJob) -> tuple[Path, subprocess.Popen | None]:
    plaza = Plaza.query.filter_by(plaza_identifier=job.plaza_identifier).first()
    if plaza is None:
        raise RuntimeError(f"Plaza not found: {job.plaza_identifier}")

    previous_process_name = str(job.process_name or "").strip()
    process_name = f"an_{job.job_uuid.replace('-', '')[:8]}_{uuid.uuid4().hex[:6]}"
    job.process_name = process_name
    job.progress_message = "Downloading VRN/ETC inputs from S3…"
    db.session.commit()

    plaza_root = plaza_db_update_root()
    if not plaza_root.is_dir():
        raise RuntimeError(f"Plaza_db_update folder not found at {plaza_root}")

    jobs_root = plaza_root / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    if previous_process_name and previous_process_name != process_name:
        _safe_rmtree(jobs_root / previous_process_name)

    process_dir = jobs_root / process_name
    vrn_dir = process_dir / "vrn"
    etc_dir = process_dir / "etc"
    vrn_dir.mkdir(parents=True, exist_ok=True)
    etc_dir.mkdir(parents=True, exist_ok=True)

    vrn_paths = _download_slot_files(job, "vrn", vrn_dir)
    etc_paths = _download_slot_files(job, "etc", etc_dir)
    if not vrn_paths and not etc_paths:
        raise RuntimeError("No VRN or ETC files on this analytics job.")

    job.progress_message = (
        "Running plaza ETL ("
        f"{len(vrn_paths)} VRN, {len(etc_paths)} ETC)…"
    )
    db.session.commit()

    runner = plaza_root / "run_website_analytics_job.py"
    if not runner.is_file():
        raise RuntimeError(f"Analytics runner missing: {runner}")

    env = _build_e4_subprocess_env()

    cmd = [
        sys.executable,
        str(runner),
        "--plaza-identifier",
        job.plaza_identifier,
        "--plaza-name",
        str(plaza.plaza_name or "").strip() or job.plaza_identifier,
        "--start-date-limit",
        "2000-01-01",
    ]
    if vrn_paths:
        cmd.extend(["--vrn-folder", str(vrn_dir)])
    if etc_paths:
        cmd.extend(["--etc-folder", str(etc_dir)])

    child = _popen_job(
        cmd,
        cwd=str(plaza_root),
        env=env,
    )
    _register_active_child(child)

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
            _job_failure_message(combined)
            if combined
            else f"Analytics ETL failed with exit code {child.returncode}"
        )
    return process_dir, child
