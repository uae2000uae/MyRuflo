#!/bin/sh
# Cloud Run Jobs entrypoint. Reads the task from an env var rather than a
# positional CLI arg so job executions can pass free-form text (spaces,
# commas, quotes) via `--update-env-vars` without gcloud's comma-separated
# --args escaping rules getting in the way.
set -e

if [ -z "${MYRUFLO_TASK:-}" ]; then
    echo "ERROR: MYRUFLO_TASK env var must be set to the task description." >&2
    echo "Example: gcloud run jobs execute myruflo-job --update-env-vars=MYRUFLO_TASK='explain this workspace'" >&2
    exit 1
fi

FLAGS=""
case "${MYRUFLO_FORCE_SWARM:-auto}" in
    true) FLAGS="--swarm" ;;
    false) FLAGS="--no-swarm" ;;
    *) FLAGS="" ;;
esac

exec myruflo run $FLAGS "$MYRUFLO_TASK"
