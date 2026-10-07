"""Every test suite here runs offline: a connection off this machine fails the test.

The guard is not hypothetical. A Hydrolix test built a real AgentCore MemoryClient, and boto3
went looking for credentials at the EC2 metadata endpoint: about a second per request off
AWS, and on AWS it would have answered. botocore's credential chain swallows connection
errors, so the guard records each attempt and fails the test at teardown rather than relying
on the error reaching it. Loopback and Unix sockets stay allowed: local servers and asyncio's
own plumbing use them.
"""

import ipaddress
import socket

import pytest

REAL_CONNECT = socket.socket.connect


def leaves_this_machine(address: object) -> bool:
    """An (ip, port, ...) address that isn't loopback. Unix sockets and loopback stay local."""
    if not isinstance(address, tuple) or not address:
        return False
    try:
        return not ipaddress.ip_address(address[0]).is_loopback
    except ValueError:  # a name: "localhost" is local, any other name could resolve anywhere
        return address[0] != "localhost"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    attempts: list[object] = []

    def connect(sock: socket.socket, address: object) -> None:
        if leaves_this_machine(address):
            attempts.append(address)
            raise OSError(f"tests run offline; refused a connection to {address!r}")
        REAL_CONNECT(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    yield attempts
    if attempts:
        pytest.fail(f"this test tried to reach the network: {attempts}", pytrace=False)
