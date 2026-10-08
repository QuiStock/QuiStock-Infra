# Separate listener on the existing private NLB: no additional load balancer,
# public origin, custom domain, ACM certificate or Kubernetes controller.
data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}
data "aws_availability_zone" "argocd" {
  for_each = toset(var.availability_zones)
  name     = each.value
}
resource "aws_vpc_security_group_ingress_rule" "argocd_from_cloudfront" {
  security_group_id = aws_security_group.nlb.id
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront.id
  ip_protocol       = "tcp"
  from_port         = 81
  to_port           = 81
}
resource "aws_vpc_security_group_egress_rule" "argocd_to_nodes" {
  security_group_id            = aws_security_group.nlb.id
  referenced_security_group_id = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 30081
  to_port                      = 30081
}
resource "aws_vpc_security_group_ingress_rule" "argocd_nodes_from_nlb" {
  security_group_id            = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  referenced_security_group_id = aws_security_group.nlb.id
  ip_protocol                  = "tcp"
  from_port                    = 30081
  to_port                      = 30081
}
resource "aws_lb_target_group" "argocd" {
  port        = 30081
  protocol    = "TCP"
  target_type = "instance"
  vpc_id      = aws_vpc.this.id
  health_check {
    protocol = "HTTP"
    port     = "traffic-port"
    path     = "/healthz"
    matcher  = "200"
  }
}
resource "aws_lb_listener" "argocd" {
  load_balancer_arn = aws_lb.edge.arn
  port              = 81
  protocol          = "TCP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.argocd.arn
  }
}
resource "aws_autoscaling_attachment" "argocd" {
  autoscaling_group_name = aws_eks_node_group.arm.resources[0].autoscaling_groups[0].name
  lb_target_group_arn    = aws_lb_target_group.argocd.arn
}
resource "aws_cloudfront_vpc_origin" "argocd" {
  vpc_origin_endpoint_config {
    name                   = "${var.cluster_name}-argocd"
    arn                    = aws_lb.edge.arn
    http_port              = 81
    https_port             = 443
    origin_protocol_policy = "http-only" # HTTP stays inside the private VPC connection.
    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }
  lifecycle {
    precondition {
      condition     = var.region != "us-east-1" || alltrue([for az in data.aws_availability_zone.argocd : az.zone_id != "use1-az3"])
      error_message = "CloudFront VPC origins do not support use1-az3. Do not recreate the existing cluster; review its subnet placement first."
    }
  }
  depends_on = [aws_lb_listener.argocd, aws_vpc_security_group_ingress_rule.argocd_from_cloudfront, aws_internet_gateway.this]
}
data "aws_cloudfront_cache_policy" "argocd" {
  name = "Managed-CachingDisabled"
}
data "aws_cloudfront_origin_request_policy" "argocd" {
  name = "Managed-AllViewerExceptHostHeader"
}
resource "aws_cloudfront_distribution" "argocd" {
  enabled             = true
  wait_for_deployment = true
  comment             = "${var.cluster_name} Argo CD"
  price_class         = "PriceClass_100"
  is_ipv6_enabled     = true
  origin {
    domain_name = aws_lb.edge.dns_name
    origin_id   = "argocd"
    vpc_origin_config {
      vpc_origin_id            = aws_cloudfront_vpc_origin.argocd.id
      origin_keepalive_timeout = 5
      origin_read_timeout      = 60
    }
  }
  default_cache_behavior {
    target_origin_id         = "argocd"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.argocd.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.argocd.id
    compress                 = true
  }
  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }
  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
