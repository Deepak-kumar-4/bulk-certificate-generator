"""Certificate renderer: recipient data in, PDF bytes out.

Knows nothing about the database, HTTP or the filesystem layout of generated files. Any
problem that would produce a wrong-looking certificate raises RenderError instead, so the
processor can mark that one row FAILED and carry on.
"""

import io
from datetime import date
from pathlib import Path

from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONT_REGULAR = "DejaVuSans"
FONT_BOLD = "DejaVuSans-Bold"

PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)
CONTENT_WIDTH = PAGE_WIDTH - 2 * 80  # text must stay clear of the border

NAME_MAX_SIZE = 40
NAME_MIN_SIZE = 10  # a typical 100-character name (the validation limit) fits
EVENT_MAX_SIZE = 24
EVENT_MIN_SIZE = 12
FOOTER_MAX_SIZE = 13
FOOTER_MIN_SIZE = 8
FOOTER_COLUMN_WIDTH = 240

NAVY = Color(0.10, 0.17, 0.32)
GOLD = Color(0.72, 0.56, 0.22)
INK = Color(0.20, 0.20, 0.22)
MUTED = Color(0.45, 0.45, 0.48)
PAPER = Color(0.995, 0.985, 0.955)


class RenderError(ValueError):
    """Raised when a certificate cannot be rendered correctly."""


def _register_fonts() -> None:
    registered = pdfmetrics.getRegisteredFontNames()
    for name, filename in ((FONT_REGULAR, "DejaVuSans.ttf"), (FONT_BOLD, "DejaVuSans-Bold.ttf")):
        if name not in registered:
            pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / filename)))


_register_fonts()


def _check_glyphs(text: str, field: str) -> None:
    """Refuse text the bundled font cannot draw, instead of silently printing boxes."""
    glyphs = pdfmetrics.getFont(FONT_REGULAR).face.charToGlyph
    missing = sorted({ch for ch in text if not ch.isspace() and ord(ch) not in glyphs})
    if missing:
        shown = "".join(missing[:5])
        raise RenderError(
            f"{field} contains characters the certificate font cannot display: {shown}"
        )


def fit_font_size(
    text: str, font: str, max_width: float, max_size: float, min_size: float
) -> float:
    """Largest size (stepping down by 1pt) at which `text` fits in `max_width`.

    Raises RenderError if it does not fit even at `min_size`.
    """
    size = max_size
    while size >= min_size:
        if pdfmetrics.stringWidth(text, font, size) <= max_width:
            return size
        size -= 1
    raise RenderError(f"text is too long to fit on the certificate: {text[:40]!r}")


def format_date(value: date) -> str:
    return f"{value.day} {value:%B %Y}"


def _draw_frame(c: Canvas) -> None:
    c.setFillColor(PAPER)
    c.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, stroke=0, fill=1)

    c.setStrokeColor(NAVY)
    c.setLineWidth(6)
    c.rect(22, 22, PAGE_WIDTH - 44, PAGE_HEIGHT - 44)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.5)
    c.rect(34, 34, PAGE_WIDTH - 68, PAGE_HEIGHT - 68)

    # Small diamonds in each corner of the inner border.
    c.setFillColor(GOLD)
    for x, y in (
        (34, 34),
        (PAGE_WIDTH - 34, 34),
        (34, PAGE_HEIGHT - 34),
        (PAGE_WIDTH - 34, PAGE_HEIGHT - 34),
    ):
        path = c.beginPath()
        path.moveTo(x, y + 9)
        path.lineTo(x + 9, y)
        path.lineTo(x, y - 9)
        path.lineTo(x - 9, y)
        path.close()
        c.drawPath(path, stroke=0, fill=1)


def _centered(c: Canvas, text: str, y: float, font: str, size: float, color: Color) -> None:
    c.setFont(font, size)
    c.setFillColor(color)
    c.drawCentredString(PAGE_WIDTH / 2, y, text)


def _signature_block(c: Canvas, x_center: float, value: str, label: str) -> None:
    size = fit_font_size(value, FONT_BOLD, FOOTER_COLUMN_WIDTH, FOOTER_MAX_SIZE, FOOTER_MIN_SIZE)
    c.setFont(FONT_BOLD, size)
    c.setFillColor(INK)
    c.drawCentredString(x_center, 112, value)
    c.setStrokeColor(GOLD)
    c.setLineWidth(0.8)
    c.line(x_center - FOOTER_COLUMN_WIDTH / 2, 104, x_center + FOOTER_COLUMN_WIDTH / 2, 104)
    c.setFont(FONT_REGULAR, 10)
    c.setFillColor(MUTED)
    c.drawCentredString(x_center, 90, label)


def render(
    *,
    recipient_name: str,
    event_name: str,
    issuer_name: str,
    issue_date: date,
    certificate_number: str,
) -> bytes:
    """Render one certificate and return the PDF as bytes."""
    for value, field in (
        (recipient_name, "name"),
        (event_name, "event name"),
        (issuer_name, "issuer name"),
    ):
        if not value or not value.strip():
            raise RenderError(f"{field} is empty")
        _check_glyphs(value, field)

    name_size = fit_font_size(
        recipient_name, FONT_BOLD, CONTENT_WIDTH, NAME_MAX_SIZE, NAME_MIN_SIZE
    )
    event_size = fit_font_size(event_name, FONT_BOLD, CONTENT_WIDTH, EVENT_MAX_SIZE, EVENT_MIN_SIZE)

    buffer = io.BytesIO()
    c = Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT), invariant=1)
    c.setTitle(f"Certificate of Completion - {recipient_name}")
    c.setAuthor(issuer_name)
    c.setSubject(event_name)

    _draw_frame(c)

    _centered(c, "Certificate of Completion", 470, FONT_BOLD, 34, NAVY)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.2)
    c.line(PAGE_WIDTH / 2 - 110, 452, PAGE_WIDTH / 2 + 110, 452)

    _centered(c, "This is to certify that", 395, FONT_REGULAR, 15, MUTED)
    _centered(c, recipient_name, 335, FONT_BOLD, name_size, INK)
    _centered(c, "has successfully completed", 275, FONT_REGULAR, 15, MUTED)
    _centered(c, event_name, 225, FONT_BOLD, event_size, NAVY)

    _signature_block(c, PAGE_WIDTH * 0.28, format_date(issue_date), "Date of issue")
    _signature_block(c, PAGE_WIDTH * 0.72, issuer_name, "Issued by")

    c.setFont(FONT_REGULAR, 8)
    c.setFillColor(MUTED)
    c.drawRightString(PAGE_WIDTH - 48, 46, f"Certificate No. {certificate_number}")

    c.showPage()
    c.save()
    return buffer.getvalue()
