"""A deployed hub reads APPROVAL_SIGNING_KEY from Secrets Manager once, at startup.

The CDK stack passes only the secret's ARN (runtime environment variables are visible in
the AgentCore control plane). The value is exported to this process's environment, so the
hub, which signs, and the domain packs, which verify, read the same key.
"""

from collections.abc import Callable, MutableMapping
from typing import Any

from media_ops_contracts.call_aws_operation import call_aws_operation
from media_ops_contracts.create_aws_client import create_aws_client


def export_approval_signing_key(
    environ: MutableMapping[str, str],
    create_client: Callable[..., Any] = create_aws_client,
) -> None:
    secret_arn = environ.get("APPROVAL_SIGNING_KEY_SECRET_ARN", "")
    if not secret_arn or environ.get("APPROVAL_SIGNING_KEY"):
        return
    client = create_client(
        "secretsmanager", region=environ.get("AWS_REGION", "us-west-2"), demo=False
    )
    secret = call_aws_operation(client, "get_secret_value", SecretId=secret_arn)
    environ["APPROVAL_SIGNING_KEY"] = secret["SecretString"]
