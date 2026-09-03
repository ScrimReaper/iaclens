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

resource "aws_instance" "web" {
  count = 2
  ami   = "ami-123"
}

resource "aws_s3_bucket" "b" {
  for_each = toset(["a", "b"])
  bucket   = "bucket-name"
}
