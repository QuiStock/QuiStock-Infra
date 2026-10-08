mock_provider "aws" {
  mock_data "aws_availability_zone" {
    defaults = { zone_id = "use1-az1" }
  }
}

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

run "argocd_private_origin_contract" {
  command = plan
  override_resource {
    target          = aws_lb.edge
    override_during = plan
    values          = { arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/edge/0123456789abcdef" }
  }
  override_resource {
    target          = aws_security_group.nlb
    override_during = plan
    values          = { id = "sg-0123456789abcdef0" }
  }
  override_resource {
    target          = aws_cloudfront_vpc_origin.argocd
    override_during = plan
    values          = { id = "vo_fixture" }
  }
  assert {
    condition     = aws_lb.edge.internal && aws_lb_listener.argocd.load_balancer_arn == aws_lb.edge.arn && aws_lb_listener.argocd.port == 81 && aws_lb_listener.edge.port == 80
    error_message = "Argo CD must reuse the private NLB on a separate listener without changing the API listener."
  }
  assert {
    condition     = aws_lb_target_group.argocd.port == 30081 && aws_vpc_security_group_ingress_rule.argocd_nodes_from_nlb.referenced_security_group_id == aws_security_group.nlb.id
    error_message = "Only the NLB may reach the Argo CD NodePort."
  }
  assert {
    condition     = aws_cloudfront_distribution.argocd.default_cache_behavior[0].viewer_protocol_policy == "https-only" && aws_cloudfront_distribution.argocd.default_cache_behavior[0].cache_policy_id == data.aws_cloudfront_cache_policy.argocd.id && data.aws_cloudfront_cache_policy.argocd.name == "Managed-CachingDisabled"
    error_message = "Public access must use HTTPS and disable caching of authenticated responses."
  }
  assert {
    condition     = one(aws_cloudfront_distribution.argocd.origin).vpc_origin_config[0].vpc_origin_id == aws_cloudfront_vpc_origin.argocd.id && data.aws_cloudfront_origin_request_policy.argocd.name == "Managed-AllViewerExceptHostHeader"
    error_message = "CloudFront must use a private origin and forward cookies, query strings and Authorization."
  }
}

run "unsupported_origin_zone_is_rejected" {
  command = plan
  override_data {
    target = data.aws_availability_zone.argocd["us-east-1a"]
    values = { zone_id = "use1-az3" }
  }
  expect_failures = [aws_cloudfront_vpc_origin.argocd]
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
