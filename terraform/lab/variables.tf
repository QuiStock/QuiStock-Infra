variable "account_id" { type = string }
variable "region" { type = string }
variable "cluster_name" { type = string }
variable "availability_zones" {
  type = list(string)
  validation {
    condition     = length(distinct(var.availability_zones)) == 2
    error_message = "Exactly two availability zones are required."
  }
}
variable "vpc_cidr" { default = "10.40.0.0/16" }
variable "cors_allowed_origins" {
  type    = list(string)
  default = []
}
variable "admin_cidrs" {
  type = list(string)
  validation {
    condition     = length(var.admin_cidrs) > 0 && alltrue([for c in var.admin_cidrs : can(cidrhost(c, 0)) && endswith(c, "/32")])
    error_message = "Use explicit operator IPv4 /32 addresses."
  }
}
variable "ami_id" { type = string }
variable "instance_type" { default = "t4g.large" }
variable "ssh_public_key" { type = string }
variable "compute_enabled" { default = true }
variable "node_subnet_indices" {
  type    = map(number)
  default = { server = 0, agent = 1 }
  validation {
    condition     = try(length(var.node_subnet_indices) == 2 && var.node_subnet_indices.server != var.node_subnet_indices.agent && alltrue([for index in values(var.node_subnet_indices) : contains([0, 1], index)]), false)
    error_message = "server and agent must use distinct subnet indices 0 and 1."
  }
}
variable "adopt_instances" {
  type    = map(string)
  default = {}
}
variable "adopt_security_group" {
  type    = string
  default = null
}
variable "legacy_eks" {
  type = object({
    cluster_role_arn   = string
    node_role_arn      = string
    admin_role_arn     = string
    kubernetes_version = string
    instance_types     = list(string)
    node_count         = number
    addon_versions     = object({ vpc_cni = string, coredns = string, kube_proxy = string })
  })
  default = null
}
