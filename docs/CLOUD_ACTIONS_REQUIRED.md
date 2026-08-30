# Account-Bound Actions Still Required

These cannot be performed safely without the team's own AWS Academy/AWS and GCP project access. Everything else can be developed, tested and reviewed locally.

1. Create or nominate an AWS account/region and a GCP project with billing enabled; record their IDs in a non-committed `terraform.tfvars`.
2. Create a private Git remote and add every team member plus the teaching team. Do not publish the repository.
3. Build and push the API Lambda and Cloud Run worker container images to ECR/Artifact Registry.
4. Run Terraform using a remote encrypted state backend. Inspect the plan before applying it.
5. Set a globally unique `cognito_domain_prefix` and use the final API/static UI origin in `ui_callback_urls` and `ui_logout_urls`; run a second Terraform apply if the API Gateway URL was not known initially. Create at least one real test user and complete email verification. The production UI implements Cognito Hosted UI authorization-code + PKCE, so it does not accept the development `X-Demo-User` identity.
6. Configure Google/Outlook federation only after the required Cognito sign-in flow works.
7. Confirm the SNS subscription email. Capture the confirmation and a real watched-tag notification for the demo.
8. Supply the 12-digit `aws_account_id` during Terraform apply. Terraform then creates the AWS workload-identity pool/provider, restricts it to the dispatcher role, and grants the resulting short-lived identity only the Cloud Run invoker service account. Do not use shared service-account JSON keys.
9. Upload checksum-verified `models/mdv5a.pt` and `models/model.pt` to the private GCS replica bucket under the same `models/` paths used by `model-manifest.json`. The worker service account has only object-view access and restores absent image assets from this bucket. Run the supplied images through Cloud Run before claiming ML success.
10. Capture the final deployed API, Cognito, queue, Cloud Run, database and SNS screenshots plus Git contribution history for the report.
