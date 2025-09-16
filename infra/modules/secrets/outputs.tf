output "cognito_client_secret_arn" {
  description = "ARN of the Cognito client secret"
  value       = aws_secretsmanager_secret.cognito_client_secret.arn
}

output "zendesk_credentials_arn" {
  description = "ARN of the Zendesk credentials secret"
  value       = aws_secretsmanager_secret.zendesk_credentials.arn
}

output "langfuse_credentials_arn" {
  description = "ARN of the Langfuse credentials secret"
  value       = aws_secretsmanager_secret.langfuse_credentials.arn
}

output "gateway_credentials_arn" {
  description = "ARN of the gateway credentials secret"
  value       = aws_secretsmanager_secret.gateway_credentials.arn
}

output "tavily_key_arn" {
  description = "ARN of the Tavily API key secret"
  value       = aws_secretsmanager_secret.tavily_key.arn
}