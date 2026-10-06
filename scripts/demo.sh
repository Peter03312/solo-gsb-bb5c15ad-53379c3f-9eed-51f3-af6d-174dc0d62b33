#!/usr/bin/env bash
# End-to-end demonstration of the calibration traceability API.
# Usage: BASE=http://localhost:8000 scripts/demo.sh
set -euo pipefail

BASE="${BASE:-http://localhost:8000}"
KEY1="demo-key-0001"
KEY2="demo-key-0002"

j() { python3 -m json.tool 2>/dev/null || cat; }

echo "== 1. Register equipment =="
curl -sS -X POST "$BASE/equipment" \
  -H 'Content-Type: application/json' \
  -d '{"code":"SCALE-001","name":"Analytical balance #1"}' | j

echo; echo "== 2. Register certificate (H1/2026, half-open [2026-01-01, 2026-07-01)) =="
curl -sS -X POST "$BASE/certificates" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $KEY1" \
  -d '{"cert_no":"CNAS-2026-0001","equipment_code":"SCALE-001",
       "valid_from":"2026-01-01T00:00:00+00:00",
       "valid_to":"2026-07-01T00:00:00+00:00"}' | j

echo; echo "== 3. Retry with the same key and payload -> original result replayed (201) =="
curl -sS -o /tmp/replay.json -w 'HTTP %{http_code}\n' -X POST "$BASE/certificates" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $KEY1" \
  -d '{"cert_no":"CNAS-2026-0001","equipment_code":"SCALE-001",
       "valid_from":"2026-01-01T00:00:00+00:00",
       "valid_to":"2026-07-01T00:00:00+00:00"}'
cat /tmp/replay.json | j

echo; echo "== 4. Same key, different payload -> 409 conflict =="
curl -sS -o /dev/null -w 'HTTP %{http_code}\n' -X POST "$BASE/certificates" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $KEY1" \
  -d '{"cert_no":"CNAS-2026-9999","equipment_code":"SCALE-001",
       "valid_from":"2027-01-01T00:00:00+00:00",
       "valid_to":"2027-07-01T00:00:00+00:00"}'

echo; echo "== 5. Overlapping window (different key) -> 409 from database exclusion =="
curl -sS -w '\nHTTP %{http_code}\n' -X POST "$BASE/certificates" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $KEY2" \
  -d '{"cert_no":"CNAS-2026-0002","equipment_code":"SCALE-001",
       "valid_from":"2026-06-01T00:00:00+00:00",
       "valid_to":"2026-12-01T00:00:00+00:00"}'

echo; echo "== 6. Adjacent window starting exactly at 2026-07-01 -> accepted =="
curl -sS -X POST "$BASE/certificates" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: demo-key-0003" \
  -d '{"cert_no":"CNAS-2026-0003","equipment_code":"SCALE-001",
       "valid_from":"2026-07-01T00:00:00+00:00",
       "valid_to":"2027-01-01T00:00:00+00:00"}' | j

echo; echo "== 7. Measurement inside the window -> accepted, VALID =="
curl -sS -X POST "$BASE/measurements" \
  -H 'Content-Type: application/json' \
  -d '{"equipment_code":"SCALE-001","cert_no":"CNAS-2026-0001",
       "measured_at":"2026-06-30T23:59:59+00:00","value":1.2345,"note":"sample A"}' | j

echo; echo "== 8. Measurement exactly at the right boundary 2026-07-01T00:00 -> rejected =="
curl -sS -w '\nHTTP %{http_code}\n' -X POST "$BASE/measurements" \
  -H 'Content-Type: application/json' \
  -d '{"equipment_code":"SCALE-001","cert_no":"CNAS-2026-0001",
       "measured_at":"2026-07-01T00:00:00+00:00","value":1.0}'

echo; echo "== 9. Revoke the certificate; historical measurement remains =="
curl -sS -X POST "$BASE/certificates/CNAS-2026-0001/revoke" | j

echo; echo "== 10. Query the measurement: still present, now INVALID / CERTIFICATE_REVOKED =="
curl -sS "$BASE/measurements?equipment_code=SCALE-001" | j

echo; echo "== 11. New measurement with revoked certificate -> rejected =="
curl -sS -o /dev/null -w 'HTTP %{http_code}\n' -X POST "$BASE/measurements" \
  -H 'Content-Type: application/json' \
  -d '{"equipment_code":"SCALE-001","cert_no":"CNAS-2026-0001",
       "measured_at":"2026-03-01T00:00:00+00:00","value":2.0}'
