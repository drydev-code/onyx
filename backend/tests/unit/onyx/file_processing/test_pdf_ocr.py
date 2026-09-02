"""Tests for PDF page rendering used by CLI-backed agents."""

from pathlib import Path

from onyx.file_processing.pdf_ocr import (
    _render_low_text_pdf_pages,
    _select_page_indices,
    render_pdf_pages_for_ocr,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_select_page_indices_keeps_first_and_last_pages() -> None:
    assert _select_page_indices(list(range(10)), 4) == [0, 1, 8, 9]
    assert _select_page_indices(list(range(10)), 3) == [0, 1, 9]


def test_render_low_text_pdf_pages_skips_pages_with_text() -> None:
    result = _render_low_text_pdf_pages(
        (FIXTURES / "multipage.pdf").read_bytes(),
        max_pages=10,
        min_text_chars=1,
    )

    assert result.total_pages == 2
    assert result.pages == []
    assert result.omitted_page_count == 0


def test_render_pdf_pages_for_ocr_returns_jpeg_from_isolated_process() -> None:
    result = render_pdf_pages_for_ocr((FIXTURES / "with_image.pdf").read_bytes())

    assert result.total_pages == 1
    assert [page.page_number for page in result.pages] == [1]
    assert result.pages[0].image_bytes.startswith(b"\xff\xd8\xff")
    assert result.omitted_page_count == 0
