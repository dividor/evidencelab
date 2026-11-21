# Moving existing data in: you upload a Postgres export and an archive of the
# data folder to the transfer bucket, then scripts/restore-data.sh runs the
# restore task, which loads them into RDS and EFS from inside the VPC.
#
# A database export holds users' password hashes and sign-in tokens, so only
# the restore task can read the bucket: it runs as its own role, not the task
# role the api, mcp, migrate and pipeline containers share. Uploads are deleted
# after transfer_retention_days.

resource "aws_s3_bucket" "transfer" {
  bucket_prefix = "${var.name}-transfer-"
  # Teardown deletes what is left in it.
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "transfer" {
  bucket                  = aws_s3_bucket.transfer.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "transfer" {
  bucket = aws_s3_bucket.transfer.id

  rule {
    id     = "delete-uploads"
    status = "Enabled"
    filter {}

    expiration {
      days = var.transfer_retention_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# Every request must use HTTPS.
data "aws_iam_policy_document" "transfer_bucket" {
  statement {
    sid       = "HttpsOnly"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.transfer.arn, "${aws_s3_bucket.transfer.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "transfer" {
  bucket = aws_s3_bucket.transfer.id
  policy = data.aws_iam_policy_document.transfer_bucket.json
  # The public access block must exist first, or AWS may refuse the policy.
  depends_on = [aws_s3_bucket_public_access_block.transfer]
}

# The restore task's own role: read the transfer bucket, and write only under
# dumps/ (scripts/dump-data.sh), nothing else. Its database password, Qdrant
# key and app keys come through the execution role, like every other task's.
resource "aws_iam_role" "restore" {
  name               = "${var.name}-ecs-restore"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "restore" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.transfer.arn]
  }
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.transfer.arn}/*"]
  }
  statement {
    actions   = ["s3:PutObject", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.transfer.arn}/dumps/*"]
  }
}

resource "aws_iam_role_policy" "restore" {
  name   = "transfer-bucket"
  role   = aws_iam_role.restore.id
  policy = data.aws_iam_policy_document.restore.json
}
