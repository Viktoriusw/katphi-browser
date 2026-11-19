"""Tests del aviso de vídeo no reproducible (media_support)."""


def test_media_warning_requires_play_intent_and_visible_video():
    """El aviso no puede saltar por consultas de códecs de scripts de anuncios."""
    import media_support
    js = media_support._DETECT_JS
    assert "intents" in js and "bigVisible" in js
    # La consulta de códecs ya no basta: failed() exige un vídeo atascado con intención
    assert "st.miss && stuckVideo()" in js
