"""Read the service and resource type out of one ARN (§8.2's table).

A signal map names resources across six services, each writing its resource part differently,
so the type is read per service rather than by one guess. An ARN this cannot parse is kept as
`unknown`/`unknown` and never dropped: a node the chain contains is evidence either way.
"""

from dataclasses import dataclass

UNKNOWN = "unknown"
ARN_FIELDS = 6  # arn:<partition>:<service>:<region>:<account>:<resource>


@dataclass(frozen=True)
class ArnParts:
    service: str
    resource_type: str


def read_arn_parts(arn: str) -> ArnParts:
    fields = arn.split(":", ARN_FIELDS - 1)
    if len(fields) < ARN_FIELDS or fields[0] != "arn":
        return ArnParts(service=UNKNOWN, resource_type=UNKNOWN)
    service, resource = fields[2], fields[5]
    if not service or not resource:
        return ArnParts(service=service or UNKNOWN, resource_type=UNKNOWN)
    return ArnParts(service=service, resource_type=read_resource_type(service, resource))


def read_resource_type(service: str, resource: str) -> str:
    if service == "s3":
        return "object" if "/" in resource else "bucket"
    if service == "mediapackagev2":
        return last_path_type(resource)
    return resource.split("/")[0].split(":")[0] or UNKNOWN


def last_path_type(resource: str) -> str:
    """`channelGroup/<g>/channel/<c>/originEndpoint/<e>` names its type before each id."""
    parts = [part for part in resource.split("/") if part]
    types = parts[::2]  # every other segment is a type, each followed by its id
    return types[-1] if types else UNKNOWN
