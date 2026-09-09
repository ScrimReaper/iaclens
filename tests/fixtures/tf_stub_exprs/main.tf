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

module "net" {
  source = "./net"
}

locals {
  n      = 2
  label  = format("%s-web", var.name)
  count2 = local.n + 1
  joined = join(",", [aws_instance.web.id, var.name])
  whole  = module.net
}
