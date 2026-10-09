"""The certificate template and its renderer.

A single predefined template, drawn with ReportLab's canvas API on A4
landscape. ReportLab was chosen over an HTML-to-PDF pipeline (WeasyPrint,
wkhtmltopdf) because it is pure Python with no system libraries to install —
the project therefore behaves identically on Windows, Linux and inside Docker,
which matters for a reviewer cloning the repo. See the README for the full
comparison.

Only ReportLab's built-in Type 1 fonts are used, so no font binaries are
committed to the repository. Those fonts cover Latin-1; a name containing
characters outside that range (Devanagari, for example) is detected up front
and reported as a generation failure rather than silently rendered as blank
boxes. Set ``CERTIFICATE_FONT_PATH`` to a TrueType file to lift that limit.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# --------------------------------------------------------------------------- #
# Template constants
# --------------------------------------------------------------------------- #

PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)  # 842 x 595 pt

NAVY = HexColor("#1B2A4A")
GOLD = HexColor("#B8893B")
INK = HexColor("#1A1A1A")
MUTED = HexColor("#5B6475")
PAPER = HexColor("#FDFCF9")

# Built-in Type 1 faces — always available, never shipped as files.
SERIF = "Times-Roman"
SERIF_BOLD = "Times-Bold"
SERIF_ITALIC = "Times-Italic"
SERIF_BOLD_ITALIC = "Times-BoldItalic"
SANS = "Helvetica"
SANS_BOLD = "Helvetica-Bold"

_CUSTOM_FONT_NAME = "CertificateCustom"
_custom_font_loaded: bool | None = None


class CertificateRenderError(RuntimeError):
    """Raised when one certificate cannot be rendered.

    The worker catches this per recipient, so one unrenderable name never
    stops the rest of the batch.
    """


# --------------------------------------------------------------------------- #
# Font handling
# --------------------------------------------------------------------------- #


def _load_custom_font() -> bool:
    """Register the TTF at ``CERTIFICATE_FONT_PATH``, if one is configured.

    Returns True when a custom font is available for use. The result is cached
    because ReportLab's font registry is process-global.
    """
    global _custom_font_loaded
    if _custom_font_loaded is not None:
        return _custom_font_loaded

    font_path = os.getenv("CERTIFICATE_FONT_PATH", "").strip()
    if not font_path or not Path(font_path).is_file():
        _custom_font_loaded = False
        return False

    try:
        pdfmetrics.registerFont(TTFont(_CUSTOM_FONT_NAME, font_path))
        _custom_font_loaded = True
    except Exception:  # noqa: BLE001 - a bad font must not break the service
        _custom_font_loaded = False
    return _custom_font_loaded


def _resolve_font(preferred: str) -> str:
    """Use the custom TTF when configured, otherwise the built-in face."""
    return _CUSTOM_FONT_NAME if _load_custom_font() else preferred


def _assert_renderable(**fields: str | None) -> None:
    """Reject text the active font cannot represent.

    Failing loudly here is deliberate: a certificate with the recipient's name
    rendered as empty boxes is worse than a certificate that is reported as
    failed, because the first error is silent and reaches the recipient.
    """
    if _load_custom_font():
        return  # a TrueType font is embedded; assume broad coverage

    for field_name, value in fields.items():
        if not value:
            continue
        try:
            value.encode("latin-1")
        except UnicodeEncodeError as exc:
            bad = value[exc.start : exc.end]
            raise CertificateRenderError(
                f"{field_name} contains characters the built-in font cannot render "
                f"({bad!r}). Set CERTIFICATE_FONT_PATH to a TrueType font that "
                f"supports this script."
            ) from exc


# --------------------------------------------------------------------------- #
# Text layout helpers
# --------------------------------------------------------------------------- #


def _fit_font_size(
    text: str, font: str, max_width: float, start_size: float, min_size: float
) -> float:
    """Largest size at or below ``start_size`` where ``text`` fits one line."""
    size = start_size
    while size > min_size and pdfmetrics.stringWidth(text, font, size) > max_width:
        size -= 0.5
    return size


def _wrap(text: str, font: str, size: float, max_width: float, max_lines: int) -> list[str]:
    """Greedy word wrap, truncating with an ellipsis past ``max_lines``."""
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = words[0]
    truncated = False

    for word in words[1:]:
        candidate = f"{current} {word}"
        if pdfmetrics.stringWidth(candidate, font, size) <= max_width:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) == max_lines:
            # No room left: whatever remains is dropped.
            truncated = True
            break

    if not truncated:
        lines.append(current)

    # A single word longer than the line is hard-truncated character-wise.
    if len(lines) == 1 and pdfmetrics.stringWidth(lines[0], font, size) > max_width:
        truncated = True

    if truncated:
        last = lines[-1]
        while last and pdfmetrics.stringWidth(f"{last}...", font, size) > max_width:
            last = last[:-1].rstrip()
        lines[-1] = f"{last}..."

    return lines[:max_lines]


def _letterspaced(
    pdf: canvas.Canvas, text: str, font: str, size: float, tracking: float, centre_x: float, y: float
) -> None:
    """Draw text centred on ``centre_x`` with extra space between glyphs."""
    width = pdfmetrics.stringWidth(text, font, size) + tracking * (len(text) - 1)
    x = centre_x - width / 2
    pdf.setFont(font, size)
    for char in text:
        pdf.drawString(x, y, char)
        x += pdfmetrics.stringWidth(char, font, size) + tracking


def _rule(pdf: canvas.Canvas, centre_x: float, y: float, width: float, colour: Color, thickness: float) -> None:
    pdf.setStrokeColor(colour)
    pdf.setLineWidth(thickness)
    pdf.line(centre_x - width / 2, y, centre_x + width / 2, y)


# --------------------------------------------------------------------------- #
# The template
# --------------------------------------------------------------------------- #


def _draw_borders(pdf: canvas.Canvas) -> None:
    pdf.setFillColor(PAPER)
    pdf.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, stroke=0, fill=1)

    outer = 10 * mm
    pdf.setStrokeColor(NAVY)
    pdf.setLineWidth(2.2)
    pdf.rect(outer, outer, PAGE_WIDTH - 2 * outer, PAGE_HEIGHT - 2 * outer, stroke=1, fill=0)

    inner = 13.5 * mm
    pdf.setStrokeColor(GOLD)
    pdf.setLineWidth(0.7)
    pdf.rect(inner, inner, PAGE_WIDTH - 2 * inner, PAGE_HEIGHT - 2 * inner, stroke=1, fill=0)

    # Small gold corner accents.
    pdf.setLineWidth(1.4)
    arm = 7 * mm
    for cx, cy, dx, dy in (
        (inner, inner, 1, 1),
        (PAGE_WIDTH - inner, inner, -1, 1),
        (inner, PAGE_HEIGHT - inner, 1, -1),
        (PAGE_WIDTH - inner, PAGE_HEIGHT - inner, -1, -1),
    ):
        pdf.line(cx, cy, cx + arm * dx, cy)
        pdf.line(cx, cy, cx, cy + arm * dy)


def _draw_seal(pdf: canvas.Canvas, x: float, y: float, initials: str) -> None:
    """A restrained medallion: two rings and the organisation's initials."""
    pdf.setStrokeColor(GOLD)
    pdf.setLineWidth(1.6)
    pdf.circle(x, y, 21, stroke=1, fill=0)
    pdf.setLineWidth(0.6)
    pdf.circle(x, y, 16, stroke=1, fill=0)

    font = _resolve_font(SANS_BOLD)
    size = _fit_font_size(initials, font, 24, 11, 6)
    pdf.setFillColor(GOLD)
    pdf.setFont(font, size)
    pdf.drawCentredString(x, y - size / 3, initials)


def _initials(organization_name: str) -> str:
    parts = [p for p in organization_name.split() if p[:1].isalnum()]
    return "".join(p[0].upper() for p in parts[:3]) or "CERT"


def render_certificate(
    *,
    recipient_name: str,
    course_name: str,
    issue_date: date,
    certificate_number: str,
    organization_name: str,
    signatory_name: str,
    signatory_title: str,
    output_path: str | Path,
) -> int:
    """Render one certificate to ``output_path`` and return its size in bytes.

    Raises:
        CertificateRenderError: if the content cannot be rendered or written.
    """
    if not recipient_name or not recipient_name.strip():
        raise CertificateRenderError("recipient_name is empty; nothing to render")

    _assert_renderable(
        recipient_name=recipient_name,
        course_name=course_name,
        organization_name=organization_name,
        signatory_name=signatory_name,
        signatory_title=signatory_title,
    )

    output_path = Path(output_path)
    centre = PAGE_WIDTH / 2

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pdf = canvas.Canvas(str(output_path), pagesize=landscape(A4))
        pdf.setTitle(f"Certificate {certificate_number}")
        pdf.setAuthor(organization_name)
        pdf.setSubject(course_name)

        _draw_borders(pdf)

        # Organisation
        pdf.setFillColor(NAVY)
        _letterspaced(
            pdf, organization_name.upper(), _resolve_font(SANS_BOLD), 10.5, 2.4, centre, 500
        )

        # Headline
        pdf.setFillColor(INK)
        _letterspaced(pdf, "CERTIFICATE", _resolve_font(SERIF_BOLD), 40, 5.5, centre, 432)
        pdf.setFillColor(MUTED)
        _letterspaced(pdf, "OF COMPLETION", _resolve_font(SANS), 12, 4.2, centre, 408)

        _rule(pdf, centre, 392, 150, GOLD, 1.1)

        # Citation
        pdf.setFillColor(MUTED)
        pdf.setFont(_resolve_font(SERIF_ITALIC), 13)
        pdf.drawCentredString(centre, 356, "This is to certify that")

        # Recipient
        name_font = _resolve_font(SERIF_BOLD)
        name_size = _fit_font_size(recipient_name, name_font, PAGE_WIDTH - 180, 34, 14)
        if pdfmetrics.stringWidth(recipient_name, name_font, name_size) > PAGE_WIDTH - 180:
            recipient_display = _wrap(recipient_name, name_font, name_size, PAGE_WIDTH - 180, 1)[0]
        else:
            recipient_display = recipient_name
        pdf.setFillColor(NAVY)
        pdf.setFont(name_font, name_size)
        pdf.drawCentredString(centre, 310, recipient_display)

        name_width = pdfmetrics.stringWidth(recipient_display, name_font, name_size)
        _rule(pdf, centre, 296, min(name_width + 70, 560), GOLD, 0.8)

        # Course
        pdf.setFillColor(MUTED)
        pdf.setFont(_resolve_font(SERIF), 12.5)
        pdf.drawCentredString(centre, 266, "has successfully completed")

        course_font = _resolve_font(SERIF_BOLD_ITALIC)
        course_size = _fit_font_size(course_name, course_font, PAGE_WIDTH - 220, 18, 12)
        course_lines = _wrap(course_name, course_font, course_size, PAGE_WIDTH - 220, 2)
        pdf.setFillColor(INK)
        pdf.setFont(course_font, course_size)
        line_y = 238
        for line in course_lines:
            pdf.drawCentredString(centre, line_y, line)
            line_y -= course_size + 4

        # Footer row: date on the left, signature on the right
        baseline = 156
        pdf.setFillColor(MUTED)
        pdf.setFont(_resolve_font(SANS), 9)
        pdf.drawString(120, baseline + 16, "DATE OF ISSUE")
        pdf.setFillColor(INK)
        pdf.setFont(_resolve_font(SERIF), 12)
        pdf.drawString(120, baseline, issue_date.strftime("%d %B %Y"))
        pdf.setStrokeColor(MUTED)
        pdf.setLineWidth(0.6)
        pdf.line(118, baseline - 10, 290, baseline - 10)

        sign_centre = PAGE_WIDTH - 205
        pdf.line(sign_centre - 86, baseline - 10, sign_centre + 86, baseline - 10)
        pdf.setFillColor(INK)
        sign_font = _resolve_font(SERIF_BOLD)
        sign_size = _fit_font_size(signatory_name, sign_font, 170, 12, 8)
        pdf.setFont(sign_font, sign_size)
        pdf.drawCentredString(sign_centre, baseline - 25, signatory_name)
        pdf.setFillColor(MUTED)
        pdf.setFont(_resolve_font(SANS), 8.5)
        pdf.drawCentredString(sign_centre, baseline - 37, signatory_title.upper())

        _draw_seal(pdf, centre, baseline + 4, _initials(organization_name))

        # Certificate number — the audit trail back to the database row.
        pdf.setFillColor(MUTED)
        pdf.setFont(_resolve_font(SANS), 8)
        pdf.drawCentredString(centre, 48, f"Certificate No. {certificate_number}")

        pdf.showPage()
        pdf.save()
    except CertificateRenderError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalise to one error type
        raise CertificateRenderError(f"failed to render certificate: {exc}") from exc

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise CertificateRenderError("renderer produced no output file")

    return output_path.stat().st_size
