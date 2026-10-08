output "cluster_name" {
  value = aws_eks_cluster.this.name
}
output "region" {
  value = var.region
}
output "get_credentials_command" {
  value = "aws eks update-kubeconfig --name ${var.cluster_name} --region ${var.region}"
}
output "api_url" {
  value = aws_apigatewayv2_api.edge.api_endpoint
}
output "core_url" {
  value = "${aws_apigatewayv2_api.edge.api_endpoint}/api"
}
output "auth_url" {
  value = "${aws_apigatewayv2_api.edge.api_endpoint}/auth"
}
output "edge_target_group_arn" {
  value = aws_lb_target_group.edge.arn
}
output "argocd_url" {
  value = "https://${aws_lb.argocd.dns_name}"
}
output "argocd_target_group_arn" {
  value = aws_lb_target_group.argocd.arn
}
