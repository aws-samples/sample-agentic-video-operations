from pathlib import Path

README = Path("samples/cmcd/README.md")


def test_test_stream_is_sustained_and_multivariant():
    text = README.read_text()

    assert "-t 180" in text
    assert "-master_pl_name master.m3u8" in text
    assert "-var_stream_map" in text
    assert "-b:v:0 2800k" in text
    assert "-b:v:1 900k" in text
    assert "`smoke write/read: passed`" in text
