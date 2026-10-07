variable "account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "Informe o ID de 12 dígitos da conta de destino."
  }
}
variable "region" {
  type    = string
  default = "us-east-1"
}
variable "cluster_name" {
  type    = string
  default = "quistock"
}
variable "kubernetes_version" {
  type        = string
  description = "Versão em suporte padrão, validada no Learner Lab."
}
variable "cluster_role_arn" {
  type = string
}
variable "node_role_arn" {
  type = string
}
variable "admin_role_arn" {
  type        = string
  description = "ARN IAM da role do operador; nunca ARN STS de uma sessão."
}
variable "admin_cidrs" {
  type = list(string)
  validation {
    condition     = length(var.admin_cidrs) > 0 && alltrue([for c in var.admin_cidrs : can(cidrnetmask(c)) && !endswith(c, "/0")])
    error_message = "Informe CIDRs IPv4 administrativos restritos."
  }
}
variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}
variable "availability_zones" {
  type = list(string)
  validation {
    condition     = length(distinct(var.availability_zones)) == 2
    error_message = "Informe duas zonas distintas da região."
  }
}
variable "instance_types" {
  type    = list(string)
  default = ["t4g.medium"]
}
variable "node_count" {
  type    = number
  default = 2
  validation {
    condition     = var.node_count >= 1 && floor(var.node_count) == var.node_count
    error_message = "A capacidade deve ser um inteiro positivo."
  }
}
variable "addon_versions" {
  type = object({ vpc_cni = string, coredns = string, kube_proxy = string })
}
