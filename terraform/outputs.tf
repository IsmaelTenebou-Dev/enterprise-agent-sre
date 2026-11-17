output "vpc_id" {
  value       = aws_vpc.sre_vpc.id
  description = "Target VPC identifier"
}

output "db_endpoint" {
  value       = aws_rds_cluster.checkpointer_db.endpoint
  description = "Security endpoints connectivity address for checking Aurora checkpointer state DB"
}

output "ecs_cluster_name" {
  value       = aws_ecs_cluster.agent_ecs.name
  description = "Elastic Container Service cluster name"
}
