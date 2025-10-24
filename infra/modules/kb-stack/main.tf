# S3 Bucket for Knowledge Base
resource "aws_s3_bucket" "kb_bucket" {
  bucket_prefix = var.name
}

resource "aws_s3_bucket_public_access_block" "kb_bucket_pab" {
  bucket = aws_s3_bucket.kb_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Access logging bucket
resource "aws_s3_bucket" "access_logs" {
  bucket_prefix = "${var.name}-access-logs"
}

resource "aws_s3_bucket_public_access_block" "access_logs_pab" {
  bucket = aws_s3_bucket.access_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Enable access logging
resource "aws_s3_bucket_logging" "kb_bucket_logging" {
  bucket = aws_s3_bucket.kb_bucket.id

  target_bucket = aws_s3_bucket.access_logs.id
  target_prefix = "access-logs/"
}

# Lifecycle configuration
resource "aws_s3_bucket_lifecycle_configuration" "kb_bucket_lifecycle" {
  bucket = aws_s3_bucket.kb_bucket.id

  rule {
    id     = "knowledge_base_lifecycle"
    status = "Enabled"

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 90
      storage_class = "GLACIER"
    }
  }
}

# IAM Role for Bedrock
resource "aws_iam_role" "bedrock_role" {
  name = "${var.name}-bedrock-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "bedrock.amazonaws.com"
        }
      }
    ]
  })
}

module "opensearch" {
  source = "../opensearch-serverless"
  
  collection_name = "${var.name}"
  additional_principals = [aws_iam_role.bedrock_role.arn]
}

module "knowledge_base" {
  source = "../knowledge-base"
  
  kb_name             = var.name
  bedrock_role_name   = aws_iam_role.bedrock_role.name
  bedrock_role_arn    = aws_iam_role.bedrock_role.arn
  opensearch_arn      = module.opensearch.collection_arn
  opensearch_index_name = "os-vector-index-${var.name}"
  kb_model_arn        = var.kb_model_arn
  s3_arn              = aws_s3_bucket.kb_bucket.arn
}