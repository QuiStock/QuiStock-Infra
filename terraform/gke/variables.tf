variable "project_id" {
  description = "ID do projeto Google Cloud com faturamento habilitado."
  type        = string
}

variable "region" {
  description = "Região do GKE. us-east1 oferece Autopilot ARM64 de uso geral."
  type        = string
  default     = "us-east1"
}

variable "cluster_name" {
  description = "Nome do cluster GKE."
  type        = string
  default     = "quistock"
}

variable "deletion_protection" {
  description = "Exige desativação explícita antes de destruir o cluster."
  type        = bool
  default     = true
}
