# Pacific BioArchive

Pacific BioArchive is a multi-cloud, serverless wildlife-media archive for FIT5225 Assignment 2. It provides authenticated upload, SHA-256 deduplication, thumbnail generation, tag search with logical AND/minimum counts, temporary file queries, bulk tag editing, deletion, and tag subscription events.

## What runs now

The local FastAPI application is a fully testable integration adapter. It uses SQLite and local object storage, and labels the supplied fixture images only in `development` mode so the UI workflow can be tested without pretending that filename inference is production ML. The private `worker/` service is the production model boundary: it runs the supplied MegaDetector and SpeciesNet assets in Alibaba Function Compute, verifies their checksums, extracts one video frame per second, and emits signed callback results.

## Local run

```powershell
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`. The current development mode is clearly marked in the UI. Restore the supplied 30 fixture images under `tests/fixtures/test_images/` and the supplied `models/mdv5a.pt` and `models/model.pt` files before demonstrating the workflow or running the full test suite. Run verification with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

For a non-destructive release check covering tests, Terraform, Git evidence and
the availability of cloud deployment tools, run:

```powershell
.\scripts\preflight.ps1
```

## Security model

- Production API requests require an AWS Cognito JWT; issuer, audience and JWKS signature are validated.
- Each media record is owned by Cognito `sub`. Object retrieval, tags, lookup and deletion re-check ownership server-side.
- Browser uploads calculate SHA-256 locally; the signed S3 PUT binds that checksum and the completion endpoint verifies S3's checksum before queuing work. DynamoDB's per-user checksum claim rejects concurrent duplicates.
- Alibaba Function Compute is private and should be invoked by the AWS dispatcher, never from the browser.
- Model objects are checksum-pinned by `models/model-manifest.json`; production Worker images contain only that manifest and labels, then restore weights from private Alibaba OSS. A new version is activated by replacing the manifest, not changing code.

## Cloud deployment

The intended cloud split and the remaining account-bound actions are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DEPLOYMENT_RUNBOOK.md](docs/DEPLOYMENT_RUNBOOK.md) and [docs/CLOUD_ACTIONS_REQUIRED.md](docs/CLOUD_ACTIONS_REQUIRED.md). The Terraform root is `infra/terraform/`. No credentials, Terraform state, model weights, test media, or `.env` files are tracked in Git.

## Academic integrity

The reports must acknowledge selective GenAI use. Every team member must understand, be able to modify, and accurately explain the submitted code and architecture. Do not claim demo-mode filename labels as ML inference; deploy and demonstrate the Alibaba Function Compute worker for the actual ML claim.
