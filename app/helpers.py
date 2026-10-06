"""Serialization and current-validity helpers shared by routers."""
from __future__ import annotations

from app.db import Certificate, Equipment
from app.schemas import CertificateOut, MeasurementOut, ValidityInfo

# A record is valid iff its certificate currently covers the measurement
# instant and has not been revoked. The window is half-open [from, to).
_VALIDITY_SELECT = """
    SELECT m.id,
           e.code              AS equipment_code,
           m.cert_no           AS cert_no,
           m.measured_at       AS measured_at,
           m.value             AS value,
           m.note              AS note,
           m.created_at        AS created_at,
           c.revoked           AS revoked,
           (c.valid_from <= m.measured_at
            AND m.measured_at < c.valid_to) AS covered
      FROM measurements m
      JOIN equipment e    ON e.id = m.equipment_id
      JOIN certificates c ON c.cert_no = m.cert_no
"""


def validity_for(revoked: bool, covered: bool) -> ValidityInfo:
    if revoked:
        return ValidityInfo(
            is_valid=False,
            reason_code="CERTIFICATE_REVOKED",
            reason="The certificate recorded for this measurement has been revoked.",
        )
    if not covered:
        return ValidityInfo(
            is_valid=False,
            reason_code="CERTIFICATE_NOT_COVERING",
            reason="The certificate validity window does not cover the measurement time.",
        )
    return ValidityInfo(
        is_valid=True,
        reason_code="VALID",
        reason="Certificate is not revoked and covers the measurement time.",
    )


def row_to_measurement_out(row) -> MeasurementOut:
    return MeasurementOut(
        id=row.id,
        equipment_code=row.equipment_code,
        cert_no=row.cert_no,
        measured_at=row.measured_at,
        value=row.value,
        note=row.note,
        created_at=row.created_at,
        validity=validity_for(row.revoked, row.covered),
    )


def serialize_certificate(
    cert: Certificate, equipment: Equipment
) -> CertificateOut:
    return CertificateOut(
        cert_no=cert.cert_no,
        equipment_code=equipment.code,
        valid_from=cert.valid_from,
        valid_to=cert.valid_to,
        revoked=cert.revoked,
        revoked_at=cert.revoked_at,
        created_at=cert.created_at,
    )
