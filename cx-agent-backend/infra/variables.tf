variable "agent_name" {
  description = "Unique name of the agent"
  default     = "cx_agent_backend"
  type        = string
  validation {
    condition     = can(regex("^[a-zA-Z0-9_]+$", var.agent_name))
    error_message = "Agent name must contain only letters, numbers, and underscores."
  }
}

variable "force_image_rebuild" {
  description = "Set true to force rebuild & push of image to ECR even if source appears unchanged"
  default     = false
  type        = bool
}

variable "image_tag" {
  description = "Tag to apply to the pushed container image in Amazon ECR"
  default     = "latest"
  type        = string
}
