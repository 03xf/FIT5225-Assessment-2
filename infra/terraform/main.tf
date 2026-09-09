resource "random_id" "suffix" {
  byte_length = 4
}
resource "random_password" "callback_hmac" {
  length  = 48
  special = false
}
resource "random_password" "worker_key" {
  length  = 48
  special = false
}

locals {
  suffix      = random_id.suffix.hex
  bucket_name = "${var.project_name}-${local.suffix}"
  tags        = { Project = var.project_name, ManagedBy = "Terraform", Assessment = "FIT5225-A2" }
}

resource "aws_ecr_repository" "api" {
  name                 = "${var.project_name}-api-${local.suffix}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "AES256" }
  tags = local.tags
}
resource "aws_ecr_repository" "dispatcher" {
  name                 = "${var.project_name}-dispatcher-${local.suffix}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "AES256" }
  tags = local.tags
}

resource "aws_cognito_user_pool" "users" {
  name                     = "${var.project_name}-users-${local.suffix}"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_numbers   = true
    require_symbols   = true
    require_uppercase = true
  }
  schema {
    name                = "given_name"
    attribute_data_type = "String"
    mutable             = true
    required            = true
    string_attribute_constraints {
      min_length = 1
      max_length = 100
    }
  }
  schema {
    name                = "family_name"
    attribute_data_type = "String"
    mutable             = true
    required            = true
    string_attribute_constraints {
      min_length = 1
      max_length = 100
    }
  }
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
  tags = local.tags
}

resource "aws_cognito_user_pool_client" "web" {
  name                                 = "${var.project_name}-web"
  user_pool_id                         = aws_cognito_user_pool.users.id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  callback_urls                        = var.ui_callback_urls
  logout_urls                          = var.ui_logout_urls
  supported_identity_providers         = ["COGNITO"]
}
resource "aws_cognito_user_pool_domain" "web" {
  count        = var.cognito_domain_prefix == "" ? 0 : 1
  domain       = var.cognito_domain_prefix
  user_pool_id = aws_cognito_user_pool.users.id
}

resource "aws_s3_bucket" "media" {
  bucket = local.bucket_name
  tags   = local.tags
}
resource "aws_s3_bucket_public_access_block" "media" {
  bucket                  = aws_s3_bucket.media.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_versioning" "media" {
  bucket = aws_s3_bucket.media.id
  versioning_configuration {
    status = "Enabled"
  }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "media" {
  bucket = aws_s3_bucket.media.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_cors_configuration" "media" {
  bucket = aws_s3_bucket.media.id
  cors_rule {
    allowed_headers = ["content-type", "x-amz-checksum-sha256", "x-amz-meta-sha256"]
    allowed_methods = ["PUT"]
    # Browser Origin headers never include a trailing slash; keep Cognito's
    # exact redirect URI (which does) separate from the CORS origin value.
    allowed_origins = [for origin in var.ui_callback_urls : trimsuffix(origin, "/")]
    expose_headers  = ["ETag", "x-amz-checksum-sha256"]
    max_age_seconds = 300
  }
}
resource "aws_s3_bucket_lifecycle_configuration" "media" {
  bucket = aws_s3_bucket.media.id
  rule {
    id     = "expire-temporary-query"
    status = "Enabled"
    filter { prefix = "temporary-query/" }
    expiration { days = 1 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}

resource "aws_dynamodb_table" "media" {
  name         = "${var.project_name}-media-${local.suffix}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"
  attribute {
    name = "PK"
    type = "S"
  }
  attribute {
    name = "SK"
    type = "S"
  }
  attribute {
    name = "GSI1PK"
    type = "S"
  }
  attribute {
    name = "GSI1SK"
    type = "S"
  }
  attribute {
    name = "GSI2PK"
    type = "S"
  }
  attribute {
    name = "GSI2SK"
    type = "S"
  }
  attribute {
    name = "GSI3PK"
    type = "S"
  }
  attribute {
    name = "GSI3SK"
    type = "S"
  }
  global_secondary_index {
    name            = "checksum-index"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }
  global_secondary_index {
    name            = "thumbnail-index"
    hash_key        = "GSI2PK"
    range_key       = "GSI2SK"
    projection_type = "ALL"
  }
  global_secondary_index {
    name            = "subscription-index"
    hash_key        = "GSI3PK"
    range_key       = "GSI3SK"
    projection_type = "ALL"
  }
  server_side_encryption { enabled = true }
  point_in_time_recovery { enabled = true }
  tags = local.tags
}
resource "aws_sns_topic" "notifications" {
  name = "${var.project_name}-tag-notifications-${local.suffix}"
  tags = local.tags
}
resource "aws_sqs_queue" "processing_dlq" {
  name                      = "${var.project_name}-processing-dlq-${local.suffix}"
  message_retention_seconds = 1209600
  tags                      = local.tags
}
resource "aws_sqs_queue" "processing" {
  name                       = "${var.project_name}-processing-${local.suffix}"
  visibility_timeout_seconds = 900
  redrive_policy             = jsonencode({ deadLetterTargetArn = aws_sqs_queue.processing_dlq.arn, maxReceiveCount = 3 })
  tags                       = local.tags
}
resource "aws_apigatewayv2_api" "http" {
  name          = "${var.project_name}-api-${local.suffix}"
  protocol_type = "HTTP"
  tags          = local.tags
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.http.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "cognito-jwt"
  jwt_configuration {
    audience = [aws_cognito_user_pool_client.web.id]
    issuer   = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.users.id}"
  }
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}
resource "aws_iam_role" "api" {
  name               = "${var.project_name}-api-${local.suffix}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = local.tags
}
resource "aws_iam_role_policy" "api" {
  name = "least-privilege-media-api"
  role = aws_iam_role.api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = "*" },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], Resource = ["${aws_s3_bucket.media.arn}/raw/*", "${aws_s3_bucket.media.arn}/thumbnails/*", "${aws_s3_bucket.media.arn}/temporary-query/*"] },
      { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:BatchWriteItem", "dynamodb:TransactWriteItems"], Resource = [aws_dynamodb_table.media.arn, "${aws_dynamodb_table.media.arn}/index/*"] },
      { Effect = "Allow", Action = ["sns:Publish", "sns:Subscribe"], Resource = aws_sns_topic.notifications.arn },
      { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = aws_sqs_queue.processing.arn }
    ]
  })
}
resource "aws_lambda_function" "api" {
  count         = var.api_lambda_image_uri == "" ? 0 : 1
  function_name = "${var.project_name}-api-${local.suffix}"
  package_type  = "Image"
  image_uri     = var.api_lambda_image_uri
  role          = aws_iam_role.api.arn
  # Query-by-file invokes the remote model synchronously and may include a
  # cold-start download, so the API timeout must exceed the worker startup
  # window. Upload processing remains asynchronous through SQS.
  timeout     = 300
  memory_size = 1024
  environment {
    variables = {
      PACIFICBIO_ENV                         = "production"
      PACIFICBIO_COGNITO_USER_POOL_ID        = aws_cognito_user_pool.users.id
      PACIFICBIO_COGNITO_APP_CLIENT_ID       = aws_cognito_user_pool_client.web.id
      PACIFICBIO_COGNITO_DOMAIN              = try("https://${aws_cognito_user_pool_domain.web[0].domain}.auth.${var.aws_region}.amazoncognito.com", "")
      PACIFICBIO_AWS_MEDIA_BUCKET            = aws_s3_bucket.media.id
      PACIFICBIO_DYNAMODB_TABLE              = aws_dynamodb_table.media.name
      PACIFICBIO_SNS_TOPIC_ARN               = aws_sns_topic.notifications.arn
      PACIFICBIO_AWS_PROCESSING_QUEUE_URL    = aws_sqs_queue.processing.url
      PACIFICBIO_WORKER_CALLBACK_HMAC_SECRET = random_password.callback_hmac.result
      PACIFICBIO_ALIBABA_PROCESSOR_URL       = var.alibaba_processor_url
      PACIFICBIO_ALIBABA_REGION              = var.alibaba_region
      PACIFICBIO_ALIBABA_OSS_BUCKET          = alicloud_oss_bucket.models.bucket
      PACIFICBIO_ALIBABA_OSS_ENDPOINT        = "https://oss-${var.alibaba_region}-internal.aliyuncs.com"
      PACIFICBIO_WORKER_SHARED_KEY           = random_password.worker_key.result
    }
  }
  tags = local.tags
}
resource "aws_apigatewayv2_integration" "api" {
  count                  = var.api_lambda_image_uri == "" ? 0 : 1
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api[0].invoke_arn
  payload_format_version = "2.0"
}
resource "aws_apigatewayv2_route" "api_root" {
  count              = var.api_lambda_image_uri == "" ? 0 : 1
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "ANY /api"
  target             = "integrations/${aws_apigatewayv2_integration.api[0].id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}
resource "aws_apigatewayv2_route" "api_proxy" {
  count              = var.api_lambda_image_uri == "" ? 0 : 1
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "ANY /api/{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.api[0].id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}
resource "aws_apigatewayv2_route" "health" {
  count     = var.api_lambda_image_uri == "" ? 0 : 1
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "GET /api/health"
  target    = "integrations/${aws_apigatewayv2_integration.api[0].id}"
}
resource "aws_apigatewayv2_route" "auth_config" {
  count     = var.api_lambda_image_uri == "" ? 0 : 1
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "GET /auth/config"
  target    = "integrations/${aws_apigatewayv2_integration.api[0].id}"
}
resource "aws_apigatewayv2_route" "internal_proxy" {
  count     = var.api_lambda_image_uri == "" ? 0 : 1
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "ANY /internal/{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.api[0].id}"
}
resource "aws_apigatewayv2_route" "web_root" {
  count     = var.api_lambda_image_uri == "" ? 0 : 1
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "ANY /"
  target    = "integrations/${aws_apigatewayv2_integration.api[0].id}"
}
resource "aws_apigatewayv2_route" "web_proxy" {
  count     = var.api_lambda_image_uri == "" ? 0 : 1
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.api[0].id}"
}
resource "aws_lambda_permission" "api_gateway" {
  count         = var.api_lambda_image_uri == "" ? 0 : 1
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

resource "aws_iam_role" "dispatcher" {
  name               = "${var.project_name}-dispatcher-${local.suffix}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = local.tags
}
resource "aws_iam_role_policy" "dispatcher" {
  name = "queue-object-metadata"
  role = aws_iam_role.dispatcher.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = "*" },
    { Effect = "Allow", Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], Resource = aws_sqs_queue.processing.arn },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], Resource = ["${aws_s3_bucket.media.arn}/raw/*", "${aws_s3_bucket.media.arn}/thumbnails/*", "${aws_s3_bucket.media.arn}/temporary-query/*"] },
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"], Resource = [aws_dynamodb_table.media.arn, "${aws_dynamodb_table.media.arn}/index/*"] }
  ] })
}
resource "aws_lambda_function" "dispatcher" {
  count         = var.dispatcher_lambda_image_uri == "" ? 0 : 1
  function_name = "${var.project_name}-dispatcher-${local.suffix}"
  package_type  = "Image"
  image_uri     = var.dispatcher_lambda_image_uri
  role          = aws_iam_role.dispatcher.arn
  timeout       = 900
  memory_size   = 2048
  environment {
    variables = {
      PACIFICBIO_ENV                          = "production"
      PACIFICBIO_DYNAMODB_TABLE               = aws_dynamodb_table.media.name
      PACIFICBIO_AWS_MEDIA_BUCKET             = aws_s3_bucket.media.id
      PACIFICBIO_ALIBABA_PROCESSOR_URL        = var.alibaba_processor_url
      PACIFICBIO_ALIBABA_REGION               = var.alibaba_region
      PACIFICBIO_ALIBABA_OSS_BUCKET           = alicloud_oss_bucket.models.bucket
      PACIFICBIO_ALIBABA_OSS_ENDPOINT         = "https://oss-${var.alibaba_region}-internal.aliyuncs.com"
      PACIFICBIO_WORKER_CALLBACK_URL          = "${aws_apigatewayv2_api.http.api_endpoint}/internal/worker-callback"
      PACIFICBIO_WORKER_CALLBACK_NONCE_PREFIX = "${local.suffix}-dispatcher-"
      PACIFICBIO_WORKER_SHARED_KEY            = random_password.worker_key.result
    }
  }
  tags = local.tags
}
resource "aws_lambda_event_source_mapping" "dispatcher" {
  count            = var.dispatcher_lambda_image_uri == "" ? 0 : 1
  event_source_arn = aws_sqs_queue.processing.arn
  function_name    = aws_lambda_function.dispatcher[0].arn
  batch_size       = 1
}

resource "alicloud_oss_bucket" "models" {
  bucket = var.alibaba_oss_bucket_name
  versioning { status = "Enabled" }
  tags = local.tags
}

resource "alicloud_oss_bucket_acl" "models" {
  bucket = alicloud_oss_bucket.models.bucket
  acl    = "private"
}
