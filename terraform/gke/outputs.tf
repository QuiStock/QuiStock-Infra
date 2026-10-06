output "cluster_name" {
  description = "Nome do cluster criado."
  value       = google_container_cluster.gke.name
}

output "region" {
  description = "Região do cluster."
  value       = google_container_cluster.gke.location
}

output "get_credentials_command" {
  description = "Comando para configurar kubectl depois do apply."
  value       = "gcloud container clusters get-credentials ${google_container_cluster.gke.name} --region ${var.region} --project ${var.project_id}"
}
