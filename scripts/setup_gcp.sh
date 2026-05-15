#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID=${1:?"Usage: ./setup_gcp.sh <project-id>"}
REGION="europe-west1"
SA_NAME="tradingbot-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
REPO_NAME="trader-google-c"  # TODO: update to your GitHub repo name

echo "→ Setting project to $PROJECT_ID"
gcloud config set project "$PROJECT_ID"

echo "→ Enabling APIs"
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com

echo "→ Creating Firestore database"
gcloud firestore databases create --location="$REGION" || echo "Firestore already exists, skipping"

echo "→ Creating Artifact Registry"
gcloud artifacts repositories create tradingbot \
  --repository-format=docker \
  --location="$REGION" || echo "Registry already exists, skipping"

echo "→ Creating service account"
gcloud iam service-accounts create "$SA_NAME" \
  --display-name="TradingBot SA" || echo "SA already exists"

echo "→ Granting IAM roles"
for ROLE in roles/datastore.user roles/secretmanager.secretAccessor roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="$ROLE"
done

echo "→ Setting up Workload Identity Federation for GitHub Actions"
gcloud iam workload-identity-pools create "github-pool" \
  --location="global" \
  --display-name="GitHub Actions Pool" || echo "Pool already exists"

gcloud iam workload-identity-pools providers create-oidc "github-provider" \
  --location="global" \
  --workload-identity-pool="github-pool" \
  --display-name="GitHub Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com" || echo "Provider already exists"

POOL_ID=$(gcloud iam workload-identity-pools describe "github-pool" \
  --location="global" --format="value(name)")

# TODO: replace YOUR_GITHUB_ORG with your actual GitHub organization/username
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${POOL_ID}/attribute.repository/YOUR_GITHUB_ORG/${REPO_NAME}"

echo "→ Creating secrets (you will be prompted to paste values)"
for SECRET in BINANCE_API_KEY BINANCE_API_SECRET WEBHOOK_SECRET; do
  echo "Paste value for $SECRET (then press Enter + Ctrl-D):"
  gcloud secrets create "$SECRET" --data-file=- || \
    gcloud secrets versions add "$SECRET" --data-file=-
done

echo -n "testnet" | gcloud secrets create TRADING_MODE --data-file=- || \
  echo -n "testnet" | gcloud secrets versions add TRADING_MODE --data-file=-

echo ""
echo "✅ GCP setup complete"
echo ""
echo "Set these as GitHub Actions secrets:"
echo "  GCP_PROJECT_ID=$PROJECT_ID"
echo "  GCP_SA_EMAIL=$SA_EMAIL"
PROVIDER_ID=$(gcloud iam workload-identity-pools providers describe "github-provider" \
  --location="global" \
  --workload-identity-pool="github-pool" \
  --format="value(name)")
echo "  WORKLOAD_IDENTITY_PROVIDER=$PROVIDER_ID"
