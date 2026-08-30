"""Short-lived Google identity for AWS Lambda callers of private Cloud Run."""
from __future__ import annotations

import json
import os
from pathlib import Path

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token


def configure_google_wif(audience: str, service_account: str) -> None:
    """Write non-secret AWS external-account configuration to Lambda /tmp."""
    configuration = {
        "type": "external_account",
        "audience": audience,
        "subject_token_type": "urn:ietf:params:aws:token-type:aws4_request",
        "token_url": "https://sts.googleapis.com/v1/token",
        "service_account_impersonation_url": f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{service_account}:generateAccessToken",
        "credential_source": {
            "environment_id": "aws1",
            "region_url": "http://169.254.169.254/latest/meta-data/placement/availability-zone",
            "url": "http://169.254.169.254/latest/meta-data/iam/security-credentials",
            "regional_cred_verification_url": "https://sts.{region}.amazonaws.com?Action=GetCallerIdentity&Version=2011-06-15",
        },
    }
    path = Path("/tmp/pacificbio-gcp-wif.json")
    path.write_text(json.dumps(configuration), encoding="utf-8")
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(path)


def cloud_run_id_token(worker_url: str, audience: str, service_account: str) -> str:
    configure_google_wif(audience, service_account)
    return id_token.fetch_id_token(GoogleRequest(), worker_url)
