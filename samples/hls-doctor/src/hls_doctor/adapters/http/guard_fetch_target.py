"""The SSRF guard every live fetch goes through, on every redirect hop.

A URL may only be fetched when its scheme is http(s) and every address its
host resolves to is global unicast: loopback, private, link-local (including
169.254.0.0/16 and fe80::/10), unique-local, multicast, reserved and
unspecified addresses are refused. The guard re-resolves and re-checks
immediately before each connection (each call), rather than pinning the
connection to a checked address; this is the documented TOCTOU trade-off,
and redirect hops are guarded individually so a redirect cannot bypass it.

`HLS_ALLOW_PRIVATE_TARGETS=true` opts in to private/loopback targets for
diagnosing a stream on the operator's own machine; it is refused inside the
deployed container (`DOCKER_CONTAINER=1`).
"""

import ipaddress
import os
import socket
from collections.abc import Callable

import httpx

from media_ops_contracts.tool_failure import FailureKind, ToolFailure

ResolveHost = Callable[[str], list[str]]


def resolve_with_system_dns(host: str) -> list[str]:
    results = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({str(item[4][0]) for item in results})


def guard_fetch_target(
    url: str,
    *,
    allow_private: bool = False,
    resolve: ResolveHost = resolve_with_system_dns,
) -> None:
    """Raise ToolFailure unless `url` is safe to fetch right now."""
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL as error:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            f"The URL could not be parsed: {error}.",
            "Check the URL and try again.",
        ) from error
    if parsed.scheme not in ("http", "https"):
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            f"Unsupported URL scheme {parsed.scheme!r}; only http and https are fetched.",
            "Use an http or https URL.",
        )
    if allow_private and os.environ.get("DOCKER_CONTAINER") == "1":
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "HLS_ALLOW_PRIVATE_TARGETS is refused inside the deployed container.",
            "Unset HLS_ALLOW_PRIVATE_TARGETS, or diagnose the private stream locally.",
        )
    if allow_private:
        return
    host = parsed.host
    addresses = resolve_addresses(host, resolve)
    for address in addresses:
        if not is_global_unicast(address):
            raise ToolFailure(
                FailureKind.INVALID_REQUEST,
                f"Refusing to fetch {host!r}: it resolves to the non-global address {address}.",
                "Public streams only; set HLS_ALLOW_PRIVATE_TARGETS=true locally to"
                " diagnose a private one.",
            )


GuardedAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def resolve_addresses(host: str, resolve: ResolveHost) -> list[GuardedAddress]:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return [literal]
    try:
        resolved = resolve(host)
    except OSError as error:
        raise ToolFailure(
            FailureKind.EXTERNAL_SERVICE_UNAVAILABLE,
            f"The host {host!r} could not be resolved: {type(error).__name__}.",
            "Check the hostname and DNS, then retry.",
        ) from error
    addresses = []
    for text in resolved:
        try:
            addresses.append(ipaddress.ip_address(text.split("%")[0]))
        except ValueError:
            continue
    if not addresses:
        raise ToolFailure(
            FailureKind.EXTERNAL_SERVICE_UNAVAILABLE,
            f"The host {host!r} resolved to no usable address.",
            "Check the hostname and DNS, then retry.",
        )
    return addresses


def is_global_unicast(address: GuardedAddress) -> bool:
    return address.is_global and not address.is_multicast
