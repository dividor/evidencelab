# Optional: a folder of your own pipeline files, such as a data source's
# downloader script and the spreadsheet it reads. They are copied into the
# pipeline task at /app/custom before the pipeline starts, so a data source's
# download command can name /app/custom/<file>. They travel through a private
# S3 bucket: the task's own settings hold far too little for them.

locals {
  pipeline_files_enabled = var.pipeline_files_dir != ""
  pipeline_files = local.pipeline_files_enabled ? {
    for f in fileset(var.pipeline_files_dir, "**") : f => "${var.pipeline_files_dir}/${f}"
  } : {}

  # Copies every file under files/ in the bucket to /app/custom, keeping
  # sub-folders, and stops the task if there are none.
  fetch_pipeline_files = <<-EOT
    python - <<'PY'
    import os
    import boto3
    bucket = os.environ["PIPELINE_FILES_BUCKET"]
    s3 = boto3.client("s3")
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="files/")
    keys = [o["Key"] for page in pages for o in page.get("Contents", [])]
    if not keys:
        raise SystemExit(f"No pipeline files in s3://{bucket}/files/")
    for key in keys:
        path = os.path.join("/app/custom", key[len("files/"):])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        s3.download_file(bucket, key, path)
    print(f"Copied {len(keys)} pipeline files to /app/custom")
    PY
  EOT
}

resource "aws_s3_bucket" "pipeline_files" {
  count         = local.pipeline_files_enabled ? 1 : 0
  bucket_prefix = "${var.name}-pipeline-files-"
  # Teardown deletes the files with the bucket.
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "pipeline_files" {
  count                   = local.pipeline_files_enabled ? 1 : 0
  bucket                  = aws_s3_bucket.pipeline_files[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_object" "pipeline_files" {
  for_each = local.pipeline_files
  bucket   = aws_s3_bucket.pipeline_files[0].id
  key      = "files/${each.key}"
  source   = each.value
  # Uploaded again whenever the file changes.
  source_hash = filemd5(each.value)
}

# Read-only, and only the files/ prefix. The api, mcp and migrate containers
# share the task role, so they could read these files too; they hold no
# secrets.
data "aws_iam_policy_document" "pipeline_files" {
  count = local.pipeline_files_enabled ? 1 : 0

  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.pipeline_files[0].arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["files/*"]
    }
  }
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.pipeline_files[0].arn}/files/*"]
  }
}

resource "aws_iam_role_policy" "pipeline_files" {
  count  = local.pipeline_files_enabled ? 1 : 0
  name   = "read-pipeline-files"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.pipeline_files[0].json
}
