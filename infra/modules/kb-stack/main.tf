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