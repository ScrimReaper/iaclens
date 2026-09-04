variable "name" {
  type = string
}

resource "aws_instance" "web" {
  ami       = "ami-123"
  user_data = templatefile("${path.module}/init.tpl", { name = var.name })

  tags = {
    Name = var.name
  }
}

locals {
  ids = [for m in aws_instance.web : m.id]
  dir = path.module
}
