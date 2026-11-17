# Terraform Provisioning Module for Autonomous SRE Agent Platform

# VPC configuration and infrastructure subnets
resource "aws_vpc" "sre_vpc" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags = {
    Name = "sre-agent-vpc"
  }
}

resource "aws_subnet" "private_subnet" {
  count             = 2
  vpc_id            = aws_vpc.sre_vpc.id
  cidr_block        = cidrsubnet(aws_vpc.sre_vpc.cidr_block, 8, count.index)
  availability_zone = data.aws_availability_zones.available.names[count.index]
  tags = {
    Name = "sre-agent-private-${count.index}"
  }
}

# Aurora Serverless v2 PostgreSQL DB Checkpointer
resource "aws_rds_cluster" "checkpointer_db" {
  cluster_identifier      = "sre-checkpointer-db"
  engine                  = "aurora-postgresql"
  engine_mode             = "provisioned"
  engine_version          = "15.4"
  database_name           = "sre_state_db"
  master_username         = var.db_user
  master_password         = var.db_password
  vpc_security_group_ids  = [aws_security_group.db_sg.id]
  db_subnet_group_name    = aws_db_subnet_group.db_subnet_grp.name
  skip_final_snapshot     = true
}

resource "aws_rds_cluster_instance" "db_instances" {
  count              = 1
  identifier         = "sre-checkpointer-db-instance"
  cluster_identifier = aws_rds_cluster.checkpointer_db.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.checkpointer_db.engine
  engine_version     = aws_rds_cluster.checkpointer_db.engine_version
}

# ECS Fargate Service to execute LangGraph Agent Tasks
resource "aws_ecs_cluster" "agent_ecs" {
  name = "sre-agent-ecs-cluster"
}

resource "aws_ecs_task_definition" "agent_task" {
  family                   = "sre-agent-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.agent_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "sre-agent-app"
      image     = var.agent_image_uri
      essential = true
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
        }
      ]
      environment = [
        { name = "DB_URI", value = "postgresql://${var.db_user}:${var.db_password}@${aws_rds_cluster.checkpointer_db.endpoint}:5432/sre_state_db" }
      ]
    }
  ])
}

# IAM Role with Minimum Privileges for Kubernetes/EKS administration
resource "aws_iam_role" "agent_task_role" {
  name = "sre-agent-task-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_policy" "agent_k8s_access" {
  name = "sre-agent-k8s-minimum-privileges"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "eks:DescribeCluster",
          "eks:ListClusters"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "agent_policy_attach" {
  role       = aws_iam_role.agent_task_role.name
  policy_arn = aws_iam_policy.agent_k8s_access.arn
}

# Boilerplate items for supporting resources
resource "aws_security_group" "db_sg" {
  name   = "sre-db-sg"
  vpc_id = aws_vpc.sre_vpc.id
  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.sre_vpc.cidr_block]
  }
}

resource "aws_db_subnet_group" "db_subnet_grp" {
  name       = "sre-db-subnet-group"
  subnet_ids = aws_subnet.private_subnet[*].id
}

resource "aws_iam_role" "ecs_execution_role" {
  name = "sre-ecs-execution-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

data "aws_availability_zones" "available" {
  state = "available"
}
