locals {
  nodes = var.compute_enabled ? var.node_subnet_indices : {}
}
resource "aws_security_group" "nodes" {
  name        = "${var.cluster_name}-k3s-recovery"
  description = "K3s recovery admin and node traffic"
  vpc_id      = aws_vpc.this.id
  dynamic "ingress" {
    for_each = toset([22, 6443])
    content {
      protocol    = "tcp"
      from_port   = ingress.value
      to_port     = ingress.value
      cidr_blocks = var.admin_cidrs
    }
  }
  dynamic "ingress" {
    for_each = { api = ["tcp", "6443"], kubelet = ["tcp", "10250"], flannel = ["udp", "8472"] }
    content {
      protocol  = ingress.value[0]
      from_port = tonumber(ingress.value[1])
      to_port   = tonumber(ingress.value[1])
      self      = true
    }
  }
  ingress {
    protocol        = "tcp"
    from_port       = 30080
    to_port         = 30080
    security_groups = [aws_security_group.nlb.id]
  }
  ingress {
    protocol        = "tcp"
    from_port       = 30081
    to_port         = 30081
    security_groups = [aws_security_group.argocd_public.id]
  }
  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_instance" "node" {
  for_each                    = local.nodes
  ami                         = var.ami_id
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public[each.value].id
  vpc_security_group_ids      = [aws_security_group.nodes.id]
  associate_public_ip_address = true
  user_data                   = "#cloud-config\n${jsonencode({ ssh_authorized_keys = [var.ssh_public_key], package_update = true, packages = ["curl", "iptables", "conntrack", "socat"] })}"
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }
  root_block_device {
    volume_size           = 30
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }
  tags = { Name = "${var.cluster_name}-k3s-${each.key}", Role = each.key }
  # Imported nodes already contain the same public key. Rebuild explicitly if
  # rotating it; do not stop a healthy imported node solely to rewrite user-data.
  lifecycle {
    # EC2 reports no public-IP association while stopped. Treating that as
    # drift would replace the pair at every End Lab instead of starting it.
    ignore_changes = [user_data, associate_public_ip_address]
  }
  depends_on = [aws_route_table_association.public, aws_eks_cluster.this]
}
resource "aws_lb_target_group_attachment" "edge_node" {
  for_each         = local.nodes
  target_group_arn = aws_lb_target_group.edge.arn
  target_id        = aws_instance.node[each.key].id
  port             = 30080
}
resource "aws_lb_target_group_attachment" "argocd_node" {
  for_each         = local.nodes
  target_group_arn = aws_lb_target_group.argocd.arn
  target_id        = aws_instance.node[each.key].id
  port             = 30081
}
import {
  for_each = var.compute_enabled ? var.adopt_instances : {}
  to       = aws_instance.node[each.key]
  id       = each.value
}
import {
  for_each = var.adopt_security_group == null ? {} : { existing = var.adopt_security_group }
  to       = aws_security_group.nodes
  id       = each.value
}
output "nodes" {
  value = { for role, node in aws_instance.node : role => { id = node.id, public_ip = node.public_ip, private_ip = node.private_ip } }
}
output "compute_mode" { value = "k3s" }
output "node_subnet_indices" { value = var.node_subnet_indices }
