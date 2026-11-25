# Two roles: the execution role ECS uses to pull images, write logs and read
# the secrets (the app keys, the model provider keys and the RDS-managed
# database password), and the task role the api, mcp, pipeline and migrate
# containers run as, which may call the Amazon Bedrock models config.json
# lists and no others.

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "read_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.app.arn,
      aws_secretsmanager_secret.providers.arn,
      aws_db_instance.main.master_user_secret[0].secret_arn,
    ]
  }
}

resource "aws_iam_role_policy" "read_secrets" {
  name   = "read-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.read_secrets.json
}

# --- Task role: Amazon Bedrock ---------------------------------------------

data "aws_caller_identity" "current" {}

resource "aws_iam_role" "task" {
  name               = "${var.name}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# Only the Bedrock models config.json offers may be called, so a changed
# setting or a stray script can't run up a bill on another model. They are
# the aws_bedrock entries of supported_llms ("model"), supported_embedding_models
# ("source", "model_id") and supported_rerank_models ("model_id"); adding a
# model to config.json allows it on the next deploy.
#
# An ID that starts with a geography (eu., us., apac., global., ...) is a
# cross-region inference profile: the profile itself is allowed, and its base
# model in every region, because the profile sends requests across regions.
# Regions stay open (rerank models are offered in only some regions); the
# model list is what limits cost. A config with no Bedrock model gets no
# Bedrock permission at all.
locals {
  deploy_config = jsondecode(file(var.config_json_path))

  bedrock_model_ids = sort(distinct(concat(
    [for m in values(try(local.deploy_config.supported_llms, {})) : m.model if try(m.provider, null) == "aws_bedrock"],
    [for m in values(try(local.deploy_config.supported_embedding_models, {})) : m.model_id if try(m.source, null) == "aws_bedrock"],
    [for m in values(try(local.deploy_config.supported_rerank_models, {})) : m.model_id if try(m.provider, null) == "aws_bedrock"],
  )))

  bedrock_profile_pattern = "^(?:us|us-gov|eu|apac|global|jp|au|ca)\\.(.+)$"
  bedrock_profile_ids     = [for id in local.bedrock_model_ids : id if can(regex(local.bedrock_profile_pattern, id))]
  bedrock_base_model_ids = distinct([
    for id in local.bedrock_model_ids :
    can(regex(local.bedrock_profile_pattern, id)) ? regex(local.bedrock_profile_pattern, id)[0] : id
  ])

  bedrock_resource_arns = sort(concat(
    [for id in local.bedrock_base_model_ids : "arn:aws:bedrock:*::foundation-model/${id}"],
    [for id in local.bedrock_profile_ids : "arn:aws:bedrock:*:${data.aws_caller_identity.current.account_id}:inference-profile/${id}"],
  ))
}

data "aws_iam_policy_document" "bedrock" {
  count = length(local.bedrock_model_ids) > 0 ? 1 : 0

  statement {
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = local.bedrock_resource_arns
  }
}

resource "aws_iam_role_policy" "bedrock" {
  count = length(local.bedrock_model_ids) > 0 ? 1 : 0

  name   = "invoke-bedrock"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.bedrock[0].json
}

# The policy used to be unconditional. Moving it keeps the same inline policy
# in place instead of deleting and re-adding one of the same name.
moved {
  from = aws_iam_role_policy.bedrock
  to   = aws_iam_role_policy.bedrock[0]
}
