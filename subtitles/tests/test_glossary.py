import pytest

from server.app.glossary import matching_terms, parse_glossary
from server.app.term_packs import terms_for


def test_builtin_names_are_specific_not_ambiguous_surnames() -> None:
    assert matching_terms("ドナルド・ダックが来た！", "ja") == [("ドナルド・ダック", "唐老鸭")]
    assert matching_terms("ドナルドダックが来た！", "ja") == [("ドナルドダック", "唐老鸭")]
    assert matching_terms("ドナルドが来た！", "ja") == []
    assert matching_terms("Donald Duck arrived", "en") == [("Donald Duck", "唐老鸭")]
    assert matching_terms("Donald arrived", "en") == []


def test_user_glossary_can_override_or_add_names() -> None:
    raw = "# 这部影片\nja|ドナルド = 唐老鸭\nja|ドナルド・ダック = 唐老鸭叔叔\n"
    assert matching_terms("ドナルド・ダックとドナルド", "ja", raw) == [
        ("ドナルド・ダック", "唐老鸭叔叔"), ("ドナルド", "唐老鸭")]
    assert matching_terms("Donald Duck", "en", raw) == [("Donald Duck", "唐老鸭")]
    assert matching_terms("マクドナルドへ行こう", "ja", raw) == []


def test_invalid_glossary_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_glossary("ドナルド 唐老鸭")
    with pytest.raises(ValueError):
        parse_glossary("xx|Donald = 唐老鸭")
    with pytest.raises(ValueError):
        parse_glossary("a" * 4001)


def test_four_offline_term_files_and_user_override() -> None:
    for language, source in (("en", "Mickey Mouse"), ("ja", "ミッキーマウス"),
                             ("ko", "미키 마우스"), ("es", "Mickey Mouse")):
        preset = terms_for(language)
        assert (source, "米老鼠") in preset
        assert matching_terms(source, language, preset=preset) == [(source, "米老鼠")]
    assert terms_for("fr") == ()
    assert matching_terms("Mickey Mouse", "en", "en|Mickey Mouse = 自定义译名",
                          terms_for("en")) == [("Mickey Mouse", "自定义译名")]
