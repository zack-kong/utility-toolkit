from server.app.languages import translation_source_for


def test_common_language_mapping() -> None:
    assert translation_source_for("en") == "en"
    assert translation_source_for("ja") == "ja"
    assert translation_source_for("sv") is None
    assert translation_source_for("unknown") is None
