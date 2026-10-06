"""Measurement record endpoints (append-only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import Certificate, Equipment, Measurement, get_db
from app.helpers import _VALIDITY_SELECT, row_to_measurement_out
from app.schemas import MeasurementCreate, MeasurementOut

router = APIRouter(prefix="/measurements", tags=["measurements"])


@router.post(
    "",
    response_model=MeasurementOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a measurement (immutable once written)",
)
def create_measurement(
    payload: MeasurementCreate, db: Session = Depends(get_db)
) -> MeasurementOut:
    equipment = (
        db.query(Equipment).filter(Equipment.code == payload.equipment_code).one_or_none()
    )
    if equipment is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown equipment code: {payload.equipment_code!r}",
        )

    # Lock the certificate row so a concurrent revoke and this write cannot
    # both succeed: whichever commits first wins, the other re-reads it.
    certificate = (
        db.query(Certificate)
        .filter(Certificate.cert_no == payload.cert_no)
        .with_for_update()
        .one_or_none()
    )
    if certificate is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown certificate number: {payload.cert_no!r}",
        )
    if certificate.equipment_id != equipment.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Certificate {payload.cert_no!r} does not belong to equipment "
                f"{payload.equipment_code!r}"
            ),
        )
    if certificate.revoked:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Certificate has been revoked; measurement not accepted",
        )
    # Half-open window: valid_from <= measured_at < valid_to.
    if not (certificate.valid_from <= payload.measured_at < certificate.valid_to):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Certificate validity window "
                f"[{certificate.valid_from.isoformat()}, "
                f"{certificate.valid_to.isoformat()}) does not cover "
                f"measured_at {payload.measured_at.isoformat()}"
            ),
        )

    record = Measurement(
        equipment_id=equipment.id,
        cert_no=payload.cert_no,
        measured_at=payload.measured_at,
        value=payload.value,
        note=payload.note,
    )
    db.add(record)
    db.commit()

    row = db.execute(
        text(_VALIDITY_SELECT + " WHERE m.id = :id"),
        {"id": record.id},
    ).one()
    return row_to_measurement_out(row)


@router.get(
    "",
    response_model=list[MeasurementOut],
    summary="List measurements with their *current* validity and reason",
)
def list_measurements(
    equipment_code: str | None = None,
    is_valid: bool | None = Query(default=None, description="Filter by current validity"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[MeasurementOut]:
    sql = _VALIDITY_SELECT + " WHERE 1=1"
    params: dict = {}
    if equipment_code is not None:
        sql += " AND e.code = :equipment_code"
        params["equipment_code"] = equipment_code
    if is_valid is not None:
        if is_valid:
            sql += (
                " AND c.revoked = FALSE"
                " AND c.valid_from <= m.measured_at"
                " AND m.measured_at < c.valid_to"
            )
        else:
            sql += (
                " AND (c.revoked = TRUE"
                " OR c.valid_from > m.measured_at"
                " OR m.measured_at >= c.valid_to)"
            )
    sql += " ORDER BY m.id DESC LIMIT :limit OFFSET :offset"
    params.update(limit=limit, offset=offset)
    rows = db.execute(text(sql), params).all()
    return [row_to_measurement_out(r) for r in rows]


@router.get(
    "/{measurement_id}",
    response_model=MeasurementOut,
    summary="Get one measurement with its current validity and reason",
)
def get_measurement(
    measurement_id: int, db: Session = Depends(get_db)
) -> MeasurementOut:
    row = db.execute(
        text(_VALIDITY_SELECT + " WHERE m.id = :id"),
        {"id": measurement_id},
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Measurement not found")
    return row_to_measurement_out(row)
