from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.services import jobs as job_service

router = APIRouter(prefix="/api/certificates", tags=["certificates"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get(
    "/{certificate_id}/download",
    response_class=FileResponse,
    responses={200: {"content": {"application/pdf": {}}, "description": "The certificate PDF"}},
)
def download_certificate(certificate_id: str, session: SessionDep) -> FileResponse:
    """Download one generated certificate as a PDF."""
    path, filename = job_service.certificate_file(session, certificate_id)
    return FileResponse(path, media_type="application/pdf", filename=filename)
