output "cluster_name" {
  value = aws_eks_cluster.this.name
}
output "region" {
  value = var.region
}
output "get_credentials_command" {
  value = "aws eks update-kubeconfig --name ${var.cluster_name} --region ${var.region}"
}
