import verify_influxdb_read_token


def test_verification_uses_the_deployed_bucket_from_the_environment(monkeypatch):
    received = []
    monkeypatch.setenv("INFLUXDB_URL", "https://localhost:8086")
    monkeypatch.setenv("INFLUXDB_ORG", "cmcd-org")
    monkeypatch.setenv("INFLUXDB_BUCKET", "event-specific-cmcd")
    monkeypatch.setenv("INFLUXDB_TOKEN", "read-token")
    monkeypatch.setattr(
        verify_influxdb_read_token,
        "verify_influxdb_read_token",
        lambda *arguments: received.append(arguments),
    )

    assert verify_influxdb_read_token.main() == 0
    assert received == [
        (
            "https://localhost:8086",
            "cmcd-org",
            "event-specific-cmcd",
            "read-token",
        )
    ]


def test_verification_uses_the_template_default_when_the_bucket_is_empty(monkeypatch):
    received = []
    monkeypatch.setenv("INFLUXDB_URL", "https://localhost:8086")
    monkeypatch.setenv("INFLUXDB_ORG", "cmcd-org")
    monkeypatch.setenv("INFLUXDB_BUCKET", "")
    monkeypatch.setenv("INFLUXDB_TOKEN", "read-token")
    monkeypatch.setattr(
        verify_influxdb_read_token,
        "verify_influxdb_read_token",
        lambda *arguments: received.append(arguments),
    )

    assert verify_influxdb_read_token.main() == 0
    assert received[0][2] == "cmcd-metrics"
