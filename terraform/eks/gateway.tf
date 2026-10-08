# Private networking is only for the gateway ENIs and NLB; nodes retain public
# outbound connectivity. No NAT or Kubernetes load balancer controller required.
resource "aws_subnet" "gateway" {
  count             = 2
  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 2)
  availability_zone = var.availability_zones[count.index]
  tags              = { Name = "${var.cluster_name}-gateway-${count.index}" }
}

resource "aws_security_group" "vpc_link" {
  name_prefix = "${var.cluster_name}-vpc-link-"
  description = "API Gateway VPC link ENIs"
  vpc_id      = aws_vpc.this.id
}
resource "aws_security_group" "nlb" {
  name_prefix = "${var.cluster_name}-nlb-"
  description = "Private NLB accessible only through the VPC link"
  vpc_id      = aws_vpc.this.id
}
resource "aws_vpc_security_group_egress_rule" "link_to_nlb" {
  security_group_id            = aws_security_group.vpc_link.id
  referenced_security_group_id = aws_security_group.nlb.id
  ip_protocol                  = "tcp"
  from_port                    = 80
  to_port                      = 80
}
resource "aws_vpc_security_group_ingress_rule" "nlb_from_link" {
  security_group_id            = aws_security_group.nlb.id
  referenced_security_group_id = aws_security_group.vpc_link.id
  ip_protocol                  = "tcp"
  from_port                    = 80
  to_port                      = 80
}
resource "aws_vpc_security_group_egress_rule" "nlb_to_nodes" {
  security_group_id            = aws_security_group.nlb.id
  referenced_security_group_id = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 30080
  to_port                      = 30080
}
resource "aws_vpc_security_group_ingress_rule" "nodes_from_nlb" {
  security_group_id            = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  referenced_security_group_id = aws_security_group.nlb.id
  ip_protocol                  = "tcp"
  from_port                    = 30080
  to_port                      = 30080
}
resource "aws_lb" "edge" {
  internal                         = true
  load_balancer_type               = "network"
  subnets                          = aws_subnet.gateway[*].id
  security_groups                  = [aws_security_group.nlb.id]
  enable_cross_zone_load_balancing = true
}
resource "aws_lb_target_group" "edge" {
  port        = 30080
  protocol    = "TCP"
  target_type = "instance"
  vpc_id      = aws_vpc.this.id
  health_check {
    protocol = "HTTP"
    port     = "traffic-port"
    path     = "/edge-health"
    matcher  = "200"
  }
}
resource "aws_lb_listener" "edge" {
  load_balancer_arn = aws_lb.edge.arn
  port              = 80
  protocol          = "TCP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.edge.arn
  }
}
# ASG attachment automatically registers replacement nodes; never record EC2 IDs
# or transient Pod IPs. NodePort 30080 is fixed in the edge GitOps Service.
resource "aws_autoscaling_attachment" "edge" {
  autoscaling_group_name = aws_eks_node_group.arm.resources[0].autoscaling_groups[0].name
  lb_target_group_arn    = aws_lb_target_group.edge.arn
}
resource "aws_apigatewayv2_vpc_link" "edge" {
  name               = "${var.cluster_name}-edge"
  subnet_ids         = aws_subnet.gateway[*].id
  security_group_ids = [aws_security_group.vpc_link.id]
}
resource "aws_apigatewayv2_api" "edge" {
  name          = "${var.cluster_name}-api"
  protocol_type = "HTTP"
  cors_configuration {
    # All browser HTTP(S) origins, including localhost. Scheme wildcards permit
    # credentialed cookie requests; a literal '*' would not work in browsers.
    allow_origins     = ["http://*", "https://*"]
    allow_credentials = true
    allow_methods     = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    allow_headers     = ["authorization", "content-type", "accept", "x-requested-with", "x-csrf-token"]
    max_age           = 300
  }
}
resource "aws_apigatewayv2_integration" "edge" {
  api_id                 = aws_apigatewayv2_api.edge.id
  integration_type       = "HTTP_PROXY"
  integration_method     = "ANY"
  connection_type        = "VPC_LINK"
  connection_id          = aws_apigatewayv2_vpc_link.edge.id
  integration_uri        = aws_lb_listener.edge.arn
  payload_format_version = "1.0"
  timeout_milliseconds   = 30000
  request_parameters     = { "overwrite:path" = "$request.path" }
}
resource "aws_apigatewayv2_route" "edge" {
  for_each           = toset(["ANY /api", "ANY /api/{proxy+}", "ANY /auth", "ANY /auth/{proxy+}"])
  api_id             = aws_apigatewayv2_api.edge.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.edge.id}"
  authorization_type = "NONE" # Authentication remains inside Auth/Core.
}
resource "aws_apigatewayv2_stage" "edge" {
  api_id      = aws_apigatewayv2_api.edge.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 100
    throttling_rate_limit  = 50
  }
}
