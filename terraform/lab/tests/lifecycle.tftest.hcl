mock_provider "aws" {}
variables {
  account_id         = "123456789012"
  region             = "us-east-1"
  cluster_name       = "quistock"
  availability_zones = ["us-east-1a", "us-east-1b"]
  admin_cidrs        = ["192.0.2.1/32"]
  ami_id             = "ami-0123456789abcdef0"
  ssh_public_key     = "ssh-ed25519 test"
}
run "fresh_stateless_cluster" {
  command = plan
  assert {
    condition     = length(aws_instance.node) == 2 && length(aws_eks_cluster.this) == 0 && length(aws_eks_node_group.arm) == 0
    error_message = "A fresh lab must create a disposable pair without EKS or IAM roles."
  }
  assert {
    condition     = length(aws_lb_target_group_attachment.edge_node) == 2 && length(aws_lb_target_group_attachment.argocd_node) == 2
    error_message = "Both Kubernetes nodes must be registered in both target groups."
  }
  assert {
    condition     = alltrue([for node in aws_instance.node : node.root_block_device[0].encrypted && node.root_block_device[0].delete_on_termination && node.metadata_options[0].http_tokens == "required"])
    error_message = "Disposable nodes need encrypted volumes and IMDSv2."
  }
}
run "keep_urls_without_compute" {
  command = plan
  variables { compute_enabled = false }
  assert {
    condition     = length(aws_instance.node) == 0 && length(aws_lb_target_group_attachment.edge_node) == 0 && aws_lb.edge.internal && !aws_lb.argocd.internal
    error_message = "Keeping network must remove compute and keep both public entry points."
  }
}
