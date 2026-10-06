FROM public.ecr.aws/docker/library/python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

# Shared module
COPY samples/hub/shared/ /app/shared/

# Reuse existing MediaLive tool implementations (no duplication)
COPY samples/medialive/src/ /app/src/

COPY samples/hub/eml/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir aws-opentelemetry-distro>=0.10.1

RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore

COPY samples/hub/eml/ /app/eml/

ENV PYTHONPATH=/app
ENV AWS_REGION=us-west-2
EXPOSE 8080

CMD ["opentelemetry-instrument", "python", "-m", "eml.main"]
