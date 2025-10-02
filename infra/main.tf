# Bedrock Agent Role
module "bedrock_role" {
  source            = "./modules/agentcore-iam-role"
  role_name         = var.bedrock_role_name
  knowledge_base_id = module.kb_stack.knowledge_base_id
  guardrail_id      = module.guardrail.guardrail_id
}

# Example Agent
module "cx_agent_demo" {
  source = "../cx-agent-backend/infra"
}

# Knowledge Base Stack
module "kb_stack" {
  source       = "./modules/kb-stack"
  name         = var.kb_stack_name
  kb_model_arn = var.kb_model_arn
}

# Guardrail Module
module "guardrail" {
  source                    = "./modules/bedrock-guardrails"
  guardrail_name            = "agentic-ai-guardrail"
  blocked_input_messaging   = "Your input contains content that violates our policy."
  blocked_outputs_messaging = "The response was blocked due to policy violations."
  description               = "Guardrail for agentic AI foundation"
}

# Cognito Module
module "cognito" {
  source         = "./modules/cognito"
  user_pool_name = var.user_pool_name
}

# Parameters Module (depends on KB, Guardrail, and Cognito)
module "parameters" {
  source            = "./modules/parameters"
  knowledge_base_id = module.kb_stack.knowledge_base_id
  guardrail_id      = module.guardrail.guardrail_id
  user_pool_id      = module.cognito.user_pool_id
  client_id         = module.cognito.user_pool_client_id

  depends_on = [
    module.kb_stack,
    module.guardrail,
    module.cognito
  ]
}

# Secrets Module (depends on Cognito for client secret)
module "secrets" {
  source = "./modules/secrets"

  cognito_client_secret = module.cognito.client_secret

  # Placeholder values - replace with actual values
  zendesk_domain      = var.zendesk_domain
  zendesk_email       = var.zendesk_email
  zendesk_api_token   = var.zendesk_api_token
  langfuse_host       = var.langfuse_host
  langfuse_public_key = var.langfuse_public_key
  langfuse_secret_key = var.langfuse_secret_key
  gateway_url         = var.gateway_url
  gateway_api_key     = var.gateway_api_key
  tavily_api_key      = var.tavily_api_key

  depends_on = [module.cognito]
}

