# Pacific BioArchive: Team Report

> Replace every bracketed item with verified team-specific evidence. Main prose must remain within 1000 words; tables, official-icon architecture figure, UI screenshots and references are excluded.

## 1. System overview and design choices

Pacific BioArchive stores and retrieves wildlife images and videos across AWS and Alibaba Cloud. AWS Cognito authenticates users; API Gateway validates JWTs before the serverless API is reached. S3 stores original media and thumbnails, DynamoDB stores owner-scoped metadata and tag indexes, SQS decouples processing, and SNS publishes watched-tag notifications. A private Alibaba Function Compute worker runs the supplied MegaDetector and SpeciesNet models, with Alibaba OSS storing protected model artifacts. [Insert why this split was selected, cost/latency trade-offs and actual regions.]

## 2. Multi-cloud architecture

Insert the official AWS and Alibaba Cloud icon diagram from the final deployed architecture. Explain: browser -> Cognito -> API/S3 -> SQS -> Function Compute -> HMAC callback -> DynamoDB/SNS. State that object URLs are short-lived and the worker is not browser-accessible.

## 3. Functional implementation and testing guide

1. Register at [Hosted UI URL], verify email, sign in and sign out.
2. Upload [sample image]; record duplicate-upload behavior on the second upload.
3. Wait for [actual Function Compute processing log], then inspect the thumbnail and automatic tags.
4. Execute [actual AND/count query] and [species query].
5. Paste [actual thumbnail URL] to obtain the full media URL.
6. Submit [actual temporary query image]; confirm no persistent item was added.
7. Multi-select [items], bulk add/remove a tag, delete one item, and verify storage/database removal.
8. Subscribe to [tag] and show a confirmed notification email.

## 4. Evidence and limitations

Summarize actual test results, model version/checksum, deployed URLs and operational limitations. Do not claim a model accuracy metric unless measured using the supplied 30-image set.

## 5. Team contribution table

| Name and student ID | Contribution % | Delivered work (max 100 words per person) |
|---|---:|---|
| [member 1] | [actual] | [Git-linked contribution] |
| [member 2] | [actual] | [Git-linked contribution] |
| [member 3] | [actual] | [Git-linked contribution] |
| [member 4, if applicable] | [actual] | [Git-linked contribution] |

Explain the assignment's contribution-percentage constraint truthfully. Link the **private** repository and confirm all members committed code.

## 6. Generative AI declaration

Generative AI was used selectively for [planning/code drafting/documentation]. All generated suggestions were reviewed, tested and modified by team members, who understand and can explain the submitted implementation. [Describe actual use accurately, including if no GenAI output was retained.]
