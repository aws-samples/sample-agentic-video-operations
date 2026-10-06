from pathlib import Path

TEMPLATE = Path("samples/cmcd/cloudfront-cmcd-kinesis.yaml")


def test_player_pins_hls_js_with_integrity_and_suppresses_favicon_request():
    template = TEMPLATE.read_text()

    assert "hls.js@latest" not in template
    assert "hls.js@1.6.16/dist/hls.min.js" in template
    assert (
        'integrity="sha384-5E8B0pTlZZJMabWpC0fyYf6OUpe15jJij34BqBAh4NXoHAlLNOjCPRrwtOXOQFAn"'
    ) in template
    assert 'crossorigin="anonymous"' in template
    assert '<link rel="icon" href="data:,">' in template


def test_player_status_messages_are_text_not_html():
    player = TEMPLATE.read_text().split('index_html = f"""', 1)[1].split('"""', 1)[0]

    assert "innerHTML" not in player and "outerHTML" not in player
    assert "line.textContent = message;" in player
    assert "statusDiv.replaceChildren(line);" in player
