resource "aws_ssm_parameter" "kb_id" {
  name  = "/amazon/kb_id"
  type  = "String"
  value = var.knowledge_base_id
}

resource "aws_ssm_parameter" "ac_stm_memory_id" {
  name  = "/amazon/ac_stm_memory_id"
  type  = "String"
  value = var.ac_stm_memory_id
}

resource "aws_ssm_parameter" "guardrail_id" {
  name  = "/amazon/guardrail_id"
  type  = "String"
  value = var.guardrail_id
}

resource "aws_ssm_parameter" "user_pool_id" {
  name  = "/cognito/user_pool_id"
  type  = "String"
  value = var.user_pool_id
}

resource "aws_ssm_parameter" "client_id" {
  name  = "/cognito/client_id"
  type  = "String"
  value = var.client_id
}