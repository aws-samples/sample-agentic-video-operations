FROM public.ecr.aws/docker/library/python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

COPY media-services-langchain/shared/ /app/shared/
COPY media-services-langchain/coordinator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir aws-opentelemetry-distro>=0.10.1

RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore

COPY media-services-langchain/coordinator/ /app/coordinator/

ENV PYTHONPATH=/app
ENV AWS_REGION=us-west-2
EXPOSE 8080

CMD ["opentelemetry-instrument", "python", "-m", "coordinator.main"]
