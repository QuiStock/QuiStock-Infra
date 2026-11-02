# Only retained when adopting the historical EKS state. Never required for a new lab.
resource "aws_eks_cluster" "this" {
  count                         = var.legacy_eks == null ? 0 : 1
  name                          = var.cluster_name
  role_arn                      = var.legacy_eks.cluster_role_arn
  version                       = var.legacy_eks.kubernetes_version
  bootstrap_self_managed_addons = false
  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = false
  }
  upgrade_policy {
    support_type = "STANDARD"
  }
  vpc_config {
    subnet_ids              = aws_subnet.public[*].id
    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = var.admin_cidrs
  }
  depends_on = [aws_route_table_association.public]
}
resource "aws_eks_access_entry" "admin" {
  count         = var.legacy_eks == null ? 0 : 1
  cluster_name  = aws_eks_cluster.this[0].name
  principal_arn = var.legacy_eks.admin_role_arn
  type          = "STANDARD"
}
resource "aws_eks_access_policy_association" "admin" {
  count         = var.legacy_eks == null ? 0 : 1
  cluster_name  = aws_eks_cluster.this[0].name
  principal_arn = aws_eks_access_entry.admin[0].principal_arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  access_scope {
    type = "cluster"
  }
}
resource "aws_eks_addon" "network" {
  for_each                    = var.legacy_eks == null ? {} : { "vpc-cni" = var.legacy_eks.addon_versions.vpc_cni }
  cluster_name                = aws_eks_cluster.this[0].name
  addon_name                  = each.key
  addon_version               = each.value
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "PRESERVE"
}
resource "aws_eks_node_group" "arm" {
  count           = var.legacy_eks == null ? 0 : 1
  cluster_name    = aws_eks_cluster.this[0].name
  node_group_name = "quistock-arm"
  node_role_arn   = var.legacy_eks.node_role_arn
  subnet_ids      = aws_subnet.public[*].id
  instance_types  = var.legacy_eks.instance_types
  ami_type        = "AL2023_ARM_64_STANDARD"
  capacity_type   = "ON_DEMAND"
  disk_size       = 20
  scaling_config {
    desired_size = 0
    min_size     = 0
    max_size     = var.legacy_eks.node_count
  }
  update_config {
    max_unavailable = 1
  }
  depends_on = [aws_eks_addon.network]
}
resource "aws_eks_addon" "coredns" {
  count                       = var.legacy_eks == null ? 0 : 1
  cluster_name                = aws_eks_cluster.this[0].name
  addon_name                  = "coredns"
  addon_version               = var.legacy_eks.addon_versions.coredns
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "PRESERVE"
  depends_on                  = [aws_eks_node_group.arm]
}
resource "aws_eks_addon" "kube_proxy" {
  count                       = var.legacy_eks == null ? 0 : 1
  cluster_name                = aws_eks_cluster.this[0].name
  addon_name                  = "kube-proxy"
  addon_version               = var.legacy_eks.addon_versions.kube_proxy
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "PRESERVE"
  depends_on                  = [aws_eks_node_group.arm]
}

moved {
  from = aws_eks_cluster.this
  to   = aws_eks_cluster.this[0]
}
moved {
  from = aws_eks_access_entry.admin
  to   = aws_eks_access_entry.admin[0]
}
moved {
  from = aws_eks_access_policy_association.admin
  to   = aws_eks_access_policy_association.admin[0]
}
moved {
  from = aws_eks_node_group.arm
  to   = aws_eks_node_group.arm[0]
}
moved {
  from = aws_eks_addon.coredns
  to   = aws_eks_addon.coredns[0]
}
moved {
  from = aws_eks_addon.kube_proxy
  to   = aws_eks_addon.kube_proxy[0]
}