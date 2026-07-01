#!/bin/sh
# Dual-mode entrypoint: the same image backs both the batch Cloud Run Job
# and the Cloud Run Service running the web UI.
#
# - If MYRUFLO_TASK is set (Cloud Run Jobs, or `docker run -e MYRUFLO_TASK=...`),
#   run the one-shot CLI task and exit — the historical Job behavior.
# - Otherwise (Cloud Run Services, or a plain `docker run`), start the web
#   server via `myruflo serve`, which listens on $PORT (Cloud Run sets this
#   automatically; it defaults to 8080 otherwise).
set -e

if [ -n "${MYRUFLO_TASK:-}" ]; then
    FLAGS=""
    case "${MYRUFLO_FORCE_SWARM:-auto}" in
        true) FLAGS="--swarm" ;;
        false) FLAGS="--no-swarm" ;;
        *) FLAGS="" ;;
    esac
    exec myruflo run $FLAGS "$MYRUFLO_TASK"
fi

exec myruflo serve
