# Rubric Traceability Matrix

This is a working evidence checklist, not a claim that cloud deployment has happened. Replace each pending item with real screenshots, logs and URLs before submission.

| Rubric criterion | Implementation location | Evidence to capture |
|---|---|---|
| 1.1 Cognito sign-up/sign-in/sign-out | Terraform Cognito pool/client; production JWT verifier | Hosted UI registration, verification email, sign-in and sign-out screenshots |
| 1.2 Access control | API Gateway JWT authorizer; `app/services/auth.py` | Anonymous API returns 401; authenticated request succeeds |
| 1.3 Fine-grained IAM | Terraform Lambda policy + private buckets | IAM/RAM policy screenshots and denied cross-user request |
| 2.1.1 Upload/dedup | `app/services/media.py`, `S3Storage`, `DynamoRepository` | Same-file second upload; checksum-bound cloud S3 upload and DynamoDB claim |
| 2.1.2 Thumbnail/video | `create_thumbnail`; worker `video_frames` uses `fps=1` | Original vs compressed thumbnail; ffprobe/frame timestamp evidence |
| 2.1.3 ML/DB | `worker/main.py`; model manifest checksums | Function Compute logs, model version, DynamoDB tag item |
| 2.2.1 Tags/species AND | `Database.search_tags`; tests | Two-tag/minimum-count query showing only the intersection |
| 2.2.2 Thumbnail URL | `/api/resolve-thumbnail`; tests | Pasted thumbnail URL returning full media URL |
| 2.2.3 Query by file | `/api/search/by-file`; tests | Query result plus proof temporary prefix is empty/expired |
| 2.3.1 Bulk tags | `/api/media/tags`; UI | Multi-select add and remove of tags |
| 2.3.2 Delete | `MediaService.delete`; UI | Before/after S3/DynamoDB state |
| 2.3.3 Notifications | subscriptions table / SNS deployment contract | Confirmed SNS email after watched-tag upload or edit |
| 3.1-3.3 UI | `app/static/` | Login, upload feedback, result cards and bulk controls screenshots |
| 3.4 External account | Cognito federation setup | Optional: provider config and a successful federated login |
| 4.1 Demo | `docs/DEMO_SCRIPT.md` | Screen recording and each member's role |
| 4.2 Reports | report templates | Private Git log, official-icon architecture figure and contribution table |

## Current automated evidence

The project contains local tests for upload, checksum deduplication, thumbnail retrieval, logical-AND tag search, species search, temporary query files, bulk tag modification, deletion, cross-user isolation, callback HMAC, subscription idempotency, processing claims, production configuration, supplied-asset integrity and cloud-adapter request construction. Re-run the suite in the project virtual environment before claiming a current result. Local tests and source-level checks are not cloud-deployment evidence.
