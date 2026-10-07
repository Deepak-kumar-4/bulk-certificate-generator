import io
from datetime import date

import pytest
from pypdf import PdfReader
from reportlab.pdfbase import pdfmetrics

from app.services import renderer
from app.services.renderer import RenderError, fit_font_size, render
from app.services.validation import NAME_MAX_LENGTH


def render_for(name: str, **overrides) -> bytes:
    kwargs = {
        "recipient_name": name,
        "event_name": "Python Bootcamp 2026",
        "issuer_name": "Deetag Academy",
        "issue_date": date(2026, 10, 1),
        "certificate_number": "CERT-2026-8F3A2C1D9E0B",
    }
    kwargs.update(overrides)
    return render(**kwargs)


def pdf_text(pdf: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 1
    return reader.pages[0].extract_text()


def test_render_returns_pdf_bytes():
    pdf = render_for("Asha Rao")

    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF")


def test_pdf_contains_name_event_issuer_date_and_number():
    text = pdf_text(render_for("Asha Rao"))

    assert "Certificate of Completion" in text
    assert "Asha Rao" in text
    assert "Python Bootcamp 2026" in text
    assert "Deetag Academy" in text
    assert "1 October 2026" in text
    assert "CERT-2026-8F3A2C1D9E0B" in text


def test_page_is_a4_landscape():
    page = PdfReader(io.BytesIO(render_for("Asha Rao"))).pages[0]

    assert round(float(page.mediabox.width)) == 842
    assert round(float(page.mediabox.height)) == 595


def test_very_long_name_is_shrunk_to_fit():
    name = ("Bartholomew Alexander " * 5)[:NAME_MAX_LENGTH].strip()

    size = fit_font_size(
        name,
        renderer.FONT_BOLD,
        renderer.CONTENT_WIDTH,
        renderer.NAME_MAX_SIZE,
        renderer.NAME_MIN_SIZE,
    )

    assert renderer.NAME_MIN_SIZE <= size < renderer.NAME_MAX_SIZE
    assert pdfmetrics.stringWidth(name, renderer.FONT_BOLD, size) <= renderer.CONTENT_WIDTH
    assert name in pdf_text(render_for(name))


def test_short_name_uses_full_size():
    size = fit_font_size(
        "Asha Rao",
        renderer.FONT_BOLD,
        renderer.CONTENT_WIDTH,
        renderer.NAME_MAX_SIZE,
        renderer.NAME_MIN_SIZE,
    )

    assert size == renderer.NAME_MAX_SIZE


def test_name_too_wide_even_at_minimum_size_raises():
    with pytest.raises(RenderError, match="too long"):
        render_for("W" * NAME_MAX_LENGTH)


def test_accented_name_renders():
    name = "José Núñez Ångström-Øberg"

    text = pdf_text(render_for(name))

    assert name in text


def test_characters_missing_from_font_raise_instead_of_printing_boxes():
    with pytest.raises(RenderError, match="cannot display"):
        render_for("田中太郎")


def test_blank_name_raises():
    with pytest.raises(RenderError, match="name is empty"):
        render_for("   ")


def test_render_does_not_touch_the_filesystem(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    render_for("Asha Rao")

    assert list(tmp_path.iterdir()) == []
