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
from typing import BinaryIO

try:
    from boto3.s3.transfer import TransferConfig
except ImportError:  # pragma: no cover
    TransferConfig = None  # type: ignore[misc, assignment]

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


def job_input_key_prefix(*, plaza_name: str, job_uuid: str) -> str:
    """Prefix for all input objects belonging to one job (used to validate completes)."""
    plaza_folder = _safe_folder(plaza_name)
    job_folder = _safe_folder(job_uuid)
    return f"{S3_ROOT_PREFIX}/{plaza_folder}/{job_folder}/"


def presign_put_upload(
    *,
    plaza_name: str,
    job_uuid: str,
    slot: str,
    original_file_name: str,
    content_type: str | None = None,
    expires_in: int = 7200,
) -> dict:
    """
    Create a browser-direct PUT URL for an exception-job input object.
    Client must send the same Content-Type header that was signed (if any).
    """
    bucket = bucket_name()
    region = _require_env("AWS_REGION")
    key = build_input_key(
        plaza_name=plaza_name,
        job_uuid=job_uuid,
        slot=slot,
        original_file_name=original_file_name,
    )
    params: dict = {"Bucket": bucket, "Key": key}
    ctype = str(content_type or "").strip()
    if ctype:
        params["ContentType"] = ctype

    client = s3_client()
    upload_url = client.generate_presigned_url(
        "put_object",
        Params=params,
        ExpiresIn=max(60, int(expires_in)),
        HttpMethod="PUT",
    )
    return {
        "bucket": bucket,
        "s3_key": key,
        "file_url": object_url(bucket, region, key),
        "upload_url": upload_url,
        "content_type": ctype or None,
        "expires_in": max(60, int(expires_in)),
    }


def head_object_size(s3_key: str) -> int | None:
    """Return object size in bytes, or None if missing."""
    client = s3_client()
    try:
        meta = client.head_object(Bucket=bucket_name(), Key=s3_key)
    except Exception:  # noqa: BLE001
        return None
    size = meta.get("ContentLength")
    return int(size) if size is not None else None


class _CountingReader:
    """Wrap a file-like object and track total bytes read for S3 uploads."""

    def __init__(self, raw: BinaryIO) -> None:
        self._raw = raw
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._raw.read(size)
        if chunk:
            self.bytes_read += len(chunk)
        return chunk

    def __getattr__(self, name: str):
        return getattr(self._raw, name)


def _multipart_transfer_config() -> TransferConfig | None:
    if TransferConfig is None:
        return None
    chunk = 8 * 1024 * 1024
    return TransferConfig(
        multipart_threshold=chunk,
        multipart_chunksize=chunk,
        max_concurrency=4,
        use_threads=True,
    )


def upload_stream(
    *,
    fileobj: BinaryIO,
    plaza_name: str,
    job_uuid: str,
    slot: str,
    original_file_name: str,
    content_type: str | None = None,
    content_length: int | None = None,
) -> dict:
    """Stream upload to S3 (multipart for large files). Does not load whole file in RAM."""
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

    if hasattr(fileobj, "seek"):
        fileobj.seek(0)

    counter = _CountingReader(fileobj)
    client = s3_client()
    transfer_cfg = _multipart_transfer_config()
    if transfer_cfg is not None:
        client.upload_fileobj(
            counter,
            bucket,
            key,
            ExtraArgs=extra or None,
            Config=transfer_cfg,
        )
    else:
        client.upload_fileobj(counter, bucket, key, ExtraArgs=extra or None)

    size = counter.bytes_read
    if size <= 0 and content_length is not None and content_length > 0:
        size = int(content_length)

    return {
        "bucket": bucket,
        "s3_key": key,
        "file_url": object_url(bucket, region, key),
        "file_size_bytes": size,
    }


def upload_bytes(
    *,
    body: bytes,
    plaza_name: str,
    job_uuid: str,
    slot: str,
    original_file_name: str,
    content_type: str | None = None,
) -> dict:
    import io

    return upload_stream(
        fileobj=io.BytesIO(body),
        plaza_name=plaza_name,
        job_uuid=job_uuid,
        slot=slot,
        original_file_name=original_file_name,
        content_type=content_type,
        content_length=len(body),
    )


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
