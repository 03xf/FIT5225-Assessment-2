# 15-Minute Demonstration Script

## 0:00-3:00 Architecture (all members visible)

1. State the two providers and their roles: AWS hosts Cognito, API Gateway, Lambda, S3, DynamoDB, SQS and SNS; Alibaba Cloud hosts the private Function Compute ML worker and OSS model artifacts.
2. Follow one upload through Cognito -> API/S3 -> SQS -> dispatcher Lambda -> Function Compute -> signed callback -> DynamoDB/SNS.
3. Explain the security boundary: Cognito JWT authorization, user ownership checks, private S3/OSS, least-privilege AWS IAM and scoped Alibaba RAM access.
4. Explain the model manifest/version switch and SHA-256 verification.

## 3:00-13:00 Application flow

1. Register, verify email, sign in and sign out as a clean Cognito user.
2. Upload `Bos_taurus_1.JPG`; show processing state, thumbnail and automatic tag.
3. Upload the same file again; show duplicate feedback and unchanged media count.
4. Upload a video; show one-frame-per-second processing evidence and aggregate tag counts.
5. Search one species, then submit a two-tag/minimum-count query that demonstrates AND rather than OR.
6. Click a thumbnail, then paste its URL into the thumbnail resolver.
7. Submit a temporary query file; show matches and verify it is not in the archive.
8. Select multiple media, bulk-add and bulk-remove a tag; delete a selected file and show object/index removal.
9. Subscribe to a tag, upload/tag matching media, and show the confirmed SNS email.

## 13:00-15:00 Q&A fallback

- Keep Function Compute logs, Alibaba OSS model objects, DynamoDB, S3 prefixes, the Terraform plan and Git commit graph open in separate tabs.
- If a cloud call fails, diagnose it honestly and use a pre-recorded successful run only as a backup.
- Every member should be ready to explain one module they personally implemented and make one small non-critical change live.
