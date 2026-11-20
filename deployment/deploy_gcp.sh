#!/usr/bin/env bash
# Production deployment on Google Cloud (Cloud Run), free-tier oriented.
#
#   gcloud auth login && gcloud auth application-default login
#   bash deployment/deploy_gcp.sh MY_PROJECT_ID [REGION]
#
# Gemini is called with the Google AI Studio API key (free tier), NOT Vertex AI.
# 1. enables the APIs
# 2. stores the Gemini API key (read from .env) in Secret Manager — never in the
#    image, never as a plain environment variable
# 3. (optional) stores the Socrata/DataSF app token in Secret Manager
# 4. deploys the agent with agents-cli on Cloud Run (min 0 instances: no idle cost)
# Traces and logs then appear in Cloud Trace / Cloud Logging (free quotas).
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${1:?usage: deploy_gcp.sh PROJECT_ID [REGION]}"
REGION="${2:-us-west1}"

# --- Gemini key from .env (or the environment) ---------------------------------
if [ -z "${GEMINI_API_KEY:-}" ] && [ -f .env ]; then
  GEMINI_API_KEY=$(grep -E '^GEMINI_API_KEY=' .env | tail -1 | cut -d= -f2- || true)
fi
if [ -z "${GEMINI_API_KEY:-}" ] || [ "$GEMINI_API_KEY" = "your-api-key-here" ]; then
  echo "GEMINI_API_KEY missing: put your Google AI Studio key in .env first." >&2
  exit 1
fi

gcloud config set project "$PROJECT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com cloudtrace.googleapis.com logging.googleapis.com telemetry.googleapis.com

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
RUN_SA="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"

put_secret() {  # $1 = secret name, $2 = value
  if gcloud secrets describe "$1" >/dev/null 2>&1; then
    printf %s "$2" | gcloud secrets versions add "$1" --data-file=- >/dev/null
  else
    printf %s "$2" | gcloud secrets create "$1" --replication-policy=automatic --data-file=- >/dev/null
  fi
  gcloud secrets add-iam-policy-binding "$1" \
    --member="serviceAccount:$RUN_SA" --role=roles/secretmanager.secretAccessor >/dev/null
  echo "Secret Manager: $1 updated"
}

# --- Secret Manager ------------------------------------------------------------
put_secret gemini-api-key "$GEMINI_API_KEY"
SECRETS="GEMINI_API_KEY=gemini-api-key"
if [ -n "${SOCRATA_APP_TOKEN:-}" ]; then
  put_secret socrata-app-token "$SOCRATA_APP_TOKEN"
  SECRETS="$SECRETS,SOCRATA_APP_TOKEN=socrata-app-token"
fi

# --- Agent on Cloud Run (agents-cli) ---------------------------------------------
# agents-cli deploy copies the project .env into the service's environment: set
# the local .env aside so the key is NOT deployed as a plain env var, and
# restore it afterwards whatever happens.
cp .env .env.local-backup
trap 'mv -f .env.local-backup .env' EXIT
cat > .env <<ENV
GOOGLE_GENAI_USE_ENTERPRISE=false
GOOGLE_CLOUD_PROJECT=$PROJECT
ENV

uvx google-agents-cli deploy --project "$PROJECT" --region "$REGION" \
  --no-agent-identity --service-account "$RUN_SA" \
  --min-instances 0 --max-instances 2 \
  --env-vars "GOOGLE_GENAI_USE_ENTERPRISE=false,RAG_EMBEDDINGS=gemini,OTEL_TO_CLOUD=true" \
  --secrets "$SECRETS"

echo
echo "Done. Next:"
echo "  - CI/CD:      uvx google-agents-cli infra cicd   (tests on PR, deploy on merge)"
echo "               then add the GEMINI_API_KEY GitHub secret: gh secret set GEMINI_API_KEY"
echo "  - Monitoring: https://console.cloud.google.com/traces/list?project=$PROJECT"
echo "  - UI:         AGENT_API_URL=<agent url> AGENT_ID_TOKEN=\$(gcloud auth print-identity-token) uv run streamlit run frontend/streamlit_app.py"
