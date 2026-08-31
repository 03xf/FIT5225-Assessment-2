# Pacific BioArchive Team Handoff

Updated: 2026-08-31

## Current state

The repository contains the application, infrastructure definitions, tests, reports and cloud evidence. A deployed demo is available at `https://7ijuyi2q17.execute-api.ap-southeast-2.amazonaws.com/`. The local adapter is for repeatable development tests; only the deployed Function Compute worker represents real ML inference.

## Repository

- GitHub: `https://github.com/03xf/FIT5225-Assessment-2`
- Main branch contains the latest application, team report and evidence screenshots.
- Do not commit credentials, `.env`, Terraform state/plan files, model weights or test media.

## Implemented locally

- Auth boundary: production code validates AWS Cognito ID tokens; development uses an isolated demo identity.
- Upload pipeline: SHA-256 deduplication, checksum-bound S3 uploads, SQS dispatch, owner-scoped DynamoDB data and HMAC worker callbacks.
- Worker: Function Compute-compatible image/video processing, thumbnails, one video frame per second, model manifest/versioning and SHA-256 checks.
- User workflows: tag/count AND search, species search, thumbnail resolution, temporary query-by-file, bulk tag edit, deletion and SNS subscriptions.

## Run Locally

Requirements: Windows PowerShell, Python 3.11+, and Git. From the repository root:

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`. Local mode uses SQLite and local object storage. It is suitable for UI/API testing, but it must not be described as cloud ML inference.

Run tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Run the release preflight without changing cloud resources:

```powershell
.\scripts\preflight.ps1
```

## Online Demo

1. Open `https://7ijuyi2q17.execute-api.ap-southeast-2.amazonaws.com/`.
2. Sign in through the Cognito Hosted UI. A verified account is required for upload and media access.
3. Upload an image or `video.mp4`, wait for `READY`, then test species/AND search, thumbnail access, tags and deletion.
4. For query-by-file, confirm the temporary result is returned and no archive item is created.
5. Use the screenshots and captions in `docs/evidence/README.md` when recording the demonstration.

## Cloud Deployment Changes

The deployed stack is account-specific. Do not redeploy it casually. If a fresh account is required, follow `docs/DEPLOYMENT_RUNBOOK.md` and `docs/CLOUD_ACTIONS_REQUIRED.md`, create an untracked `infra/terraform/terraform.tfvars`, and configure Cognito callback/logout URLs for the new API URL.

## Important boundaries

- Do not commit `terraform.tfvars`, `.env`, Terraform state, cloud credentials, model weights or test media.
- Keep S3, OSS and the Function Compute worker private. The browser receives only short-lived S3 URLs.
- The Function Compute worker needs the exact shared key and callback HMAC secret produced for the deployed stack.
- External provider login is optional; do not prioritize it over the required Cognito flow.

## Troubleshooting

- `401 Unauthorized` on `/api/media`: the browser session is signed out or the Cognito token has expired; sign in again.
- Upload remains pending: check the SQS/dispatcher and Function Compute logs; do not repeatedly upload the same file.
- Thumbnail unavailable: verify the record is `READY` and access it from the owning account.
- Local startup fails: recreate `.venv` and reinstall `requirements.txt`; do not copy cloud `.env` values into the local adapter.

## Handoff Checklist

- [ ] Clone the repository and switch to `main`.
- [ ] Run the local test suite successfully.
- [ ] Open the online demo and verify Cognito sign-in.
- [ ] Read `docs/DEMO_SCRIPT.md` and `docs/PRE_SUBMISSION_CHECKLIST.md`.
- [ ] Review the team report and individual reports under `docs/`.
- [ ] Keep all secrets and account-specific configuration untracked.
