FROM python:3.11-slim

# Node is only needed for the Caravo CLI. Keep the runtime on an exact,
# security-patched release and install the CLI at image-build time so request
# handling never downloads and executes an unpinned npm package.
ARG NODE_VERSION=24.22.1
ARG TARGETARCH
ARG CARAVO_CLI_VERSION=0.2.23
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl xz-utils && \
    case "${TARGETARCH:-amd64}" in \
      amd64) node_arch=x64 ;; \
      arm64) node_arch=arm64 ;; \
      *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac && \
    curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" && \
    curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt" && \
    grep " node-v${NODE_VERSION}-linux-${node_arch}.tar.xz$" SHASUMS256.txt | sha256sum -c - && \
    tar -xJf "node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" -C /usr/local --strip-components=1 --no-same-owner && \
    test "$(node --version)" = "v${NODE_VERSION}" && \
    npm install --global "@caravo/cli@${CARAVO_CLI_VERSION}" && \
    caravo --help >/dev/null && \
    npm cache clean --force && \
    rm -f "node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" SHASUMS256.txt && \
    apt-get purge -y --auto-remove xz-utils && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}
