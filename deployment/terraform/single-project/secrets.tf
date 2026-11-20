# The agent calls Gemini with an AI Studio API key (free tier) stored in Secret
# Manager. The secret is created outside Terraform (the key never lands in the
# Terraform state); here we only let the app service account read it.
resource "google_secret_manager_secret_iam_member" "app_sa_gemini_key" {
  project   = var.project_id
  secret_id = var.gemini_api_key_secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app_sa.email}"
}
