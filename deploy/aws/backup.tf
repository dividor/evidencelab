# Scheduled backups, with AWS Backup, of what a deploy can't recreate quickly:
# the Postgres database, the documents and page images on EFS, and Qdrant's
# instance with the index on its disk (when Qdrant runs on EC2). Weekly and
# kept for 35 days unless the settings say otherwise; backups_enabled = false
# turns them off.
#
# The vault belongs to the deployment: removing the deployment deletes it and
# its backups. RDS's final snapshot (unless db_skip_final_snapshot) is kept.

locals {
  backup_resources = concat(
    [aws_db_instance.main.arn, aws_efs_file_system.data.arn],
    aws_instance.qdrant[*].arn,
  )
}

resource "aws_backup_vault" "main" {
  count         = var.backups_enabled ? 1 : 0
  name          = var.name
  force_destroy = true
}

resource "aws_backup_plan" "main" {
  count = var.backups_enabled ? 1 : 0
  name  = var.name

  rule {
    rule_name         = "scheduled"
    target_vault_name = aws_backup_vault.main[0].name
    schedule          = var.backup_schedule

    lifecycle {
      delete_after = var.backup_retention_days
    }
  }
}

data "aws_iam_policy_document" "backup_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["backup.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "backup" {
  count              = var.backups_enabled ? 1 : 0
  name               = "${var.name}-backup"
  assume_role_policy = data.aws_iam_policy_document.backup_assume.json
}

resource "aws_iam_role_policy_attachment" "backup" {
  for_each = var.backups_enabled ? toset([
    "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup",
    "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForRestores",
  ]) : toset([])
  role       = aws_iam_role.backup[0].name
  policy_arn = each.value
}

resource "aws_backup_selection" "main" {
  count        = var.backups_enabled ? 1 : 0
  name         = var.name
  plan_id      = aws_backup_plan.main[0].id
  iam_role_arn = aws_iam_role.backup[0].arn
  resources    = local.backup_resources
}
