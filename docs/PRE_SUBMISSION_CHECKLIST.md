# Submission Readiness Checklist

Use this only with evidence from the team's own deployment. A checked box is a claim you can demonstrate live, not merely a feature found in source code.

## Before cloud apply

- [ ] Put the AWS account ID, Alibaba Cloud region/bucket, unique Cognito domain prefix, image URIs, Function Compute endpoint and final UI origin in an untracked `terraform.tfvars`.
- [ ] Use an encrypted remote Terraform state backend and inspect `terraform plan` with all team members.
- [ ] Confirm AWS permits the selected region/services and Alibaba Cloud billing, OSS and Function Compute are enabled.
- [ ] Build and scan API, dispatcher and worker images; push API/dispatcher images to private ECR and deploy the worker image to Function Compute.
- [ ] Upload the supplied model files only to protected Alibaba OSS, and verify the manifest hashes before deployment.

## Required live evidence

- [ ] Register a new email/password user in Cognito Hosted UI, verify email, sign in, sign out, and show anonymous `/api/*` rejection.
- [ ] Upload an image; show browser SHA-256, short-lived S3 upload, DynamoDB record, compressed aspect-preserving thumbnail, Function Compute log and model version.
- [ ] Upload the identical image again and show it returns the first media record without a second object or metadata item.
- [ ] Upload a video; show frame timestamps proving `fps=1`, a generated thumbnail and aggregate tag counts.
- [ ] Search with two `species:minimum` terms and show logical AND; then search a single species.
- [ ] Resolve a thumbnail URL to the full media URL while signed in, and show a different Cognito user cannot retrieve it.
- [ ] Use query-by-file and show it returns matches but no new media/table item; inspect the temporary prefix after completion.
- [ ] Select multiple records, add tags with operation `1`, remove them with operation `0`, and delete selected media. Show S3 and DynamoDB before/after.
- [ ] Subscribe to a tag, confirm the SNS email, upload/tag matching media and show the received notification.
- [ ] Show the private Function Compute access boundary, scoped Alibaba RAM/OSS policy, SQS/DLQ and the absence of cloud credentials in source control.

## Assessment artifacts

- [ ] Prepare a 3-minute architecture overview using official AWS/Alibaba Cloud icons, then rehearse the 15-minute functional demo with every member speaking.
- [ ] Replace all report placeholders, keep team report <=1000 words and each individual report <=500 words.
- [ ] Include the required selective-GenAI acknowledgement in both reports, with only truthful usage.
- [ ] Make the repository private, invite the teaching staff, and confirm every member's commits/contribution table are visible.
- [ ] Preserve screenshots, CloudWatch/Function Compute logs, commands, model version/hash and test output in the evidence folder before submission.
- [ ] Run `./scripts/preflight.ps1` immediately before the final recording; use `-RunModelSmoke` once Worker dependencies are available.
- [ ] Build the three local containers and invoke the API/Dispatcher Lambda runtime smoke paths before pushing immutable image digests.
