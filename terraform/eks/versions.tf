terraform {
  required_version = ">= 1.11.4, < 2.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.21.0"
    }
  }
  backend "s3" {}
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id]
  default_tags {
    tags = { app = "quistock", environment = "learner-lab", managed_by = "terraform" }
  }
}
