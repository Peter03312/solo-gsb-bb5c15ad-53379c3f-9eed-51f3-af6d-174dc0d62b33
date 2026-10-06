"""Calibration certificate endpoints.

Registration is idempotent via the ``Idempotency-Key`` request header:
a retry with the same key and identical payload replays the original result;
the same key with a different payload returns 409.
"""
from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from psycopg2.errors import ExclusionViolation, UniqueViolation
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Certificate, Equipment, IdempotencyRecord, get_db
from app.helpers import serialize_certificate
from app.schemas import CertificateCreate, CertificateOut

router = APIRouter(prefix="/certificates", tags=["certificates"])


def _payload_hash(payload: CertificateCreate) -> str:
    canonical = json.dumps(
        payload.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _replay_or_conflict(
    db: Session, key: str, request_hash: str
) -> IdempotencyRecord:
    existing = db.get(IdempotencyRecord, key)
    if existing is None:  # pragma: no cover - lost a race we should have won
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Idempotency record vanished; please retry",
        )
    if existing.request_hash != request_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Idempotency-Key {key!r} was already used with a different "
                "request payload"
            ),
        )
    return existing


@router.post(
    "",
    response_model=CertificateOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a calibration certificate (idempotent)",
)
def register_certificate(
    payload: CertificateCreate,
    response: Response,
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=1, description="Client-generated unique key"
    ),
    db: Session = Depends(get_db),
) -> dict:
    request_hash = _payload_hash(payload)

    # Fast path: retry of a completed request -> replay original result.
    existing = db.get(IdempotencyRecord, idempotency_key)
    if existing is not None:
        record = _replay_or_conflict(db, idempotency_key, request_hash)
        response.status_code = record.response_status
        return record.response_body

    equipment = (
        db.query(Equipment)
        .filter(Equipment.code == payload.equipment_code)
        .one_or_none()
    )
    if equipment is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown equipment code: {payload.equipment_code!r}",
        )

    # Insert the idempotency placeholder first: a concurrent request with the
    # same key blocks here on the primary key, so registrations are serialized.
    placeholder = IdempotencyRecord(
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        response_status=0,
        response_body={},
    )
    db.add(placeholder)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        record = _replay_or_conflict(db, idempotency_key, request_hash)
        response.status_code = record.response_status
        return record.response_body

    certificate = Certificate(
        cert_no=payload.cert_no,
        equipment_id=equipment.id,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
    )
    db.add(certificate)
    try:
        db.flush()
    except IntegrityError as exc:
        # Rollback also removes the placeholder, so the key can be retried
        # after the client fixes the conflict.
        db.rollback()
        if isinstance(exc.orig, UniqueViolation):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Certificate number already registered: {payload.cert_no!r}",
            )
        if isinstance(exc.orig, ExclusionViolation):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Validity window overlaps another certificate for equipment "
                    f"{payload.equipment_code!r}"
                ),
            )
        raise

    result = serialize_certificate(certificate, equipment)
    body = result.model_dump(mode="json")
    placeholder.response_status = status.HTTP_201_CREATED
    placeholder.response_body = body
    db.commit()
    response.status_code = status.HTTP_201_CREATED
    return body


@router.get(
    "/{cert_no}",
    response_model=CertificateOut,
    summary="Get a certificate by number",
)
def get_certificate(cert_no: str, db: Session = Depends(get_db)) -> CertificateOut:
    cert = (
        db.query(Certificate).filter(Certificate.cert_no == cert_no).one_or_none()
    )
    if cert is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    equipment = db.get(Equipment, cert.equipment_id)
    return serialize_certificate(cert, equipment)


@router.get(
    "",
    response_model=list[CertificateOut],
    summary="List certificates (optionally filtered by equipment code)",
)
def list_certificates(
    equipment_code: str | None = None, db: Session = Depends(get_db)
) -> list[CertificateOut]:
    query = db.query(Certificate, Equipment).join(
        Equipment, Equipment.id == Certificate.equipment_id
    )
    if equipment_code is not None:
        query = query.filter(Equipment.code == equipment_code)
    return [serialize_certificate(c, e) for c, e in query.order_by(Certificate.id).all()]


@router.post(
    "/{cert_no}/revoke",
    response_model=CertificateOut,
    summary="Revoke a certificate (does not delete historical measurements)",
)
def revoke_certificate(
    cert_no: str, db: Session = Depends(get_db)
) -> CertificateOut:
    # Row lock serializes revocation against measurement writes, which take the
    # same FOR UPDATE lock before validating coverage.
    certificate = (
        db.query(Certificate)
        .filter(Certificate.cert_no == cert_no)
        .with_for_update()
        .one_or_none()
    )
    if certificate is None:
        raise HTTPException(status_code=404, detail="Certificate not found")

    if not certificate.revoked:
        certificate.revoked = True
        certificate.revoked_at = func.now()
        db.commit()
        db.refresh(certificate)

    equipment = db.get(Equipment, certificate.equipment_id)
    return serialize_certificate(certificate, equipment)
