# BitaxePID on Alpine Linux (x86_64)
# Clones the application from GitHub at build time and installs every dependency.
#
#   docker compose build            # uses BITAXEPID_REPO / BITAXEPID_REF from .env
#   docker compose up -d

ARG ALPINE_VERSION=3.20

# ---------- Stage 1: fetch the source ----------
FROM --platform=linux/amd64 alpine:${ALPINE_VERSION} AS source
ARG BITAXEPID_REPO=https://github.com/ldemattos/BitaxePID.git
ARG BITAXEPID_REF=main
RUN apk add --no-cache git \
 && git clone --depth 1 --branch "${BITAXEPID_REF}" "${BITAXEPID_REPO}" /src \
 && rm -rf /src/.git

# ---------- Stage 2: runtime image ----------
FROM --platform=linux/amd64 alpine:${ALPINE_VERSION}
LABEL org.opencontainers.image.title="bitaxepid" \
      org.opencontainers.image.source="https://github.com/ldemattos/BitaxePID"

# Runtime dependencies: Python, tini (clean signal handling), curl (healthcheck)
RUN apk add --no-cache python3 py3-pip tini curl bash \
 && adduser -D -h /app -u 1000 bitaxe

WORKDIR /app
COPY --from=source /src/requirements.txt /app/requirements.txt

# Isolated virtualenv so Alpine's system python stays untouched
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    BITAXEPID_HOME=/app \
    BITAXEPID_DATA=/data

COPY --from=source /src/*.py /src/*.yaml /app/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh \
 && mkdir -p /data && chown -R bitaxe:bitaxe /app /data

USER bitaxe
VOLUME ["/data"]
EXPOSE 8093

ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/entrypoint.sh"]
