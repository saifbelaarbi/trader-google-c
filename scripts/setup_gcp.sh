#!/usr/bin/env bash
# GCP setup script — run this once to provision all cloud resources
# Usage: ./scripts/setup_gcp.sh <your-gcp-project-id> <your-github-username>
# Example: ./scripts/setup_gcp.sh my-tradingbot-123 saifbelaarbi

set -euo pipefail

PROJECT_ID=${1:?"Usage: ./setup_gcp.sh <project-id> <github-username-or-org>"}
GITHUB_USER=${2:?"Usage: ./setup_gcp.sh <project-id> <github-username-or-org>"}
REPO_NAME="trader-google-c"
REGION="europe-west1"
SA_NAME="tradingbot-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "→ Project: $PROJECT_ID  GitHub: ${GITHUB_USER}/${REPO_NAME}"
gcloud config set project "$PROJECT_ID"

echo "→ Enabling APIs"
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com

echo "→ Creating Firestore database (native mode)"
gcloud firestore databases create --location="$REGION" 2>/dev/null || echo "  Firestore already exists, skipping"

echo "→ Creating Artifact Registry repository"
gcloud artifacts repositories create tradingbot \
  --repository-format=docker \
  --location="$REGION" 2>/dev/null || echo "  Registry already exists, skipping"

echo "→ Creating service account"
gcloud iam service-accounts create "$SA_NAME" \
  --display-name="TradingBot SA" 2>/dev/null || echo "  SA already exists, skipping"

echo "→ Granting IAM roles"
for ROLE in roles/datastore.user roles/secretmanager.secretAccessor roles/logging.logWriter roles/artifactregistry.writer roles/run.admin; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="$ROLE" \
    --quiet
done

# Allow the SA to act as itself when Cloud Run uses it as a runtime SA
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --role="roles/iam.serviceAccountUser" \
  --member="serviceAccount:$SA_EMAIL" \
  --quiet

echo "→ Setting up Workload Identity Federation for GitHub Actions"
if gcloud iam workload-identity-pools describe "github-pool" --location="global" --quiet 2>/dev/null; then
  echo "  Pool 'github-pool' already exists, skipping create"
else
  gcloud iam workload-identity-pools create "github-pool" \
    --location="global" \
    --display-name="GitHub Actions Pool"
fi

if gcloud iam workload-identity-pools providers describe "github-provider" \
    --location="global" --workload-identity-pool="github-pool" --quiet 2>/dev/null; then
  echo "  Provider 'github-provider' already exists, skipping create"
else
  gcloud iam workload-identity-pools providers create-oidc "github-provider" \
    --location="global" \
    --workload-identity-pool="github-pool" \
    --display-name="GitHub Provider" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition="assertion.repository=='${GITHUB_USER}/${REPO_NAME}'" \
    --issuer-uri="https://token.actions.githubusercontent.com"
fi

POOL_ID=$(gcloud iam workload-identity-pools describe "github-pool" \
  --location="global" --format="value(name)")

gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${POOL_ID}/attribute.repository/${GITHUB_USER}/${REPO_NAME}"

echo "→ Creating WEBHOOK_SECRET (you will be prompted to paste a value)"
echo "  Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
echo "  Paste your webhook secret (then press Enter):"
read -r WEBHOOK_SECRET_VAL
printf '%s' "$WEBHOOK_SECRET_VAL" | gcloud secrets create WEBHOOK_SECRET --data-file=- 2>/dev/null || \
  printf '%s' "$WEBHOOK_SECRET_VAL" | gcloud secrets versions add WEBHOOK_SECRET --data-file=-

echo ""
echo "✅ GCP setup complete!"
echo ""
echo "Add these three secrets to your GitHub repo:"
echo "  (Settings → Secrets and variables → Actions → New repository secret)"
echo ""
echo "  GCP_PROJECT_ID=$PROJECT_ID"
echo "  GCP_SA_EMAIL=$SA_EMAIL"

PROVIDER_ID=$(gcloud iam workload-identity-pools providers describe "github-provider" \
  --location="global" \
  --workload-identity-pool="github-pool" \
  --format="value(name)")
echo "  WORKLOAD_IDENTITY_PROVIDER=$PROVIDER_ID"
echo ""
echo "Your WEBHOOK_SECRET is in GCP Secret Manager."
echo "You'll also need it in TradingView alerts and in agent/.env"
echo ""
echo "Next step: push to main to trigger the first deploy."
