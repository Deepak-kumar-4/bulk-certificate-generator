"""Where generated files live.

Paths are built only from generated ids (job id, certificate id), never from names or
emails, so user input cannot influence a file path.
"""

import os
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
