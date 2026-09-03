variable "region" {
  type    = string
  default = "eu-west-1"
}

resource "aws_subnet" "a" {
  cidr_block = "${var.region}"
}
