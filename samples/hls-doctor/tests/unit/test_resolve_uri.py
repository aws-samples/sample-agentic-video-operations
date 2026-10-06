from hls_doctor.domain.playlist.multivariant_model import DefineTag
from hls_doctor.domain.playlist.resolve_uri import (
    build_variable_table,
    resolve_uri,
    substitute_variables,
)

BASE = "https://demo.example/vod/master.m3u8?auth=t"


def test_relative_and_absolute_resolution() -> None:
    assert resolve_uri("v1/prog.m3u8", BASE) == "https://demo.example/vod/v1/prog.m3u8"
    assert resolve_uri("/keys/k.bin", BASE) == "https://demo.example/keys/k.bin"
    assert resolve_uri("https://other.example/x.m3u8", BASE) == "https://other.example/x.m3u8"


def test_define_name_value_substitution() -> None:
    table = build_variable_table([DefineTag(line_number=1, name="cdn", value="edge-1")], BASE)
    assert substitute_variables("https://{$cdn}.example/seg.ts", table) == (
        "https://edge-1.example/seg.ts"
    )


def test_define_queryparam_reads_the_base_url() -> None:
    table = build_variable_table([DefineTag(line_number=1, queryparam="auth")], BASE)
    assert table["auth"] == "t"


def test_unknown_variables_stay_verbatim() -> None:
    assert substitute_variables("seg-{$missing}.ts", {}) == "seg-{$missing}.ts"
