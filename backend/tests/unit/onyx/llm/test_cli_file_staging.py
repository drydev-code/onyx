"""Tests for temporary CLI attachment workspaces."""

import base64
from pathlib import Path
from unittest.mock import Mock

import pytest

from onyx.llm import cli_file_staging
from onyx.llm.cli_file_staging import (
    append_cli_file_instructions,
    format_cli_artifact_downloads,
    materialize_data_url_images,
    prepare_cli_file_workspace,
    publish_cli_generated_pdfs,
)
from onyx.llm.models import FileAttachment, UserMessage

PDF_FIXTURE = (
    Path(__file__).parents[1] / "file_processing" / "fixtures" / "with_image.pdf"
)


def test_prepare_workspace_stages_original_pdf_without_rendering(
    tmp_path: Path,
) -> None:
    pdf_bytes = PDF_FIXTURE.read_bytes()
    prompt = UserMessage(
        content="Run OCR.",
        file_attachments=[
            FileAttachment(
                file_id="pdf-1",
                filename="../unsafe report.pdf",
                mime_type="application/pdf",
                content=pdf_bytes,
            )
        ],
    )

    workspace = prepare_cli_file_workspace(prompt, str(tmp_path))

    staged_path = Path(workspace.files[0].path)
    assert staged_path.parent == tmp_path / "attachments"
    assert staged_path.name == "001-unsafe_report.pdf"
    assert staged_path.read_bytes() == pdf_bytes
    assert not (tmp_path / "rendered-pdf-pages").exists()

    augmented_prompt = append_cli_file_instructions("Run OCR.", workspace)
    assert str(staged_path) in augmented_prompt
    assert "original files directly" in augmented_prompt
    assert "did not extract, convert, render, or OCR" in augmented_prompt
    assert "installed pdfinfo, pdftotext, or pdftoppm commands" in augmented_prompt
    assert "installed Python PDF libraries are pypdf and pypdfium2" in augmented_prompt
    assert "Do not import fitz, PyMuPDF, or pdfinfo" in augmented_prompt
    assert "reportlab and Pillow" in augmented_prompt
    assert workspace.output_directory in augmented_prompt
    assert "Onyx will publish validated PDFs" in augmented_prompt


def test_materialize_data_url_images_writes_supported_image(tmp_path: Path) -> None:
    png_bytes = b"\x89PNG\r\n\x1a\nimage"
    data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode()

    paths = materialize_data_url_images([data_url], str(tmp_path))

    assert len(paths) == 1
    assert Path(paths[0]).read_bytes() == png_bytes


def test_prepare_workspace_stages_all_original_attachments(tmp_path: Path) -> None:
    pdf_bytes = PDF_FIXTURE.read_bytes()
    prompt = UserMessage(
        content="Read both files.",
        file_attachments=[
            FileAttachment(
                file_id="pdf-1",
                filename="scan.pdf",
                mime_type="application/pdf",
                content=pdf_bytes,
            ),
            FileAttachment(
                file_id="image-1",
                filename="photo.png",
                mime_type="image/png",
                content=b"\x89PNG\r\n\x1a\noriginal",
            ),
        ],
    )

    workspace = prepare_cli_file_workspace(prompt, str(tmp_path))

    assert len(workspace.files) == 2
    assert Path(workspace.files[0].path).read_bytes() == pdf_bytes
    assert Path(workspace.files[1].path).read_bytes().endswith(b"original")


def test_materialize_data_url_images_skips_remote_urls(tmp_path: Path) -> None:
    assert (
        materialize_data_url_images(["https://example.com/image.png"], str(tmp_path))
        == []
    )


def test_publish_cli_generated_pdf_returns_download_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = prepare_cli_file_workspace(
        UserMessage(content="Create a PDF."),
        str(tmp_path),
    )
    output_pdf = Path(workspace.output_directory) / "report.pdf"
    output_pdf.write_bytes(PDF_FIXTURE.read_bytes())

    file_store = Mock()
    file_store.save_file.return_value = "stored-pdf-id"
    monkeypatch.setattr(cli_file_staging, "get_default_file_store", lambda: file_store)

    publication = publish_cli_generated_pdfs(
        str(tmp_path),
        workspace.output_directory,
        "Done.",
    )

    assert publication.rejected_count == 0
    assert publication.artifacts[0].descriptor["id"] == "stored-pdf-id"
    assert publication.artifacts[0].descriptor["name"] == "report.pdf"
    assert "/api/chat/file/stored-pdf-id" in format_cli_artifact_downloads(publication)
    file_store.save_file.assert_called_once()


def test_publish_cli_generated_pdf_rejects_path_outside_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_path = tmp_path / "workspace"
    workspace = prepare_cli_file_workspace(
        UserMessage(content="Create a PDF."),
        str(workspace_path),
    )
    outside_pdf = tmp_path / "outside.pdf"
    outside_pdf.write_bytes(PDF_FIXTURE.read_bytes())

    file_store = Mock()
    monkeypatch.setattr(cli_file_staging, "get_default_file_store", lambda: file_store)

    publication = publish_cli_generated_pdfs(
        str(workspace_path),
        workspace.output_directory,
        f"[report](sandbox:{outside_pdf})",
    )

    assert publication.artifacts == []
    assert publication.rejected_count == 1
    file_store.save_file.assert_not_called()


def test_publish_cli_generated_pdf_rejects_unreadable_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = prepare_cli_file_workspace(
        UserMessage(content="Create a PDF."),
        str(tmp_path),
    )
    output_pdf = Path(workspace.output_directory) / "broken.pdf"
    output_pdf.write_bytes(b"%PDF-not-a-real-document")

    file_store = Mock()
    monkeypatch.setattr(cli_file_staging, "get_default_file_store", lambda: file_store)

    publication = publish_cli_generated_pdfs(
        str(tmp_path),
        workspace.output_directory,
        "Done.",
    )

    assert publication.artifacts == []
    assert publication.rejected_count == 1
    file_store.save_file.assert_not_called()
