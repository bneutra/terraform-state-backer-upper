provider "aws" {
  region = var.region

  default_tags {
    tags = local.common_tags
  }
}
locals{
  lambda_name = "${var.prefix}-state-saver-webhook"
}
# create an s3 bucket for state storage
resource "aws_s3_bucket" "state-file-backups" {
  bucket = "${var.prefix}-state-files"
}


resource "aws_s3_bucket_versioning" "state-file-backups" {
  bucket = aws_s3_bucket.state-file-backups.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "state-file-backups" {
  bucket = aws_s3_bucket.state-file-backups.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state-file-backups" {
  bucket = aws_s3_bucket.state-file-backups.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.state-file-backups-key.arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_kms_key" "state-file-backups-key" {
  description             = "This key is used to encrypt bucket objects"
  deletion_window_in_days = 10
}

# create webhook
module "webhook" {
  source        = "terraform-aws-modules/lambda/aws"
  version       = "7.4.0"
  function_name           = local.lambda_name
  description             = "Receives webhook notifications from TFC and saves state files to S3."
  handler                 = "main.lambda_handler"
  runtime                 = "python3.12"
  policies           = [aws_iam_policy.lambda_policy.arn]
    number_of_policies = 1
  attach_policies    = true
  memory_size        = 1024
  create_role        = true
  role_name          = local.lambda_name
  timeout            = 30
  source_path = [
    {
      path             = "${path.module}/files",
      pip_requirements = "${path.module}/files/requirements.txt"
    }
  ]

  environment_variables = {
      REGION                     = var.region
      S3_BUCKET                  = aws_s3_bucket.state-file-backups.id
      SALT_PATH                  = aws_ssm_parameter.notification_token.name
      TFC_TOKEN_PATH             = aws_ssm_parameter.tfc_token.name
  }
    tags = {
    datadog  = true
    service  = local.lambda_name
    CostType = "OpEx-RnD"
  }
}


resource "aws_ssm_parameter" "tfc_token" {
  name        = "${var.prefix}-tfc-token"
  description = "Terraform Cloud team token"
  type        = "SecureString"
  value       = "CHANGE_ME"
  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "notification_token" {
  name        = "${var.prefix}-tfc-notification-token"
  description = "Terraform Cloud webhook notification token"
  type        = "SecureString"
  value       = "CHANGE_ME"
  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_s3_bucket" "webhook" {
  bucket = "${var.prefix}-state-saver-webhook"
}

resource "aws_s3_bucket_public_access_block" "webhook" {
  bucket = aws_s3_bucket.webhook.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_object" "webhook" {
  bucket = aws_s3_bucket.webhook.id
  key    = "v1/webhook.zip"
  source = "${path.module}/files/webhook.zip"

  etag = filemd5("${path.module}/files/webhook.zip")
}


# data "aws_iam_policy_document" "webhook_assume_role_policy_definition" {
#   statement {
#     effect  = "Allow"
#     actions = ["sts:AssumeRole"]
#     principals {
#       identifiers = ["lambda.amazonaws.com"]
#       type        = "Service"
#     }
#   }
# }

resource "aws_iam_policy" "lambda_policy" {
  name   = "${var.prefix}-state-saver-lambda-webhook-policy"
  policy = data.aws_iam_policy_document.lambda_policy_definition.json
}

data "aws_iam_policy_document" "lambda_policy_definition" {
  statement {
    effect    = "Allow"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.notification_token.arn, aws_ssm_parameter.tfc_token.arn]
  }
  statement {
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.state-file-backups.arn}/*"]
  }
  statement {
    effect    = "Allow"
    actions   = ["kms:GenerateDataKey"]
    resources = [aws_kms_key.state-file-backups-key.arn]
  }
}


resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.webhook.lambda_function_name
  principal     = "apigateway.amazonaws.com"

  # The "/*/*" portion grants access from any method on any resource
  # within the API Gateway REST API.
  source_arn = "${aws_api_gateway_rest_api.webhook.execution_arn}/*/*"
}

# api gateway
resource "aws_api_gateway_rest_api" "webhook" {
  name        = "${var.prefix}-state-saver-webhook"
  description = "TFC webhook receiver for saving state files"
}

resource "aws_api_gateway_resource" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.webhook.id
  parent_id   = aws_api_gateway_rest_api.webhook.root_resource_id
  path_part   = "{proxy+}"
}

resource "aws_api_gateway_method" "proxy" {
  rest_api_id   = aws_api_gateway_rest_api.webhook.id
  resource_id   = aws_api_gateway_resource.proxy.id
  http_method   = "ANY"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "lambda" {
  rest_api_id = aws_api_gateway_rest_api.webhook.id
  resource_id = aws_api_gateway_method.proxy.resource_id
  http_method = aws_api_gateway_method.proxy.http_method

  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = module.webhook.lambda_function_invoke_arn
}

resource "aws_api_gateway_method" "proxy_root" {
  rest_api_id   = aws_api_gateway_rest_api.webhook.id
  resource_id   = aws_api_gateway_rest_api.webhook.root_resource_id
  http_method   = "ANY"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "lambda_root" {
  rest_api_id = aws_api_gateway_rest_api.webhook.id
  resource_id = aws_api_gateway_method.proxy_root.resource_id
  http_method = aws_api_gateway_method.proxy_root.http_method

  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = module.webhook.lambda_function_invoke_arn
}

resource "aws_api_gateway_deployment" "webhook" {
  depends_on = [
    aws_api_gateway_integration.lambda,
    aws_api_gateway_integration.lambda_root,
  ]

  rest_api_id = aws_api_gateway_rest_api.webhook.id
  stage_name  = "state-saver"
}


