# Deployment Contract

This file defines the non-secret inputs the deployed API and worker require.

| Component | Required configuration | Source |
|---|---|---|
| API Lambda | `PACIFICBIO_ENV=production`, Cognito pool/client IDs, DynamoDB table name, S3 bucket, Cloud Run URL, callback-secret reference | Terraform outputs and Secrets Manager |
| API Gateway | JWT issuer and audience from Cognito; every `/api/*` route uses the JWT authorizer except health | Terraform |
| S3 | Private `raw/`, `thumbnails/`, `temporary-query/` prefixes; browser source PUT is a short-lived presigned URL that binds SHA-256, while the trusted one-time Cloud Run thumbnail PUT is separately scoped. Temporary query objects are deleted by the API and protected by a one-day lifecycle fallback. | Terraform |
| Dispatcher Lambda | SQS records emitted only after the API has verified the S3 checksum, short-lived signed S3 GET URL, Cloud Run IAM ID token, HMAC callback nonce | AWS Lambda role + GCP WIF |
| Cloud Run worker | Read-only model artifact, callback HMAC secret, private invoker IAM policy | GCP Secret Manager/IAM |
| SNS | The watched-tag endpoint creates a per-user email subscription with a species filter; the user must confirm the SNS email before alerts are delivered | Cognito verified email + SNS |

The local SQLite/file adapter is intentionally not used in production. The production path now selects a DynamoDB repository and S3 adapter; its per-user checksum claim uses a DynamoDB transaction so concurrent uploads of the same file deduplicate safely. Account-specific deployment remains required for Terraform apply, Google workload identity federation and email subscription confirmation.
