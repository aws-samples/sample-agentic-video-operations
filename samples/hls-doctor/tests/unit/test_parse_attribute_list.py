from hls_doctor.domain.playlist.parse_attribute_list import (
    parse_attribute_list,
    parse_decimal,
    parse_integer,
    parse_resolution,
)


def test_quoted_values_may_contain_commas() -> None:
    attributes = parse_attribute_list('CODECS="avc1.640028,mp4a.40.2",BANDWIDTH=100')
    assert attributes["CODECS"] == "avc1.640028,mp4a.40.2"
    assert attributes["BANDWIDTH"] == "100"


def test_unquoted_hex_and_enum_values() -> None:
    attributes = parse_attribute_list("METHOD=AES-128,IV=0x1234,DEFAULT=YES")
    assert attributes == {"METHOD": "AES-128", "IV": "0x1234", "DEFAULT": "YES"}


def test_malformed_trailing_text_is_preserved() -> None:
    attributes = parse_attribute_list("BANDWIDTH=1,garbage")
    assert attributes["_TRAILING"] == "garbage"


def test_unterminated_quote_keeps_the_rest() -> None:
    attributes = parse_attribute_list('NAME="unterminated')
    assert attributes["NAME"] == "unterminated"


def test_value_parsers_tolerate_garbage() -> None:
    assert parse_decimal("6.006") == 6.006
    assert parse_decimal("x") is None and parse_decimal(None) is None
    assert parse_integer("42") == 42 and parse_integer("4.2") is None
    assert parse_resolution("1920x1080") == (1920, 1080)
    assert parse_resolution("wide") is None
