#!/usr/bin/env bash
# Build the image, start it without Telegram, wait for /health, then stop it.
# Usage: tools/smoke_container.sh [image-tag]
set -euo pipefail

image="${1:-themi:smoke}"
name="themi-smoke-$$"

docker build -t "$image" .
key="$(docker run --rm --entrypoint themi "$image" keygen)"
docker run -d --name "$name" -p 127.0.0.1:18080:8080 \
    -e THEMI_SECRET_KEY="$key" -e THEMI_DISABLE_TELEGRAM=1 "$image" >/dev/null
trap 'docker logs "$name" || true; docker rm -f "$name" >/dev/null 2>&1 || true' EXIT

for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:18080/health; then
        echo
        docker stop --time 20 "$name" >/dev/null
        status="$(docker inspect --format '{{.State.ExitCode}}' "$name")"
        echo "container exited with status $status"
        test "$status" = "0"
        exit 0
    fi
    sleep 1
done
echo "health check never passed" >&2
exit 1
