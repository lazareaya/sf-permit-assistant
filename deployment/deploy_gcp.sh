#!/usr/bin/env bash
# Production deployment on Google Cloud (Cloud Run).
#
#   gcloud auth login && gcloud auth application-default login
#   SOCRATA_APP_TOKEN=xxx bash deployment/deploy_gcp.sh MY_PROJECT_ID [REGION]
#
# 1. enables the APIs
# 2. stores the (optional) Socrata/DataSF app token in Secret Manager
# 3. deploys the agent with agents-cli on Cloud Run (token injected from Secret Manager)
# Gemini is reached through Vertex AI with the service identity: no API key in prod.
# Traces and logs then appear in Cloud Trace / Cloud Logging automatically.
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${1:?usage: deploy_gcp.sh PROJECT_ID [REGION]}"
REGION="${2:-us-west1}"

gcloud config set project "$PROJECT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com aiplatform.googleapis.com cloudtrace.googleapis.com \
  logging.googleapis.com telemetry.googleapis.com

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
RUN_SA="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"
SECRET_FLAGS=()

# --- Secret Manager (optional DataSF app token) --------------------------------
if [ -n "${SOCRATA_APP_TOKEN:-}" ]; then
  if gcloud secrets describe socrata-app-token >/dev/null 2>&1; then
    printf %s "$SOCRATA_APP_TOKEN" | gcloud secrets versions add socrata-app-token --data-file=-
  else
    printf %s "$SOCRATA_APP_TOKEN" | gcloud secrets create socrata-app-token --replication-policy=automatic --data-file=-
  fi
  gcloud secrets add-iam-policy-binding socrata-app-token \
    --member="serviceAccount:$RUN_SA" --role=roles/secretmanager.secretAccessor >/dev/null
  SECRET_FLAGS=(--secrets "SOCRATA_APP_TOKEN=socrata-app-token")
else
  echo "No SOCRATA_APP_TOKEN given: DataSF is called anonymously (lower rate limits)."
fi

# --- Agent on Cloud Run (agents-cli) --------------------------------------------
sed -i.bak "s/^GOOGLE_CLOUD_PROJECT=.*/GOOGLE_CLOUD_PROJECT=$PROJECT/" .env && rm -f .env.bak
uvx google-agents-cli deploy --project "$PROJECT" --region "$REGION" \
  --no-agent-identity --service-account "$RUN_SA" \
  --env-vars "RAG_EMBEDDINGS=gemini,OTEL_TO_CLOUD=true" \
  "${SECRET_FLAGS[@]}"

echo
echo "Done. Next:"
echo "  - CI/CD:      uvx google-agents-cli infra cicd   (tests on PR, deploy on merge)"
echo "  - Monitoring: https://console.cloud.google.com/traces/list?project=$PROJECT"
echo "  - UI:         AGENT_API_URL=<agent url> AGENT_ID_TOKEN=\$(gcloud auth print-identity-token) uv run streamlit run frontend/streamlit_app.py"
