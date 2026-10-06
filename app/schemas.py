"""Pydantic request/response models."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, AwareDatetime, model_validator


class EquipmentCreate(BaseModel):
    code: str = Field(..., min_length=1, examples=["SCALE-001"])
    name: str = Field(..., min_length=1, examples=["Analytical balance #1"])


class EquipmentOut(BaseModel):
    id: int
    code: str
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CertificateCreate(BaseModel):
    cert_no: str = Field(..., min_length=1, examples=["CNAS-CERT-2026-0001"])
    equipment_code: str = Field(..., min_length=1)
    # AwareDatetime rejects naive timestamps; a UTC offset / time zone is mandatory.
    valid_from: AwareDatetime
    valid_to: AwareDatetime

    @model_validator(mode="after")
    def _check_window(self):
        if self.valid_from >= self.valid_to:
            raise ValueError(
                "valid_from must be strictly earlier than valid_to "
                "(window is half-open [valid_from, valid_to))"
            )
        return self


class CertificateOut(BaseModel):
    cert_no: str
    equipment_code: str
    valid_from: datetime
    valid_to: datetime
    revoked: bool
    revoked_at: datetime | None = None
    created_at: datetime


class MeasurementCreate(BaseModel):
    equipment_code: str = Field(..., min_length=1)
    cert_no: str = Field(..., min_length=1)
    measured_at: AwareDatetime
    value: float | None = None
    note: str | None = None


class ValidityInfo(BaseModel):
    is_valid: bool
    reason_code: str = Field(
        ..., description="VALID / CERTIFICATE_REVOKED / CERTIFICATE_NOT_COVERING"
    )
    reason: str


class MeasurementOut(BaseModel):
    id: int
    equipment_code: str
    cert_no: str
    measured_at: datetime
    value: float | None
    note: str | None
    created_at: datetime
    validity: ValidityInfo
