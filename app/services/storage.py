"""Where generated files live.

Paths are built only from generated ids (job id, certificate id), never from names or
emails, so user input cannot influence a file path.
"""

import os
import re
import tempfile
import unicodedata
import zipfile
from collections.abc import Iterable
from pathlib import Path

from app.config import get_settings


def storage_root() -> Path:
    return get_settings().storage_dir.resolve()


def certificate_relpath(job_id: str, certificate_id: str) -> str:
    return f"{job_id}/{certificate_id}.pdf"


def resolve(relpath: str) -> Path:
    """Absolute path for a stored relative path, refusing anything outside the storage root."""
    root = storage_root()
    path = (root / relpath).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"path escapes storage directory: {relpath}")
    return path


def save_certificate(job_id: str, certificate_id: str, data: bytes) -> str:
    """Write a certificate PDF and return its path relative to the storage root.

    Written to a temporary name first and then renamed, so a crash never leaves a
    half-written PDF under the final name.
    """
    relpath = certificate_relpath(job_id, certificate_id)
    path = resolve(relpath)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".pdf.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return relpath


def delete_file(relpath: str) -> None:
    resolve(relpath).unlink(missing_ok=True)


def download_filename(recipient_name: str | None, certificate_number: str | None) -> str:
    """Filename shown to the user: an ASCII-safe version of the name plus the certificate number."""
    ascii_name = (
        unicodedata.normalize("NFKD", recipient_name or "").encode("ascii", "ignore").decode()
    )
    safe_name = re.sub(r"[^A-Za-z0-9]+", "-", ascii_name).strip("-")[:60].strip("-")
    parts = [part for part in (safe_name or "certificate", certificate_number) if part]
    return "-".join(parts) + ".pdf"


def build_zip(entries: Iterable[tuple[str, str]]) -> Path:
    """Write (stored relpath, name inside zip) pairs into a temporary zip file and return its path.

    The zip is built on disk rather than in memory, so a job with thousands of certificates
    does not need to fit in RAM. The caller deletes the file once it has been sent.
    """
    fd, name = tempfile.mkstemp(prefix="certificates-", suffix=".zip")
    os.close(fd)
    path = Path(name)
    try:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relpath, arcname in entries:
                archive.write(resolve(relpath), arcname=arcname)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path
