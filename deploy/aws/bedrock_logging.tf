# The Bedrock call log (bedrock_call_log): Amazon Bedrock's model invocation
# logging, turned on in each region the app calls Bedrock in. Every
# InvokeModel and Converse call, from any caller in the account, gets a record
# in the log group /aws/bedrock/<name>/model-invocations of that region: who
# made it (the role and session, or the user), the model or inference
# profile, and its input and output token counts.
#
# The text of prompts and answers, images, embeddings and video are left out,
# so the documents and questions stay out of the log.
#
# Bedrock keeps one logging setting per account and region, so only one
# deployment in an account should turn this on.

locals {
  bedrock_call_log_regions = var.bedrock_call_log ? local.bedrock_regions : []
}

resource "aws_cloudwatch_log_group" "bedrock_calls" {
  for_each = toset(local.bedrock_call_log_regions)

  region            = each.key
  name              = "/aws/bedrock/${var.name}/model-invocations"
  retention_in_days = var.bedrock_call_log_retention_days
}

data "aws_iam_policy_document" "bedrock_logging_assume" {
  count = length(local.bedrock_call_log_regions) > 0 ? 1 : 0

  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [for r in local.bedrock_call_log_regions : "arn:aws:bedrock:${r}:${data.aws_caller_identity.current.account_id}:*"]
    }
  }
}

# The role Bedrock writes the log with.
resource "aws_iam_role" "bedrock_logging" {
  count = length(local.bedrock_call_log_regions) > 0 ? 1 : 0

  name               = "${var.name}-bedrock-call-log"
  assume_role_policy = data.aws_iam_policy_document.bedrock_logging_assume[0].json
}

data "aws_iam_policy_document" "bedrock_logging" {
  count = length(local.bedrock_call_log_regions) > 0 ? 1 : 0

  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [for g in aws_cloudwatch_log_group.bedrock_calls : "${g.arn}:log-stream:*"]
  }
}

resource "aws_iam_role_policy" "bedrock_logging" {
  count = length(local.bedrock_call_log_regions) > 0 ? 1 : 0

  name   = "write-bedrock-call-log"
  role   = aws_iam_role.bedrock_logging[0].id
  policy = data.aws_iam_policy_document.bedrock_logging[0].json
}

resource "aws_bedrock_model_invocation_logging_configuration" "this" {
  for_each = toset(local.bedrock_call_log_regions)

  region = each.key

  logging_config {
    text_data_delivery_enabled      = false
    image_data_delivery_enabled     = false
    embedding_data_delivery_enabled = false
    video_data_delivery_enabled     = false

    cloudwatch_config {
      log_group_name = aws_cloudwatch_log_group.bedrock_calls[each.key].name
      role_arn       = aws_iam_role.bedrock_logging[0].arn
    }
  }

  depends_on = [aws_iam_role_policy.bedrock_logging]
}
