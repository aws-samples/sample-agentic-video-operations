"""The offline guard in the root conftest.py: only local connections get through."""

import socket

import pytest


@pytest.mark.parametrize(
    ("family", "address"),
    [
        (socket.AF_INET, ("169.254.169.254", 80)),  # the EC2 metadata endpoint boto3 tries
        (socket.AF_INET, ("192.0.2.1", 443)),  # TEST-NET-1
        (socket.AF_INET6, ("2001:db8::1", 443, 0, 0)),
        (socket.AF_INET, ("example.com", 443)),  # a name could resolve anywhere
    ],
)
def test_a_connection_off_this_machine_is_refused_and_recorded(offline, family, address):
    with socket.socket(family) as sock, pytest.raises(OSError, match="run offline"):
        sock.connect(address)

    assert offline == [address]
    offline.clear()  # recorded as the guard should; cleared so this test itself passes


@pytest.mark.parametrize(
    ("family", "address"),
    [
        (socket.AF_INET, ("127.0.0.1", 9)),
        (socket.AF_INET6, ("::1", 9, 0, 0)),
        (socket.AF_INET, ("localhost", 9)),
    ],
)
def test_a_local_connection_reaches_the_real_socket(offline, family, address):
    """Port 9 (discard) is closed here: the real connect refuses it, the guard doesn't."""
    with socket.socket(family) as sock, pytest.raises(OSError) as refused:
        sock.connect(address)

    assert "run offline" not in str(refused.value)
    assert offline == []
