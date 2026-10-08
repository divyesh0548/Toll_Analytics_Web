"""S3 helpers for exception job input files.

Layout:
  Toll Analytics Files/{plaza_folder}/{job_uuid}/{slot}/{filename}
"""

from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path

try:
    import boto3
except ImportError as exc:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]
    _BOTO3_IMPORT_ERROR = exc
else:
    _BOTO3_IMPORT_ERROR = None

S3_ROOT_PREFIX = "Toll Analytics Files"

# Keep local names short — deep Exempt portal paths easily hit Windows MAX_PATH (260).
_MAX_LOCAL_STEM = 48


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def _safe_folder(value: str) -> str:
    text = re.sub(r"[\\/]+", "_", str(value or "").strip())
    text = re.sub(r"[^\w.\- ]+", "_", text).strip(" ._")
    return text or "unknown"


def _safe_filename(value: str) -> str:
    name = Path(str(value or "file")).name
    name = re.sub(r"[^\w.\- ()+]+", "_", name).strip(" ._")
    return name or "file.bin"


def shorten_local_filename(value: str) -> str:
    """Truncate long stems so downloads under deep Windows paths stay < MAX_PATH."""
    name = _safe_filename(value)
    path = Path(name)
    stem = path.stem[:_MAX_LOCAL_STEM].rstrip(" ._") or "file"
    suffix = path.suffix[:16] if path.suffix else ""
    return f"{stem}{suffix}"


def s3_client():
    if boto3 is None:
        raise RuntimeError(
            "boto3 is required for S3. "
            f"Install it in this environment. ({_BOTO3_IMPORT_ERROR})"
        )
    return boto3.client(
        "s3",
        region_name=_require_env("AWS_REGION"),
        aws_access_key_id=_require_env("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=_require_env("AWS_SECRET_ACCESS_KEY"),
    )


def bucket_name() -> str:
    return _require_env("AWS_S3_BUCKET_NAME")


def object_url(bucket: str, region: str, key: str) -> str:
    region = (region or "us-east-1").strip()
    if region == "us-east-1":
        return f"https://{bucket}.s3.amazonaws.com/{key}"
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"


def build_input_key(
    *,
    plaza_name: str,
    job_uuid: str,
    slot: str,
    original_file_name: str,
) -> str:
    plaza_folder = _safe_folder(plaza_name)
    job_folder = _safe_folder(job_uuid)
    slot_folder = _safe_folder(slot)
    file_name = _safe_filename(original_file_name)
    return f"{S3_ROOT_PREFIX}/{plaza_folder}/{job_folder}/{slot_folder}/{file_name}"


def upload_bytes(
    *,
    body: bytes,
    plaza_name: str,
    job_uuid: str,
    slot: str,
    original_file_name: str,
    content_type: str | None = None,
) -> dict:
    bucket = bucket_name()
    region = _require_env("AWS_REGION")
    key = build_input_key(
        plaza_name=plaza_name,
        job_uuid=job_uuid,
        slot=slot,
        original_file_name=original_file_name,
    )
    extra: dict = {}
    if content_type:
        extra["ContentType"] = content_type
    client = s3_client()
    client.put_object(Bucket=bucket, Key=key, Body=body, **extra)
    return {
        "bucket": bucket,
        "s3_key": key,
        "file_url": object_url(bucket, region, key),
        "file_size_bytes": len(body),
    }


def _unique_sibling(path: Path) -> Path:
    stem = path.stem[:_MAX_LOCAL_STEM].rstrip(" ._") or "file"
    return path.with_name(f"{stem}_{uuid.uuid4().hex[:6]}{path.suffix}")


def _win_long_path(path: Path) -> str:
    r"""Prefix \\?\ so Windows can open paths near/over MAX_PATH."""
    resolved = str(path.resolve())
    if os.name == "nt" and not resolved.startswith("\\\\?\\"):
        if resolved.startswith("\\\\"):
            return "\\\\?\\UNC\\" + resolved.lstrip("\\")
        return "\\\\?\\" + resolved
    return resolved


def _download_bytes_to_file(s3_key: str, dest: Path) -> Path:
    """Stream S3 object into dest with an explicit open/close (no boto rename)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    client = s3_client()
    with open(_win_long_path(dest), "wb") as out_fh:
        client.download_fileobj(bucket_name(), s3_key, out_fh)
        out_fh.flush()
        try:
            os.fsync(out_fh.fileno())
        except OSError:
            pass
    return dest


def download_to_path(s3_key: str, local_path: Path) -> Path:
    """
    Download S3 object to local_path.

    Does not use boto3 download_file (its internal rename hits WinError 32).
    Uses a short .part name to avoid Windows MAX_PATH FileNotFoundError.
    """
    local_path = Path(local_path)
    # Enforce short final name as well.
    local_path = local_path.with_name(shorten_local_filename(local_path.name))
    local_path.parent.mkdir(parents=True, exist_ok=True)

    # Short temp name — do NOT embed the original filename (that blew past MAX_PATH).
    tmp_path = local_path.parent / f".dl_{uuid.uuid4().hex[:12]}.part"
    try:
        _download_bytes_to_file(s3_key, tmp_path)

        if not local_path.exists():
            for attempt in range(5):
                try:
                    os.replace(_win_long_path(tmp_path), _win_long_path(local_path))
                    return local_path
                except PermissionError:
                    time.sleep(0.3 * (attempt + 1))
                except OSError:
                    # os.replace may not accept \\?\ on all builds — try plain paths.
                    try:
                        os.replace(str(tmp_path), str(local_path))
                        return local_path
                    except PermissionError:
                        time.sleep(0.3 * (attempt + 1))

        alt = _unique_sibling(local_path)
        try:
            try:
                os.replace(_win_long_path(tmp_path), _win_long_path(alt))
            except OSError:
                os.replace(str(tmp_path), str(alt))
            return alt
        except PermissionError:
            alt2 = _unique_sibling(local_path)
            return _download_bytes_to_file(s3_key, alt2)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def delete_object(s3_key: str) -> None:
    client = s3_client()
    client.delete_object(Bucket=bucket_name(), Key=s3_key)


def delete_keys(keys: list[str]) -> None:
    if not keys:
        return
    client = s3_client()
    bucket = bucket_name()
    # delete_objects accepts up to 1000 keys
    for i in range(0, len(keys), 1000):
        chunk = keys[i : i + 1000]
        client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": k} for k in chunk], "Quiet": True},
        )
