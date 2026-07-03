#!/usr/bin/env bash
# Build MyRuflo's container, push it to Artifact Registry, and deploy both
# Cloud Run shapes wired to the existing "ANTHROPIC_AI_KEY" Secret Manager
# secret:
#   - myruflo-job: batch one-shot task runner (MYRUFLO_TASK env var per run)
#   - myruflo:     the web UI (chat + admin panel), listening on $PORT
# Both run the same image; docker/entrypoint.sh picks the mode based on
# whether MYRUFLO_TASK is set.
#
# Assumes the secret already exists (this script never handles the raw key).
# Usage: deploy/gcp/deploy.sh PROJECT_ID [REGION] [SECRET_NAME]
set -euo pipefail

PROJECT_ID="${1:?Usage: deploy.sh PROJECT_ID [REGION] [SECRET_NAME]}"
REGION="${2:-us-central1}"
SECRET_NAME="${3:-ANTHROPIC_AI_KEY}"

REPO="myruflo"
JOB_NAME="myruflo-job"
SERVICE_NAME="myruflo"
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

# Multi-platform keys: the app resolves these secret IDs from Secret Manager
# at runtime (see myruflo/llm/specs.py). Grant access to whichever ones exist
# in this project — missing ones are skipped, and the app degrades gracefully.
echo "==> Granting the runner access to any per-platform key secrets that exist"
for PLATFORM_SECRET in OPENAI_API_KEY GEMINI_API_KEY GOOGLE_API_KEY XAI_API_KEY GROK_API_KEY DEEPSEEK_API_KEY MISTRAL_API_KEY ANTHROPIC_API_KEY; do
  if gcloud secrets describe "$PLATFORM_SECRET" >/dev/null 2>&1; then
    echo "    - $PLATFORM_SECRET"
    gcloud secrets add-iam-policy-binding "$PLATFORM_SECRET" \
      --member="serviceAccount:${SA_EMAIL}" \
      --role="roles/secretmanager.secretAccessor" >/dev/null
  fi
done

echo "==> Deploying Cloud Run Job: $JOB_NAME"
gcloud run jobs deploy "$JOB_NAME" \
  --image="$IMAGE" \
  --region="$REGION" \
  --service-account="$SA_EMAIL" \
  --set-secrets="ANTHROPIC_API_KEY=${SECRET_NAME}:latest" \
  --set-env-vars="MYRUFLO_ALLOW_SHELL=false" \
  --max-retries=0 \
  --task-timeout=900

echo "==> Deploying Cloud Run Service: $SERVICE_NAME (web UI)"
# The key is bound on this service as a plain env var named ANTHROPIC_AI_KEY
# (not the standard ANTHROPIC_API_KEY name the Job uses above). config.py's
# _resolve_api_key() checks ANTHROPIC_AI_KEY as a fallback, so keep binding
# it under that same name here rather than reverting it to a different one
# on the next deploy.
# --set-env-vars replaces the full env var set on this revision, which also
# clears out any stray MYRUFLO_TASK left over from earlier config — the new
# dual-mode entrypoint would otherwise mistake this for a Job and never
# start the web server.
# --max-instances=1 --min-instances=1: the web UI's SQLite data (accounts,
# chats, tool toggles) lives on local disk, which is neither shared across
# instances nor durable across a fresh cold start. Pinning to exactly one
# always-on instance keeps that data consistent while the revision is
# running (it still resets on a new deploy). Revisit with a GCS-backed
# volume or a real database if you need it to survive redeploys too.
gcloud run deploy "$SERVICE_NAME" \
  --image="$IMAGE" \
  --region="$REGION" \
  --service-account="$SA_EMAIL" \
  --set-secrets="ANTHROPIC_AI_KEY=${SECRET_NAME}:latest" \
  --set-env-vars="MYRUFLO_ALLOW_SHELL=false" \
  --max-instances=1 \
  --min-instances=1 \
  --allow-unauthenticated \
  --port=8080

SERVICE_URL="$(gcloud run services describe "$SERVICE_NAME" --region="$REGION" --format='value(status.url)')"

cat <<EOF

Deployed.

Web UI: $SERVICE_URL
(the first account registered there becomes the admin)

Run a batch task on the Job with:

  gcloud run jobs execute $JOB_NAME --region=$REGION \\
    --update-env-vars="MYRUFLO_TASK=explain what this workspace does"

If your gcloud version doesn't support --update-env-vars on 'execute', do:

  gcloud run jobs update $JOB_NAME --region=$REGION \\
    --update-env-vars="MYRUFLO_TASK=explain what this workspace does"
  gcloud run jobs execute $JOB_NAME --region=$REGION

Note: each Job execution starts from a clean container — there is no
persistent disk by default, so /workspace and /data (memory + hooks log)
reset every run. To persist them across executions, mount a GCS bucket as
a volume, e.g.:

  gcloud run jobs update $JOB_NAME --region=$REGION \\
    --add-volume=name=data,type=cloud-storage,bucket=YOUR_BUCKET \\
    --add-volume-mount=volume=data,mount-path=/data

The same --add-volume/--add-volume-mount flags work on
'gcloud run services update $SERVICE_NAME' if you later want the web UI's
data/app.db and data/memory.db to survive redeploys.
EOF
