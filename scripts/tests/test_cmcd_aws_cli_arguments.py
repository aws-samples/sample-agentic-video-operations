"""Reject unsupported flags in AWS CLI commands built by the CMCD scripts."""

import ast
from pathlib import Path

COMMAND_FLAGS = {
    ("cloudformation", "delete-stack"): {"--region", "--retain-resources", "--stack-name"},
    ("cloudformation", "deploy"): {
        "--capabilities",
        "--parameter-overrides",
        "--region",
        "--s3-bucket",
        "--s3-prefix",
        "--stack-name",
        "--template-file",
    },
    ("cloudformation", "describe-stack-resource"): {
        "--logical-resource-id",
        "--output",
        "--query",
        "--region",
        "--stack-name",
    },
    ("cloudformation", "describe-stacks"): {
        "--output",
        "--query",
        "--region",
        "--stack-name",
    },
    ("cloudformation", "wait"): {"--region", "--stack-name"},
    ("logs", "delete-log-group"): {"--log-group-name", "--region"},
    ("logs", "describe-log-groups"): {
        "--log-group-name-prefix",
        "--output",
        "--query",
        "--region",
    },
    ("s3", "rm"): {"--only-show-errors", "--recursive", "--region"},
    ("s3api", "create-bucket"): {"--bucket", "--region"},
    ("s3api", "delete-bucket"): {
        "--bucket",
        "--expected-bucket-owner",
        "--region",
    },
    ("s3api", "head-bucket"): {
        "--bucket",
        "--expected-bucket-owner",
        "--region",
    },
    ("s3api", "put-bucket-encryption"): {
        "--bucket",
        "--expected-bucket-owner",
        "--region",
        "--server-side-encryption-configuration",
    },
    ("s3api", "put-public-access-block"): {
        "--bucket",
        "--expected-bucket-owner",
        "--public-access-block-configuration",
        "--region",
    },
    ("secretsmanager", "get-secret-value"): {
        "--output",
        "--query",
        "--region",
        "--secret-id",
    },
    ("sts", "get-caller-identity"): {"--output", "--query"},
    ("timestream-influxdb", "delete-db-instance"): {"--identifier", "--region"},
    ("timestream-influxdb", "get-db-instance"): {
        "--identifier",
        "--output",
        "--query",
        "--region",
    },
}
CMCD_AWS_SCRIPTS = (
    Path("scripts/manage_cmcd_stack.py"),
    Path("scripts/destroy_cmcd_stack.py"),
    Path("scripts/create_cmcd_read_token.py"),
)
AWS_SERVICES = {service for service, _ in COMMAND_FLAGS}


def test_every_cmcd_aws_cli_command_uses_only_supported_flags():
    seen: set[tuple[str, str]] = set()
    for path in CMCD_AWS_SCRIPTS:
        for command, flags, line in _read_command_shapes(path):
            assert command in COMMAND_FLAGS, f"{path}:{line}: unreviewed AWS CLI command {command}"
            unsupported = flags - COMMAND_FLAGS[command]
            assert not unsupported, f"{path}:{line}: unsupported flags {sorted(unsupported)}"
            seen.add(command)

    assert seen == set(COMMAND_FLAGS)


def _read_command_shapes(
    path: Path,
) -> list[tuple[tuple[str, str], set[str], int]]:
    shapes = []
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.List) or len(node.elts) < 2:
            continue
        service = _literal_string(node.elts[0])
        operation = _literal_string(node.elts[1])
        if service not in AWS_SERVICES or operation is None:
            continue
        flags = {
            value
            for element in node.elts[2:]
            if (value := _literal_string(element)) is not None and value.startswith("--")
        }
        shapes.append(((service, operation), flags, node.lineno))
    return shapes


def _literal_string(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None
