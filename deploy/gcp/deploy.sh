#!/usr/bin/env bash
# Build MyRuflo's container, push it to Artifact Registry, and deploy it as
# a Cloud Run Job wired to the existing "MYRUFLO_EVL" Secret Manager secret.
#
# Assumes the secret already exists (this script never handles the raw key).
# Usage: deploy/gcp/deploy.sh PROJECT_ID [REGION] [SECRET_NAME]
set -euo pipefail

PROJECT_ID="${1:?Usage: deploy.sh PROJECT_ID [REGION] [SECRET_NAME]}"
REGION="${2:-us-central1}"
SECRET_NAME="${3:-MYRUFLO_EVL}"

REPO="myruflo"
JOB_NAME="myruflo-job"
SA_NAME="myruflo-runner"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/myruflo:latest"

echo "==> Project: $PROJECT_ID  Region: $REGION  Secret: $SECRET_NAME"
gcloud config set project "$PROJECT_ID" >/dev/null

echo "==> Ensuring Artifact Registry repo exists"
gcloud artifacts repositories describe "$REPO" --location="$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "$REPO" \
    --repository-format=docker --location="$REGION" \
    --description="MyRuflo container images"

echo "==> Building and pushing image via Cloud Build"
gcloud builds submit --tag "$IMAGE" "$(dirname "$0")/../.."

echo "==> Ensuring runner service account exists"
gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="MyRuflo Cloud Run runner"

echo "==> Granting the runner access to the $SECRET_NAME secret"
gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor"

echo "==> Deploying Cloud Run Job: $JOB_NAME"
gcloud run jobs deploy "$JOB_NAME" \
  --image="$IMAGE" \
  --region="$REGION" \
  --service-account="$SA_EMAIL" \
  --set-secrets="ANTHROPIC_API_KEY=${SECRET_NAME}:latest" \
  --set-env-vars="MYRUFLO_ALLOW_SHELL=false" \
  --max-retries=0 \
  --task-timeout=900

gcloud run services update myruflo \
  --region=us-central1 \
  --set-env-vars=MYRUFLO_TASK="Deploy from GitHub"


cat <<EOF

Deployed. Run a task with:

  gcloud run jobs execute $JOB_NAME --region=$REGION \\
    --update-env-vars="MYRUFLO_TASK=explain what this workspace does"

If your gcloud version doesn't support --update-env-vars on 'execute', do:

  gcloud run jobs update $JOB_NAME --region=$REGION \\
    --update-env-vars="MYRUFLO_TASK=explain what this workspace does"
  gcloud run jobs execute $JOB_NAME --region=$REGION

Note: each execution starts from a clean container — there is no persistent
disk by default, so /workspace and /data (memory + hooks log) reset every
run. To persist them across executions, mount a GCS bucket as a volume, e.g.:

  gcloud run jobs update $JOB_NAME --region=$REGION \\
    --add-volume=name=data,type=cloud-storage,bucket=YOUR_BUCKET \\
    --add-volume-mount=volume=data,mount-path=/data
EOF
