variable "role_name" {
  description = "Name of the IAM role"
  type        = string
}

variable "knowledge_base_id" {
  description = "Knowledge Base ID to restrict access to"
  type        = string
  default     = "*"
}

variable "guardrail_id" {
  description = "Guardrail ID to restrict access to"
  type        = string
  default     = "*"
}