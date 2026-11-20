# The agent calls Gemini with an AI Studio API key (free tier) stored in Secret
# Manager. The secret itself is created outside Terraform so that the key never
# lands in the Terraform state; here we only let the app service account read it.
resource "google_secret_manager_secret_iam_member" "app_sa_gemini_key" {
  for_each = local.deploy_project_ids

  project   = each.value
  secret_id = var.gemini_api_key_secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app_sa[each.key].email}"
}
