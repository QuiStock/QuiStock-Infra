mock_provider "aws" {}

variables {
  account_id         = "123456789012"
  kubernetes_version = "1.34"
  cluster_role_arn   = "arn:aws:iam::123456789012:role/LabRole"
  node_role_arn      = "arn:aws:iam::123456789012:role/LabRole"
  admin_role_arn     = "arn:aws:iam::123456789012:role/OperatorRole"
  admin_cidrs        = ["203.0.113.10/32"]
  availability_zones = ["us-east-1a", "us-east-1b"]
  addon_versions = {
    vpc_cni    = "v1.19.0-eksbuild.1"
    coredns    = "v1.11.4-eksbuild.1"
    kube_proxy = "v1.34.0-eksbuild.1"
  }
}

run "private_gateway_contract" {
  command = plan
  assert {
    condition     = aws_lb.edge.internal && aws_lb.edge.load_balancer_type == "network"
    error_message = "The backend must stay behind a private NLB."
  }
  assert {
    condition     = aws_lb_target_group.edge.port == 30080 && aws_lb_target_group.edge.target_type == "instance"
    error_message = "Target port must match the GitOps NodePort and register nodes."
  }
  assert {
    condition     = aws_apigatewayv2_integration.edge.connection_type == "VPC_LINK" && aws_apigatewayv2_integration.edge.request_parameters["overwrite:path"] == "$request.path"
    error_message = "Integration must use the VPC link without injecting a stage prefix."
  }
  assert {
    condition     = length(aws_apigatewayv2_route.edge) == 4 && alltrue([for r in aws_apigatewayv2_route.edge : r.authorization_type == "NONE"])
    error_message = "Both base and nested paths must preserve application-owned authentication."
  }
  assert {
    condition     = aws_apigatewayv2_api.edge.cors_configuration[0].allow_credentials && contains(aws_apigatewayv2_api.edge.cors_configuration[0].allow_origins, "http://*") && contains(aws_apigatewayv2_api.edge.cors_configuration[0].allow_origins, "https://*") && contains(aws_apigatewayv2_api.edge.cors_configuration[0].allow_headers, "authorization")
    error_message = "Open browser origins must support cookie credentials and bearer headers."
  }
}
