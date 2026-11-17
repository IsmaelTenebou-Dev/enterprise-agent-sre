variable "vpc_cidr" {
  type        = string
  default     = "10.0.0.0/16"
  description = "CIDR block for the target VPC"
}

variable "db_user" {
  type        = string
  default     = "sre_user"
  description = "Aurora Serverless checkpointer DB owner username"
}

variable "db_password" {
  type        = string
  default     = "SuperSecurePassword123!"
  sensitive   = true
  description = "Aurora Serverless checkpointer DB owner password"
}

variable "agent_image_uri" {
  type        = string
  default     = "123456789012.dkr.ecr.us-east-1.amazonaws.com/sre-agent:latest"
  description = "Docker image URI representing the SRE LangGraph checkpointer service"
}
