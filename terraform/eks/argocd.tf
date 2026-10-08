# Public HTTPS passes through TCP to Argo CD's own certificate. No CloudFront,
# ACM, custom domain or Kubernetes load balancer controller is required.
resource "aws_security_group" "argocd_public" {
  name_prefix = "${var.cluster_name}-argocd-"
  description = "Public Argo CD HTTPS; authentication remains mandatory"
  vpc_id      = aws_vpc.this.id
}
resource "aws_vpc_security_group_ingress_rule" "argocd_public_https" {
  security_group_id = aws_security_group.argocd_public.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}
resource "aws_vpc_security_group_egress_rule" "argocd_to_nodes" {
  security_group_id            = aws_security_group.argocd_public.id
  referenced_security_group_id = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 30081
  to_port                      = 30081
}
resource "aws_vpc_security_group_ingress_rule" "argocd_nodes_from_nlb" {
  security_group_id            = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  referenced_security_group_id = aws_security_group.argocd_public.id
  ip_protocol                  = "tcp"
  from_port                    = 30081
  to_port                      = 30081
}
resource "aws_lb" "argocd" {
  internal                         = false
  load_balancer_type               = "network"
  ip_address_type                  = "ipv4"
  subnets                          = aws_subnet.public[*].id
  security_groups                  = [aws_security_group.argocd_public.id]
  enable_cross_zone_load_balancing = true
  depends_on                       = [aws_route_table_association.public]
}
# Keep the existing target group/ASG attachment from the interrupted migration.
# Port 30081 now carries HTTPS; changing health protocol does not replace it.
resource "aws_lb_target_group" "argocd" {
  port        = 30081
  protocol    = "TCP"
  target_type = "instance"
  vpc_id      = aws_vpc.this.id
  health_check {
    protocol = "HTTPS"
    port     = "traffic-port"
    path     = "/healthz"
    matcher  = "200"
  }
}
resource "aws_lb_listener" "argocd" {
  load_balancer_arn = aws_lb.argocd.arn
  port              = 443
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
