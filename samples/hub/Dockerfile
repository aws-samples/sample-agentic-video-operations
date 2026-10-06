# Build context: the repository root (the hub CDK stack and `docker build -f` both use it).
# uv installs the hub and the domain packs from the one lock file; no sibling folders are
# copied into the image.
FROM ghcr.io/astral-sh/uv:0.8.4-python3.13-bookworm-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY . .
RUN uv sync --frozen --no-dev --no-editable --package media-ops-hub --extra runtime

FROM public.ecr.aws/docker/library/python:3.13-slim
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 bedrock_agentcore
COPY --from=build --chown=bedrock_agentcore /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" DOCKER_CONTAINER=1
USER bedrock_agentcore
EXPOSE 8080
CMD ["opentelemetry-instrument", "serve-hub"]
