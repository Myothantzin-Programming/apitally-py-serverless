from apitally_serverless.common.headers import convert_headers, is_supported_content_type, parse_content_length


def test_convert_headers():
    assert convert_headers(None) == []
    assert convert_headers([("Content-Type", "application/json")]) == [("content-type", "application/json")]


def test_parse_content_length():
    assert parse_content_length(None) is None
    assert parse_content_length(123) == 123
    assert parse_content_length("456") == 456
    assert parse_content_length(b"789") == 789
    assert parse_content_length("invalid") is None


def test_is_supported_content_type():
    assert is_supported_content_type(None) is False
    assert is_supported_content_type("") is False
    assert is_supported_content_type("application/json") is True
    assert is_supported_content_type("application/json; charset=utf-8") is True
    assert is_supported_content_type("application/octet-stream") is False
