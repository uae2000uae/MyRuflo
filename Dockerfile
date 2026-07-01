# MyRuflo — container image for GCP hosting (Cloud Run Jobs).
#
# Shaped as a one-shot task runner rather than an HTTP service: Cloud Run
# Jobs execute the container to completion and don't require a listener on
# $PORT, which fits this CLI tool's "run a task, print the result, exit"
# nature far better than Cloud Run's request-serving Service type.
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
