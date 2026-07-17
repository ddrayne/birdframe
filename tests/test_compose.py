import io
from datetime import datetime

from PIL import Image

from birdframe.compose import compose_final, fallback_poster


def _png_bytes(w, h, colour=(120, 90, 60)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


def test_compose_final_is_exact_frame_size():
    art = _png_bytes(1024, 1536)
    out = compose_final(art, date=datetime(2026, 7, 5),
                        species=["European Robin", "Common Blackbird"])
    img = Image.open(io.BytesIO(out))
    assert img.size == (1200, 1600)
    assert img.format == "PNG"


def test_fallback_poster_is_exact_frame_size():
    out = fallback_poster(date=datetime(2026, 7, 5),
                          species=["European Robin", "Common Blackbird"])
    img = Image.open(io.BytesIO(out))
    assert img.size == (1200, 1600)


def test_compose_handles_empty_species():
    art = _png_bytes(1024, 1536)
    out = compose_final(art, date=datetime(2026, 7, 5), species=[])
    assert Image.open(io.BytesIO(out)).size == (1200, 1600)


def test_compose_handles_very_long_species_list():
    art = _png_bytes(1024, 1536)
    out = compose_final(art, date=datetime(2026, 7, 5),
                        species=[f"Species number {i}" for i in range(30)])
    assert Image.open(io.BytesIO(out)).size == (1200, 1600)


def test_caption_label_renders_differently():
    from birdframe.compose import compose_final, fallback_poster
    from datetime import datetime
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (1024, 1536), (90, 110, 90)).save(buf, format="PNG")
    art = buf.getvalue()
    when = datetime(2026, 7, 5, 6, 30)
    plain = compose_final(art, when, ["European Robin"])
    labelled = compose_final(art, when, ["European Robin"], label="dawn")
    assert plain != labelled                     # the label is drawn in the caption
    assert fallback_poster(when, ["European Robin"]) != \
        fallback_poster(when, ["European Robin"], label="dawn")
