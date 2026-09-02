"""Render PDF pages that need visual OCR for CLI-backed agents."""

from io import BytesIO
from typing import NamedTuple

from pypdfium2 import PdfiumError

from onyx.configs.app_configs import (
    PDF_OCR_MAX_PAGES,
    PDF_OCR_MIN_TEXT_CHARS,
    PDF_TEXT_EXTRACTION_TIMEOUT_SECONDS,
)
from onyx.utils.logger import setup_logger
from onyx.utils.process_isolation import IsolatedProcessError, run_in_isolated_process

logger = setup_logger()

_RENDER_SCALE = 2.0
_JPEG_QUALITY = 92


class RenderedPdfPage(NamedTuple):
    page_number: int
    image_bytes: bytes


class RenderedPdf(NamedTuple):
    total_pages: int
    pages: list[RenderedPdfPage]
    omitted_page_count: int


def _select_page_indices(candidate_indices: list[int], cap: int) -> list[int]:
    if cap <= 0:
        return []
    if len(candidate_indices) <= cap:
        return candidate_indices

    first_count = (cap + 1) // 2
    last_count = cap - first_count
    if last_count == 0:
        return candidate_indices[:first_count]
    return candidate_indices[:first_count] + candidate_indices[-last_count:]


def _render_low_text_pdf_pages(
    file_bytes: bytes,
    max_pages: int,
    min_text_chars: int,
) -> RenderedPdf:
    """PDFium worker body. This runs outside the API server process."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(file_bytes)
    try:
        total_pages = len(pdf)
        candidate_indices: list[int] = []
        for page_index in range(total_pages):
            page = pdf[page_index]
            try:
                text_page = page.get_textpage()
                try:
                    text = text_page.get_text_range()
                finally:
                    text_page.close()
                if len(text.strip()) < min_text_chars:
                    candidate_indices.append(page_index)
            except Exception:
                candidate_indices.append(page_index)
            finally:
                page.close()

        selected_indices = _select_page_indices(candidate_indices, max_pages)
        rendered_pages: list[RenderedPdfPage] = []
        for page_index in selected_indices:
            page = pdf[page_index]
            try:
                bitmap = page.render(scale=_RENDER_SCALE)
                try:
                    image = bitmap.to_pil().convert("RGB")
                    output = BytesIO()
                    image.save(output, format="JPEG", quality=_JPEG_QUALITY)
                finally:
                    bitmap.close()
                rendered_pages.append(
                    RenderedPdfPage(
                        page_number=page_index + 1,
                        image_bytes=output.getvalue(),
                    )
                )
            finally:
                page.close()

        return RenderedPdf(
            total_pages=total_pages,
            pages=rendered_pages,
            omitted_page_count=len(candidate_indices) - len(selected_indices),
        )
    finally:
        pdf.close()


def render_pdf_pages_for_ocr(
    file_bytes: bytes,
    max_pages: int = PDF_OCR_MAX_PAGES,
) -> RenderedPdf:
    """Render low-text pages while isolating PDFium crashes and hangs."""
    if not file_bytes or max_pages <= 0:
        return RenderedPdf(total_pages=0, pages=[], omitted_page_count=0)

    try:
        return run_in_isolated_process(
            _render_low_text_pdf_pages,
            file_bytes,
            max_pages,
            PDF_OCR_MIN_TEXT_CHARS,
            timeout=PDF_TEXT_EXTRACTION_TIMEOUT_SECONDS,
        )
    except (IsolatedProcessError, OSError, PdfiumError, ValueError) as error:
        logger.warning("PDF page rendering for OCR failed: %s", error)
        return RenderedPdf(total_pages=0, pages=[], omitted_page_count=0)
