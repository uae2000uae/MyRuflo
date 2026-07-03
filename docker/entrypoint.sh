#!/bin/sh
# Dual-mode entrypoint: the same image backs both the batch Cloud Run Job
# and the Cloud Run Service running the web UI.
#
# - If MYRUFLO_TASK is set (Cloud Run Jobs, or `docker run -e MYRUFLO_TASK=...`),
#   run the one-shot CLI task and exit — the historical Job behavior.
# - Otherwise (Cloud Run Services, or a plain `docker run`), start the web
#   server via `myruflo serve`, which listens on $PORT (Cloud Run sets this
#   automatically; it defaults to 8080 otherwise).
#
# Cloud persistence: when LITESTREAM_BUCKET is set, the SQLite databases
# (accounts/logins/conversations in app.db, agent memory in memory.db) are
# restored from the GCS bucket at startup and continuously replicated back
# while the process runs — so data survives redeploys and cold starts.
set -e

if [ -n "${MYRUFLO_TASK:-}" ]; then
    FLAGS=""
    case "${MYRUFLO_FORCE_SWARM:-auto}" in
        true) FLAGS="--swarm" ;;
        false) FLAGS="--no-swarm" ;;
        *) FLAGS="" ;;
    esac
    CMD="myruflo run $FLAGS \"\$MYRUFLO_TASK\""
    if [ -n "${LITESTREAM_BUCKET:-}" ]; then
        litestream restore -if-replica-exists -if-db-not-exists /data/app.db
        litestream restore -if-replica-exists -if-db-not-exists /data/memory.db
        exec litestream replicate -exec "sh -c '$CMD'"
    fi
    exec sh -c "$CMD"
fi

if [ -n "${LITESTREAM_BUCKET:-}" ]; then
    litestream restore -if-replica-exists -if-db-not-exists /data/app.db
    litestream restore -if-replica-exists -if-db-not-exists /data/memory.db
    exec litestream replicate -exec "myruflo serve"
fi

exec myruflo serve
