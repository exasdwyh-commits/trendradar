import json

import pytest

from trendradar.core.errors import NotConfigured, SourceError, ValidationFailed
from trendradar.studio.materials import create_material, get_material, update_material


@pytest.fixture()
def translator(monkeypatch):
    from trendradar.studio import translations

    class Translator:
        calls = []

        def slot_enabled(self, slot):
            return True

        def chat_json(self, slot, system, user, **kwargs):
            payload = json.loads(user)
            payload["slot"] = slot
            self.calls.append(payload)
            return {
                "title": "中文标题",
                "content": "中文译文 " + payload.get("content", ""),
            }, "test-translator"

    provider = Translator()
    monkeypatch.setattr(translations, "get_llm", lambda: provider)
    monkeypatch.setattr(translations, "writing_slot", lambda: "WRITING_MODEL")
    return provider


def test_translation_preserves_original_and_reuses_cache(conn, translator):
    from trendradar.studio.translations import translate

    mid = create_material(conn, kind="note", title="English title", content="Revenue grew 20%.")
    first = translate(conn, "material", mid)
    assert first["title"] == "中文标题" and first["model"] == "test-translator"
    assert get_material(conn, mid)["title"] == "English title"
    assert get_material(conn, mid)["content"] == "Revenue grew 20%."
    second = translate(conn, "material", mid)
    assert second["cached"] and len(translator.calls) == 1
    update_material(conn, mid, {"content": "Revenue grew 30%."})
    assert not translate(conn, "material", mid)["cached"]
    assert len(translator.calls) == 2


def test_translation_sends_all_long_content(conn, translator):
    from trendradar.studio.translations import translate

    content = "A long English paragraph.\n" * 500
    mid = create_material(conn, kind="note", title="Long article", content=content)
    translate(conn, "material", mid)
    assert "".join(call["content"] for call in translator.calls) == content
    assert len(translator.calls) > 1


def test_translation_without_model_never_fabricates(conn):
    from trendradar.studio.translations import translate

    mid = create_material(conn, kind="note", title="English title", content="Original article", origin="mock")
    with pytest.raises(NotConfigured):
        translate(conn, "material", mid)


def test_empty_translation_is_not_cached(conn, translator):
    from trendradar.studio.translations import translate

    translator.chat_json = lambda *args, **kwargs: ({"title": "中文标题", "content": ""}, "test-translator")
    mid = create_material(conn, kind="note", title="English title", content="Original article")
    with pytest.raises(ValidationFailed):
        translate(conn, "material", mid)
    assert conn.execute("SELECT COUNT(*) FROM article_translations").fetchone()[0] == 0


def test_partial_translation_failure_is_not_cached(conn, translator):
    from trendradar.studio.translations import translate

    original_chat = translator.chat_json

    def fail_second(*args, **kwargs):
        if translator.calls:
            raise RuntimeError("Provider unavailable")
        return original_chat(*args, **kwargs)

    translator.chat_json = fail_second
    mid = create_material(conn, kind="note", title="Long article", content="English text " * 500)
    with pytest.raises(SourceError, match="原文已保留"):
        translate(conn, "material", mid)
    assert conn.execute("SELECT COUNT(*) FROM article_translations").fetchone()[0] == 0


def test_title_uses_fast_model_without_sending_body_and_caches_independently(conn, translator):
    from trendradar.studio.translations import get_translation, translate

    mid = create_material(conn, kind="note", title="English title", content="Private long article " * 6000)
    first = translate(conn, "material", mid, "title")
    assert first["content"] == first["original_content"] == ""
    assert translator.calls == [{"title": "English title", "slot": "FAST_MODEL"}]
    assert get_translation(conn, "material", mid, "full") is None
    update_material(conn, mid, {"content": "A changed English article"})
    assert translate(conn, "material", mid, "title")["cached"]
    assert len(translator.calls) == 1
    full = translate(conn, "material", mid, "full")
    assert full["content"] and translator.calls[-1]["slot"] == "WRITING_MODEL"
    update_material(conn, mid, {"title": "New English title"})
    assert get_translation(conn, "material", mid, "title") is None


def test_existing_full_translation_provides_title_without_model_call(conn, translator):
    from trendradar.studio.translations import translate

    mid = create_material(conn, kind="note", title="English title", content="Original article")
    translate(conn, "material", mid, "full")
    title = translate(conn, "material", mid, "title")
    assert title["cached"] and title["content"] == title["original_content"] == ""
    assert len(translator.calls) == 1
