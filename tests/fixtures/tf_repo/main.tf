variable "region" {
  type    = string
  default = "us-east-1"
}

module "net" {
  source = "./modules/net"
  region = var.region
}

resource "aws_eip" "x" {
  subnet_id = "${module.net.subnet_id}"
}
