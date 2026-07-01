# MyRuflo — container image for GCP hosting.
#
# One image, two Cloud Run shapes, picked at runtime by docker/entrypoint.sh:
#   - Cloud Run Job:     MYRUFLO_TASK is set -> runs one batch task and exits.
#   - Cloud Run Service: MYRUFLO_TASK is unset -> runs `myruflo serve`, which
#                         listens on $PORT (Cloud Run injects this; defaults
#                         to 8080 otherwise).
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml requirements.txt requirements-gcp.txt ./
COPY myruflo ./myruflo

RUN pip install --no-cache-dir -r requirements.txt -r requirements-gcp.txt \
    && pip install --no-cache-dir --no-deps .

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && mkdir -p /workspace /data

ENV MYRUFLO_WORKSPACE=/workspace \
    MYRUFLO_DATA_DIR=/data \
    MYRUFLO_ALLOW_SHELL=false

ENTRYPOINT ["/entrypoint.sh"]
