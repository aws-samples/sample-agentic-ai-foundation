data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  image_src_path = "${path.module}/.."
  image_src_hash = sha512(
    join(
      "",
      # TODO: Find a way to exclude .venv, dist, and potentially other subfolders:
      [for f in fileset(".", "${local.image_src_path}/**") : filesha512(f)]
    )
  )

  image_build_extra_args = "--platform linux/arm64"
  image_build_push_cmd = <<-EOT
    aws ecr get-login-password | finch login --username AWS \
      --password-stdin ${aws_ecr_repository.ecr_repository.repository_url} &&

    finch build ${local.image_build_extra_args} \
      -t ${aws_ecr_repository.ecr_repository.repository_url}:${var.image_tag} \
      ${local.image_src_path} &&

    finch push ${aws_ecr_repository.ecr_repository.repository_url}:${var.image_tag}
  EOT
}

resource "aws_ecr_repository" "ecr_repository" {
  name = var.agent_name
}

resource "terraform_data" "ecr_image" {
  triggers_replace = [
    aws_ecr_repository.ecr_repository.id,
    var.force_image_rebuild == true ? timestamp() : local.image_src_hash
  ]

  input = "${aws_ecr_repository.ecr_repository.repository_url}:${var.image_tag}"

  provisioner "local-exec" {
    command = local.image_build_push_cmd
  }
}

resource "aws_iam_role" "execution_role" {
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AssumeRolePolicy"
        Effect = "Allow"
        Principal = {
          Service = "bedrock-agentcore.amazonaws.com"
        }
        Action = "sts:AssumeRole"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
          ArnLike = {
            "aws:SourceArn" = "arn:aws:bedrock-agentcore:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
          }
        }
      }
    ]
  })
}
