# Agent Container Image
module "container_image" {
  source = "./modules/container-image"

  force_image_rebuild = var.force_image_rebuild
  image_build_tool    = var.container_image_build_tool
  repository_name     = "langgraph-cx-agent"
}

# Agent Memory
resource "aws_bedrockagentcore_memory" "agent_memory" {
  name                  = "CxMemory"
  event_expiry_duration = 30
}

# Bedrock Agent Role
module "bedrock_role" {
  source                   = "./modules/agentcore-iam-role"
  agent_memory_arn         = aws_bedrockagentcore_memory.agent_memory.arn
  container_repository_arn = module.container_image.ecr_repository_arn
  role_name                = var.bedrock_role_name
  knowledge_base_id        = module.kb_stack.knowledge_base_id
  guardrail_id             = module.guardrail.guardrail_id
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
  ac_stm_memory_id  = aws_bedrockagentcore_memory.agent_memory.id

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

# Deploy the endpoint
resource "aws_bedrockagentcore_agent_runtime" "agent_runtime" {
  agent_runtime_name = "langgraph_cx_agent"
  description        = "Example customer service agent for Agentic AI Foundation"
  role_arn           = module.bedrock_role.role_arn
  authorizer_configuration {
    custom_jwt_authorizer {
      discovery_url   = module.cognito.user_pool_discovery_url
      allowed_clients = [module.cognito.user_pool_client_id]
    }
  }
  agent_runtime_artifact {
    container_configuration {
      container_uri = module.container_image.ecr_image_uri
    }
  }
  network_configuration {
    network_mode = "PUBLIC"
  }
  protocol_configuration {
    server_protocol = "HTTP"
  }
  environment_variables = {
    "LOG_LEVEL" = "INFO"
    "OTEL_EXPORTER_OTLP_ENDPOINT" = "${var.langfuse_host}/api/public/otel"
    "OTEL_EXPORTER_OTLP_HEADERS" = "Authorization=Basic ${base64encode("${var.langfuse_public_key}:${var.langfuse_secret_key}")}"
    "DISABLE_ADOT_OBSERVABILITY" = "true",
    "LANGSMITH_OTEL_ENABLED" = "true",
    "LANGSMITH_TRACING" = "true"

  }

}
