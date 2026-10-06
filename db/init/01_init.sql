-- Lab Equipment Calibration Traceability - schema initialization
-- Runs automatically on first container start (docker-entrypoint-initdb.d).

CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE IF NOT EXISTS equipment (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code         TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Calibration certificates.
-- Validity window: [valid_from, valid_to)  (left-closed, right-open).
CREATE TABLE IF NOT EXISTS certificates (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cert_no      TEXT NOT NULL UNIQUE,
    equipment_id BIGINT NOT NULL REFERENCES equipment(id),
    valid_from   TIMESTAMPTZ NOT NULL,
    valid_to     TIMESTAMPTZ NOT NULL,
    revoked      BOOLEAN NOT NULL DEFAULT FALSE,
    revoked_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT cert_window_left_closed_right_open CHECK (valid_from < valid_to),
    -- Validity windows of certificates for the SAME equipment must not overlap.
    -- Adjacent windows are allowed: '[2026-01-01,2026-06-01)' and
    -- '[2026-06-01,2027-01-01)' do not overlap because the range is half-open.
    CONSTRAINT cert_no_overlap EXCLUDE USING gist (
        equipment_id WITH =,
        tstzrange(valid_from, valid_to, '[)') WITH &&
    )
);

-- Idempotent certificate registration.
CREATE TABLE IF NOT EXISTS idempotency_records (
    idempotency_key   TEXT PRIMARY KEY,
    request_hash      TEXT NOT NULL,
    response_status   INT NOT NULL,
    response_body     JSONB NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Measurement records are append-only. A trigger blocks UPDATE / DELETE.
CREATE TABLE IF NOT EXISTS measurements (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    equipment_id    BIGINT NOT NULL REFERENCES equipment(id),
    cert_no         TEXT NOT NULL REFERENCES certificates(cert_no),
    measured_at     TIMESTAMPTZ NOT NULL,
    value           DOUBLE PRECISION,
    note            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_measurements_equipment ON measurements(equipment_id);
CREATE INDEX IF NOT EXISTS idx_certificates_equipment ON certificates(equipment_id);

CREATE OR REPLACE FUNCTION measurements_immutable() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'measurements are append-only; % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_measurements_immutable ON measurements;
CREATE TRIGGER trg_measurements_immutable
    BEFORE UPDATE OR DELETE ON measurements
    FOR EACH ROW EXECUTE FUNCTION measurements_immutable();
