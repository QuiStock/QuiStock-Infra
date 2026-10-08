mock_provider "aws" {}

variables {
  account_id         = "123456789012"
  kubernetes_version = "1.34"
  cluster_role_arn   = "arn:aws:iam::123456789012:role/LabRole"
  node_role_arn      = "arn:aws:iam::123456789012:role/LabRole"
  admin_role_arn     = "arn:aws:iam::123456789012:role/OperatorRole"
  admin_cidrs        = ["0.0.0.0/0"]
  availability_zones = ["us-east-1a", "us-east-1b"]
  addon_versions = {
    vpc_cni    = "v1.19.0-eksbuild.1"
    coredns    = "v1.11.4-eksbuild.1"
    kube_proxy = "v1.34.0-eksbuild.1"
  }
}

run "argocd_public_https_contract" {
  command = plan
  override_resource {
    target          = aws_lb.argocd
    override_during = plan
    values          = { arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/argocd/0123456789abcdef" }
  }
  override_resource {
    target          = aws_security_group.argocd_public
    override_during = plan
    values          = { id = "sg-0123456789abcdef0" }
  }
  assert {
    condition     = !aws_lb.argocd.internal && aws_lb.edge.internal && aws_lb_listener.argocd.load_balancer_arn == aws_lb.argocd.arn && aws_lb_listener.argocd.port == 443 && aws_lb_listener.argocd.protocol == "TCP" && aws_lb_listener.edge.port == 80
    error_message = "Public Argo CD must pass through HTTPS while API traffic stays on the private NLB."
  }
  assert {
    condition     = aws_lb_target_group.argocd.port == 30081 && aws_lb_target_group.argocd.health_check[0].protocol == "HTTPS" && aws_vpc_security_group_ingress_rule.argocd_nodes_from_nlb.referenced_security_group_id == aws_security_group.argocd_public.id
    error_message = "The existing target group must carry HTTPS, accessible only from the public NLB security group."
  }
  assert {
    condition     = aws_vpc_security_group_ingress_rule.argocd_public_https.cidr_ipv4 == "0.0.0.0/0" && aws_vpc_security_group_ingress_rule.argocd_public_https.from_port == 443 && aws_vpc_security_group_ingress_rule.argocd_public_https.to_port == 443
    error_message = "Public access is authorized only on port 443."
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
    condition     = length(aws_apigatewayv2_route.edge) == 5 && contains(keys(aws_apigatewayv2_route.edge), "$default") && alltrue([for r in aws_apigatewayv2_route.edge : r.authorization_type == "NONE"])
    error_message = "Website fallback and API paths must preserve application-owned authentication."
  }
  assert {
    condition     = aws_apigatewayv2_api.edge.cors_configuration[0].allow_credentials && contains(aws_apigatewayv2_api.edge.cors_configuration[0].allow_origins, "http://*") && contains(aws_apigatewayv2_api.edge.cors_configuration[0].allow_origins, "https://*") && contains(aws_apigatewayv2_api.edge.cors_configuration[0].allow_headers, "authorization")
    error_message = "Open browser origins must support cookie credentials and bearer headers."
  }
}
