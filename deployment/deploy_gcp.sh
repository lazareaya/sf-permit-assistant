#!/usr/bin/env bash
# End-to-end production deployment on Google Cloud (Cloud Run).
#
#   gcloud auth login && gcloud auth application-default login
#   bash deployment/deploy_gcp.sh MY_PROJECT_ID [REGION]
#
# 1. enables the APIs
# 2. creates the fraud API key in Secret Manager (never in code)
# 3. builds + deploys the Project 2 fraud API on Cloud Run (key from Secret Manager)
# 4. deploys the agent with agents-cli on Cloud Run (FRAUD_API_KEY from Secret Manager)
# Traces and logs then appear in Cloud Trace / Cloud Logging automatically.
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${1:?usage: deploy_gcp.sh PROJECT_ID [REGION]}"
REGION="${2:-europe-west1}"
P2_DIR="${P2_DIR:-../../PROJET 2 - ML /fraud-detection-mlops}"
REPO=agents
IMAGE="$REGION-docker.pkg.dev/$PROJECT/$REPO/fraud-api:latest"

gcloud config set project "$PROJECT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com aiplatform.googleapis.com cloudtrace.googleapis.com \
  logging.googleapis.com telemetry.googleapis.com

# --- 1. Secret Manager --------------------------------------------------------
if ! gcloud secrets describe fraud-api-key >/dev/null 2>&1; then
  openssl rand -hex 24 | tr -d '\n' | gcloud secrets create fraud-api-key --replication-policy=automatic --data-file=-
fi
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
RUN_SA="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"
gcloud secrets add-iam-policy-binding fraud-api-key \
  --member="serviceAccount:$RUN_SA" --role=roles/secretmanager.secretAccessor >/dev/null

# --- 2. Project 2 fraud API on Cloud Run ---------------------------------------
gcloud artifacts repositories describe "$REPO" --location "$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "$REPO" --repository-format=docker --location "$REGION"
gcloud builds submit "$P2_DIR" --config deployment/cloudbuild-fraud-api.yaml --substitutions "_IMAGE=$IMAGE"
gcloud run deploy fraud-api --image "$IMAGE" --region "$REGION" --port 7860 --memory 2Gi \
  --allow-unauthenticated --set-secrets API_KEY=fraud-api-key:latest
FRAUD_URL=$(gcloud run services describe fraud-api --region "$REGION" --format='value(status.url)')
echo "Fraud API: $FRAUD_URL"

# --- 3. Agent on Cloud Run (agents-cli) ----------------------------------------
sed -i.bak "s/^GOOGLE_CLOUD_PROJECT=.*/GOOGLE_CLOUD_PROJECT=$PROJECT/" .env && rm -f .env.bak
uvx google-agents-cli deploy --project "$PROJECT" --region "$REGION" \
  --no-agent-identity --service-account "$RUN_SA" \
  --env-vars "FRAUD_API_URL=$FRAUD_URL,RAG_EMBEDDINGS=gemini,OTEL_TO_CLOUD=true" \
  --secrets "FRAUD_API_KEY=fraud-api-key"

echo
echo "Done. Next:"
echo "  - CI/CD:      uvx google-agents-cli infra cicd   (tests on PR, deploy on merge)"
echo "  - Monitoring: https://console.cloud.google.com/traces/list?project=$PROJECT"
echo "  - UI:         AGENT_API_URL=<agent url> AGENT_ID_TOKEN=\$(gcloud auth print-identity-token) uv run streamlit run frontend/streamlit_app.py"
