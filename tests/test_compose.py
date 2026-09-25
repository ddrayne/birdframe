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


def _pixel(png, xy):
    return Image.open(io.BytesIO(png)).convert("RGB").getpixel(xy)


def test_native_4_5_render_fills_the_art_area():
    green = (20, 120, 60)
    out = compose_final(_png_bytes(1200, 1504, green), datetime(2026, 7, 5), ["European Robin"])
    assert _pixel(out, (2, 2)) == green and _pixel(out, (1197, 1497)) == green


def test_small_near_4_5_render_is_scaled_up_to_fill():
    green = (20, 120, 60)                      # e.g. Gemini's 1K "4:5", 896x1152
    out = compose_final(_png_bytes(896, 1152, green), datetime(2026, 7, 5), ["European Robin"])
    assert _pixel(out, (2, 2)) == green and _pixel(out, (1197, 1497)) == green


def test_mismatched_2_3_render_is_letterboxed_not_cropped():
    out = compose_final(_png_bytes(1024, 1536, (20, 120, 60)), datetime(2026, 7, 5), ["Wren"])
    assert _pixel(out, (40, 700)) == (250, 248, 242)     # paper beside the art
    assert _pixel(out, (600, 700)) == (20, 120, 60)


def test_caption_is_pure_black_for_the_e_ink_palette():
    out = compose_final(_png_bytes(1200, 1504), datetime(2026, 7, 5), ["European Robin"])
    strip = Image.open(io.BytesIO(out)).convert("L").crop((0, 1500, 1200, 1600))
    assert strip.getextrema()[0] == 0


def test_caption_keeps_whole_names_and_counts_the_rest():
    from PIL import ImageDraw
    from birdframe.compose import _font, _names_line
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    names = [f"Eurasian Species Number {i}" for i in range(12)]
    line = _names_line(draw, names, _font(24), 1140)
    shown = line.rsplit(" + ", 1)[0].split(", ")
    assert line.endswith(f" + {12 - len(shown)} more")
    assert all(name in names for name in shown)          # no name cut mid-word
    assert _names_line(draw, names[:2], _font(24), 1140) == ", ".join(names[:2])


def test_eink_preview_uses_only_the_panels_six_blended_inks():
    from birdframe.compose import eink_preview
    art = Image.new("RGB", (120, 160))
    art.putdata([(x * 2 % 256, y % 256, (x * y) % 256) for y in range(160) for x in range(120)])
    buf = io.BytesIO()
    art.save(buf, format="PNG")
    printed = Image.open(io.BytesIO(eink_preview(buf.getvalue(), saturation=0.6))).convert("RGB")
    assert printed.size == (120, 160)
    blended = {(0, 0, 0), (199, 200, 201), (227, 216, 43), (196, 43, 45), (37, 35, 158), (35, 157, 42)}
    assert {colour for _, colour in printed.getcolors(1000)} <= blended
