# Local Build Validation Record

This is a reproducible local verification record, not cloud-deployment
evidence. Re-run the commands and replace/add cloud evidence before submission.

## Verified locally on 2026-08-27

| Artifact | Command / invocation | Result |
|---|---|---|
| API Lambda container | `docker build -f Dockerfile.api -t pacificbio-api:local .` followed by a Lambda Runtime API-v2 `GET /api/health` event | Built and returned HTTP 200 with `environment: production`. This also exposed and led to a fix for the `PACIFICBIO_ENV` alias. |
| Dispatcher Lambda container | `docker build -f Dockerfile.dispatcher -t pacificbio-dispatcher:local .` followed by `{"Records":[]}` through Lambda Runtime | Built and returned `{"processed":0}`. |
| Worker container | `docker build -f Dockerfile.worker -t pacificbio-worker:local .` | Not yet conclusive locally: Docker Hub was unreachable; the public ECR Python mirror was reachable, but Debian package download stalled before ML dependencies installed. Do not claim Worker runtime/model success from this record. |
| Local code/IaC | `./scripts/preflight.ps1` | Historical result from 2026-08-27: Python suite passed 16 tests and `terraform validate` succeeded. The current checkout is missing supplied model and fixture assets, so this result cannot be reproduced until those assets are restored. |

## Required next evidence

Build the Worker in a network-enabled environment, invoke `/healthz`, upload the
checksum-verified Alibaba OSS model objects, then run `scripts/run_model_smoke.py` or a
Function Compute request against a supplied image. Retain the output and Function Compute logs
with the active model version.
