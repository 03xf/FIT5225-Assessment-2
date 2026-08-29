# Architecture and Trust Boundaries

```text
Browser
  | Cognito Hosted UI / JWT
  v
API Gateway (public static UI; JWT on /api/*) --> API Lambda
        |                                            |        |
        |-- SHA-256-bound presigned PUT ------------>|        +--> DynamoDB tag index
        v                                            v
   Cognito user pool                              private S3 raw/thumbnail
                                                          |
                                  checksum-verified completion -> SQS -> dispatcher Lambda
                                                                          |
                                signed service request                  v
                                      +--------------------------> private Alibaba Function Compute ML worker
                                                                            |--> private Alibaba OSS model artifacts
                                                                            |
                                                                     signed HMAC callback
                                                                            v
                                                                  API Lambda -> DynamoDB + SNS email
```

## Responsibility split

| Provider | Components | Responsibility |
|---|---|---|
| AWS | Cognito, S3, API Gateway, Lambda, SQS, DynamoDB, SNS | User identity, public entry points, primary storage, metadata, notifications and durable API authorization |
| Alibaba Cloud | OSS, Function Compute | Private model artifacts and ML worker execution |

## Critical implementation rules

1. The browser never receives AWS/Alibaba long-lived credentials or the Function Compute worker URL.
2. API Gateway validates Cognito tokens before business functions run. Lambda roles are scoped to the precise S3 prefixes, DynamoDB table, queue and SNS topic they need.
3. The browser calculates SHA-256, and the presigned S3 PUT binds it as an S3-validated checksum. The completion endpoint requires the returned S3 checksum before it queues processing.
4. Processing is emitted only after successful completion verification. The media ID is the idempotency key; callbacks update the one owner-scoped record and its tag index.
5. `media_tags` is an inverted index. Multi-tag queries find the intersection, not a union; each requested tag also checks its minimum count.
6. The query-by-file object is written only to a TTL-bound temporary prefix, never to the main table/index, and is deleted after processing.
7. Deletion is owner-scoped and removes source/thumbnail S3 keys before DynamoDB tag records. An S3 delete error retains metadata so the retry remains visible rather than silently orphaning storage.

## Model lifecycle

`model-manifest.json` names a version and checksum-pinned detector/classifier objects. The worker verifies SHA-256 before legacy PyTorch deserialization. A new model release is uploaded under a new immutable prefix, evaluated against the supplied test set, and activated by atomically updating the manifest pointer. This keeps the function/container source unchanged as required by section 4.1.
