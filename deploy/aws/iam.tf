# Two roles: the execution role ECS uses to pull images, write logs and read
# the secrets (the app keys, the model provider keys and the RDS-managed
# database password), and the task role the api, mcp, pipeline and migrate
# containers run as, which may call the Amazon Bedrock models config.json
# lists and no others, and only from the deployment's own network.

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

  # A policy attached to the role outside Terraform is detached before the
  # role is deleted, so removing the deployment doesn't fail on it.
  force_detach_policies = true
}

# Which Bedrock calls the role may make: only the models config.json offers,
# only in the regions the app calls them in, and only from the deployment's
# own network.
#
# - The models are the aws_bedrock entries of supported_llms ("model"),
#   supported_embedding_models ("source", "model_id") and
#   supported_rerank_models ("model_id"). Adding a model to config.json allows
#   it on the next deploy.
# - The app calls chat and embedding models in the deployment's region, and a
#   rerank model in its own "region", because rerank models are offered in only
#   some regions.
# - An ID that starts with a geography (eu., us., apac., global., ...) is a
#   cross-region inference profile, which may send each request to its model
#   in another region. The profile is allowed in the region the app calls it
#   in. Its base model is allowed in every region, but only for requests that
#   came through one of these profiles (bedrock:InferenceProfileArn).
# - The profiles and the models called directly are allowed only from the NAT
#   gateway's address, through which every container reaches AWS (network.tf).
#   A copy of the role's credentials used anywhere else is refused. The base
#   models behind a profile carry no address condition: AWS doesn't document
#   whether the caller's address is still known when a profile's request is
#   checked in another region, and they can only be reached through a profile,
#   which checks the address.
#
# A config with no Bedrock model gets no Bedrock permission at all.
locals {
  deploy_config = jsondecode(file(var.config_json_path))

  # Every Bedrock model config.json lists, with the region the app calls it in.
  bedrock_models = distinct(concat(
    [for m in values(try(local.deploy_config.supported_llms, {})) : { id = m.model, region = var.region } if try(m.provider, null) == "aws_bedrock"],
    [for m in values(try(local.deploy_config.supported_embedding_models, {})) : { id = m.model_id, region = var.region } if try(m.source, null) == "aws_bedrock"],
    [for m in values(try(local.deploy_config.supported_rerank_models, {})) : { id = m.model_id, region = coalesce(try(m.region, null), var.region) } if try(m.provider, null) == "aws_bedrock"],
  ))
  bedrock_model_ids = sort(distinct([for m in local.bedrock_models : m.id]))
  bedrock_regions   = sort(distinct([for m in local.bedrock_models : m.region]))

  bedrock_profile_pattern = "^(?:us|us-gov|eu|apac|global|jp|au|ca)\\.(.+)$"
  bedrock_profiles        = [for m in local.bedrock_models : m if can(regex(local.bedrock_profile_pattern, m.id))]
  bedrock_direct_models   = [for m in local.bedrock_models : m if !can(regex(local.bedrock_profile_pattern, m.id))]

  bedrock_profile_arns = sort(distinct([
    for m in local.bedrock_profiles : "arn:aws:bedrock:${m.region}:${data.aws_caller_identity.current.account_id}:inference-profile/${m.id}"
  ]))
  bedrock_direct_model_arns = sort(distinct([
    for m in local.bedrock_direct_models : "arn:aws:bedrock:${m.region}::foundation-model/${m.id}"
  ]))
  bedrock_routed_model_arns = sort(distinct([
    for m in local.bedrock_profiles : "arn:aws:bedrock:*::foundation-model/${regex(local.bedrock_profile_pattern, m.id)[0]}"
  ]))

  bedrock_allowed_source_ips = ["${aws_eip.nat.public_ip}/32"]
}

data "aws_iam_policy_document" "bedrock" {
  count = length(local.bedrock_models) > 0 ? 1 : 0

  statement {
    sid       = "FromTheDeploymentOnly"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = concat(local.bedrock_profile_arns, local.bedrock_direct_model_arns)

    condition {
      test     = "IpAddress"
      variable = "aws:SourceIp"
      values   = local.bedrock_allowed_source_ips
    }
  }

  dynamic "statement" {
    for_each = length(local.bedrock_profile_arns) > 0 ? [1] : []

    content {
      sid       = "ThroughTheProfilesOnly"
      actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      resources = local.bedrock_routed_model_arns

      condition {
        test     = "StringLike"
        variable = "bedrock:InferenceProfileArn"
        values   = local.bedrock_profile_arns
      }
    }
  }
}

resource "aws_iam_role_policy" "bedrock" {
  count = length(local.bedrock_models) > 0 ? 1 : 0

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
