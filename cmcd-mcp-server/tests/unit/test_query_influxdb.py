from types import SimpleNamespace

from cmcd_mcp.adapters.influxdb import query_influxdb as query_module


def test_query_influxdb_builds_the_client_with_keyword_arguments(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.closed = False

        def query_api(self):
            record = SimpleNamespace(values={"_time": "2026-10-05T12:00:00Z", "_value": 1})
            return SimpleNamespace(query=lambda **_: [SimpleNamespace(records=[record])])

        def close(self):
            self.closed = True

    monkeypatch.setattr(query_module, "InfluxDBClient", FakeClient)
    records = query_module.query_influxdb(
        "flux",
        url="https://influxdb.example.com",
        token="token",
        org="org",
        verify_ssl=True,
    )
    assert records == [{"_time": "2026-10-05T12:00:00Z", "_value": 1}]
    assert captured == {
        "url": "https://influxdb.example.com",
        "token": "token",
        "org": "org",
        "timeout": 10_000,
        "verify_ssl": True,
    }
