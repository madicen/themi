# Themi: one container running the Telegram bot, scheduler and website.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install '.[ourgroceries]'

# Run as an unprivileged user; the database lives on the /data volume.
RUN useradd --create-home --uid 10001 themi \
    && mkdir -p /data \
    && chown themi:themi /data
USER themi

ENV THEMI_DB_PATH=/data/themi.db \
    THEMI_HTTP_HOST=0.0.0.0 \
    THEMI_HTTP_PORT=8080
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["themi"]
CMD ["run"]
