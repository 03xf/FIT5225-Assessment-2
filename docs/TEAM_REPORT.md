# Pacific BioArchive: Team Report

**Unit:** FIT5225 Assignment 2  
**Team:** Group 13
**Repository:** [03xf/FIT5225-Assessment-2](https://github.com/03xf/FIT5225-Assessment-2) (private repository; teaching staff must be invited before submission)

## 1. System overview and design choices

Pacific BioArchive is an authenticated, multi-cloud wildlife-media archive. AWS hosts Cognito, API Gateway, Lambda, S3, DynamoDB, SQS and SNS; Alibaba Cloud hosts the private Function Compute worker and OSS model artifacts. SQS keeps uploads asynchronous, while query-by-file uses a 300-second timeout for worker cold starts. Private buckets and short-lived signed URLs limit exposure.

## 2. Multi-cloud architecture

Figure 1 shows the deployed AWS/Alibaba Cloud boundary and request flow, with service labels and trust boundaries readable for marking.

![Figure 1. Pacific BioArchive multi-cloud architecture](evidence/architecture-diagram.svg)
*Figure 1. Multi-cloud architecture showing the AWS and Alibaba Cloud service boundary and signed processing flow.*

```text
Browser -> Cognito Hosted UI -> API Gateway (JWT) -> API Lambda
                         |             |-- DynamoDB owner metadata/tag index
                         |             |-- private S3 raw + thumbnail objects
                         |             `-- SQS -> dispatcher Lambda
                         |                           -> signed request -> Alibaba FC worker
                         |                                                  |-> private OSS models
                         |                                                  `-> HMAC callback -> API Lambda -> DynamoDB/SNS
```

The browser calculates SHA-256 and receives no long-lived credentials or worker URL. API Gateway rejects unauthenticated `/api/*` requests. Lambda roles are prefix/service scoped; the worker uses a dispatcher-only key and HMAC callbacks. See [ARCHITECTURE.md](ARCHITECTURE.md) for the trust boundary.

## 3. Functional implementation and testing guide

1. Open the UI, verify Cognito, demonstrate sign-in/sign-out, and show anonymous `/api/media` rejection (401).
2. Upload `Bos_taurus_1.JPG`: SHA-256-bound presigned PUT, owner item in DynamoDB, and duplicate suppression.
3. Upload `video.mp4`: frame sampling, thumbnail, model-hash checks and tags; the record reaches `READY`. Logs: [function-compute-sls-20260830.md](evidence/function-compute-sls-20260830.md).
4. Run species and AND queries; resolve a thumbnail as two users to show owner isolation.
5. Use query-by-file and verify TTL cleanup without creating an archive item.
6. Demonstrate bulk tag add/remove and deletion; verify S3 and DynamoDB before/after, then restore the test image.
7. Subscribe to `felis_catus`, confirm the SNS email, and upload matching media. See [evidence/README.md](evidence/README.md).

## 4. Evidence and limitations

AWS is in `ap-southeast-2`; Alibaba Cloud is in `cn-hangzhou`; the worker is `pacificbio-worker`. The regression suite passes **16 tests**. Evidence covers authentication, 401 rejection, deduplication, video readiness, queries, ownership, cleanup, bulk tags, deletion/restoration, SNS, storage/database state and SLS logs. The image scan still reports upstream base-layer vulnerabilities (`CRITICAL=4` plus `HIGH` findings); rebuild on remediated bases or document a justified risk decision. The SQS DLQ has three historical failed messages. No accuracy percentage is claimed because a 30-image evaluation is outstanding.

### Selected rubric evidence

The following screenshots are embedded for quick marking; the complete evidence bundle is in [evidence/README.md](evidence/README.md).

![Authenticated Cognito session](evidence/screenshots-20260830/03-authenticated-home.png)
*Figure 2. Authenticated Cognito session with the owner archive loaded.*
![Signed-out access state](evidence/screenshots-20260830/04-signed-out-home.png)
*Figure 3. Signed-out state showing the UI without an authenticated session.*
![Anonymous API rejection](evidence/screenshots-20260830/01-unauthorized-api-media.png)
*Figure 4. Anonymous request to `/api/media` rejected with HTTP 401.*
![Video ready with generated tags](evidence/screenshots-20260830/12-video-ready-card.png)
*Figure 5. Video record in READY state with generated species tags.*
![Function Compute SLS invocation logs](evidence/screenshots-20260830/28-function-compute-real-logs.png)
*Figure 6. Alibaba Function Compute invocation logs recorded in SLS.*
![AND tag query](evidence/screenshots-20260830/08-and-query.png)
*Figure 7. AND tag query returning records matching every condition.*
![Bulk selection](evidence/screenshots-20260830/06-bulk-select.png)
*Figure 8. Two media records selected with the bulk tag controls ready.*
![Bulk add tags success](evidence/screenshots-20260830/07-bulk-add-tags-success.png)
*Figure 9. Temporary tag added to both selected records (“Tags added”).*
![Bulk remove tags success](evidence/screenshots-20260830/07-bulk-remove-tags-success.png)
*Figure 10. Temporary tag removed from both records (“Tags removed”).*
![Bulk remove missing tag](evidence/screenshots-20260830/07-bulk-remove-missing-tag.png)
*Figure 11. Removing a non-existent tag left records unchanged.*
![Deletion confirmation](evidence/screenshots-20260830/20-app-test-delete-complete.png)
*Figure 12. Application confirmation after deleting the selected test record.*
![DynamoDB state after deletion](evidence/screenshots-20260830/23-dynamodb-test-after-delete.png)
*Figure 13. DynamoDB item absent after deletion.*
![SNS tag-added notification](evidence/sns-tag-added-notification-20260829.png)
*Figure 14. Actual AWS SNS email received after the watched `felis_catus` tag was added; the payload records `event: "tag-added"`.*
![AWS IAM role and least-privilege policy](evidence/screenshots-20260830/29-aws-iam-wide.png)
*Figure 15. AWS API Lambda role with the inline `least-privilege-media-api` policy; the role identity and policy attachment are fully visible.*
![IAM policy permissions (DynamoDB section)](evidence/screenshots-20260830/29-aws-iam-policy-json.png)
*Figure 15a. IAM policy JSON showing the scoped DynamoDB actions and table/index ARNs.*
![IAM policy permissions (SNS and SQS section)](evidence/screenshots-20260830/29-aws-iam-policy-json-end.png)
*Figure 15b. IAM policy JSON showing SNS publish/subscribe and SQS SendMessage permissions, including the scoped resource ARNs.*
![AWS SQS queue encryption](evidence/screenshots-20260830/30-aws-sqs-dlq-wide.png)
*Figure 16. AWS processing queue details showing the queue name, standard queue type, and enabled SSE-SQS encryption.*
![AWS SQS dead-letter queue settings](evidence/screenshots-20260830/30-aws-sqs-dlq-settings.png)
*Figure 16a. The same processing queue configured with an enabled dead-letter queue, the DLQ ARN, and maximum receive count of 3.*
![AWS SQS redrive settings](evidence/screenshots-20260830/31-aws-sqs-redrive-settings-focused.png)
*Figure 17. Source queue redrive configuration: 15-minute visibility timeout, DLQ target and maximum receive count of 3.*
![Alibaba OSS private ACL](evidence/screenshots-20260830/32-alibaba-oss-private-acl-focused.png)
*Figure 18. Alibaba OSS model bucket `pacificbio-models-748998941962-20260828` with Bucket ACL set to Private; all object access requires authentication.*
![Thumbnail URL and query-by-file controls](evidence/screenshots-20260830/10-thumbnail-preview.png)
*Figure 19. Authenticated thumbnail resolution and query-by-file panel; no archive item is added.*
![Single-species query](evidence/screenshots-20260830/09-single-species-query.png)
*Figure 20. Single-species search for `alectura_lathami` returning matching ready records.*
![Video processing result](evidence/screenshots-20260830/11-video-ready-and-tags.png)
*Figure 21. Processed `video.mp4` in READY state with model version and aggregate species/count tags.*
![S3 objects before deletion](evidence/screenshots-20260830/18-s3-test-before-delete.png)
*Figure 22. S3 console before deletion showing the test source object.*
![S3 objects after deletion](evidence/screenshots-20260830/21-s3-test-after-delete-raw.png)
*Figure 23. S3 console after deletion showing the test source prefix empty.*
![Checksum-validated archive](evidence/screenshots-20260830/03-authenticated-home.png)
*Figure 24. Production archive banner showing checksum validation; duplicate and SHA-256 details are in the upload evidence record.*

## 5. Team contributions

| Name and student ID | Contribution % | Delivered work |
|---|---:|---|
| **Yuhan Pei (36667528)** | **25%** | **Member 01: API, Cognito/JWT authentication and DynamoDB persistence.** |
| **Mingyu Xu (36667277)** | **25%** | **Member 02: frontend, upload/checksum, search, tags and deletion workflows.** |
| **Zhihao Qian (36667625)** | **25%** | **Member 03: Function Compute worker, model validation, classification and video processing.** |
| **Zhicong Wang (36667676)** | **25%** | **Member 04: Terraform infrastructure, IAM/RAM, SQS/DLQ, deployment and security evidence.** |

The four contribution percentages total 100%; verify repository history before submission.

## 6. Generative AI declaration

GPT was used only to brainstorm design options and to help debug implementation errors. Team members reviewed every suggestion, tested the resulting system, and can explain, modify and defend the submitted code and architecture.
