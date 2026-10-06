"""Equipment registration endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg2.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Equipment, get_db
from app.schemas import EquipmentCreate, EquipmentOut

router = APIRouter(prefix="/equipment", tags=["equipment"])


@router.post(
    "",
    response_model=EquipmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a piece of equipment",
)
def create_equipment(
    payload: EquipmentCreate, db: Session = Depends(get_db)
) -> EquipmentOut:
    equipment = Equipment(code=payload.code, name=payload.name)
    db.add(equipment)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if isinstance(exc.orig, UniqueViolation):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Equipment code already exists: {payload.code!r}",
            )
        raise
    db.refresh(equipment)
    return EquipmentOut.model_validate(equipment)


@router.get(
    "/{code}",
    response_model=EquipmentOut,
    summary="Get equipment by code",
)
def get_equipment(code: str, db: Session = Depends(get_db)) -> EquipmentOut:
    equipment = db.query(Equipment).filter(Equipment.code == code).one_or_none()
    if equipment is None:
        raise HTTPException(status_code=404, detail="Equipment not found")
    return EquipmentOut.model_validate(equipment)
