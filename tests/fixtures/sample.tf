variable "region" {
  description = "AWS region"
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment"
  default     = "production"
}

provider "aws" {
  region = var.region
}

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true

  tags = {
    Name        = "main-vpc"
    Environment = var.environment
  }
}

resource "aws_subnet" "public" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = "${var.region}a"

  depends_on = [aws_vpc.main]

  tags = {
    Name = "public-subnet"
  }
}

resource "aws_instance" "web_server" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = "t3.micro"
  subnet_id     = aws_subnet.public.id

  depends_on = [aws_subnet.public]

  tags = {
    Name        = "web-server"
    Environment = var.environment
  }
}

data "aws_ami" "ubuntu" {
  most_recent = true

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-*-22.04-amd64-server-*"]
  }

  owners = ["099720109477"]
}

output "vpc_id" {
  value       = aws_vpc.main.id
  description = "The ID of the main VPC"
}

output "web_server_ip" {
  value       = aws_instance.web_server.public_ip
  description = "Public IP of the web server"
}

locals {
  common_tags = {
    ManagedBy   = "terraform"
    Environment = var.environment
  }
}
