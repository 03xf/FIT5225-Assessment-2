# Two-Phase Deployment Runbook

This runbook intentionally separates infrastructure bootstrap from application
release. Use a team-owned AWS account and GCP project; do not put credentials,
model weights or Terraform state in Git.

## 1. Bootstrap infrastructure

1. Copy `infra/terraform/terraform.tfvars.example` to an untracked
   `terraform.tfvars` and set the GCP project ID, AWS account ID and unique
   Cognito domain prefix.
2. Configure an encrypted remote Terraform backend before the first apply.
3. Run `terraform init`, `terraform plan` and then `terraform apply` with all
   three image URI variables empty. This creates the private ECR repositories,
   Artifact Registry repository, storage, identity and data-plane resources.
4. Record `api_ecr_repository_url`, `dispatcher_ecr_repository_url`,
   `worker_artifact_registry_repository`, `api_gateway_url` and
   `gcp_replica_bucket` from `terraform output`.

## 2. Publish immutable images and model assets

Authenticate Docker to the two team-owned registries. Build and push the API
and dispatcher with their respective Dockerfiles, and the worker with
`Dockerfile.worker`. Use immutable image digests (not mutable tags) in the
three Terraform image variables.

Upload the supplied model objects to the returned private GCS bucket, retaining
the manifest paths exactly:

```text
gs://<gcp_replica_bucket>/models/mdv5a.pt
gs://<gcp_replica_bucket>/models/model.pt
```

Before upload, compare both SHA-256 values with `models/model-manifest.json`.
The Cloud Run service identity has object-viewer access only.

## 3. Deploy and configure login

1. Set the three image digest URIs in `terraform.tfvars` and apply again.
2. Replace `ui_callback_urls` and `ui_logout_urls` with the HTTPS
   `api_gateway_url` output (plus a trailing slash if required by the Hosted
   UI), then apply once more.
3. Open the API URL, use Cognito Hosted UI to register with first name, last
   name, verified email and password, then validate sign-in and sign-out.
4. Complete an SNS subscription from the application and retain its
   confirmation email for the demo.

## 4. Release gates

- Run `terraform validate`, all Python tests and the real
  `scripts/run_model_smoke.py` before presenting.
- Verify Cloud Run is private, the worker can only be invoked through AWS
  workload identity federation, and no service-account key exists.
- Follow [PRE_SUBMISSION_CHECKLIST.md](PRE_SUBMISSION_CHECKLIST.md) to capture
  the required evidence.
