# Themi: one container running the Telegram bot, scheduler and website.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml ./
# The dependencies first, from pyproject.toml alone, so a change to the code reuses this
# layer (the slowest step by far for the Pi's arm64 image, built under emulation). With
# them the optional connectors: OurGroceries, ThinQ's pushes, the Roborock vacuum. (Not
# Google Keep, the most fragile; add `keep` to EXTRAS to use it.)
ARG EXTRAS="ourgroceries thinq roborock"
RUN python -c "import sys, tomllib; p = tomllib.load(open('pyproject.toml', 'rb'))['project']; \
print('\n'.join(p['dependencies'] + [d for e in sys.argv[1:] for d in p['optional-dependencies'][e]]))" \
        $EXTRAS > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt
COPY README.md ./
COPY src ./src
RUN pip install --no-deps .

# Which release this is (the tag, from the release workflow); `themi --version` says it.
# After the installs, since it changes every release and would otherwise rebuild them.
ARG THEMI_BUILD_VERSION=dev
ENV THEMI_BUILD_VERSION=$THEMI_BUILD_VERSION

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
