"""Temporary attachment workspaces for local CLI-backed LLM providers."""

import base64
import binascii
import os
import re
import shutil
from pathlib import Path
from typing import NamedTuple

from onyx.configs.app_configs import (
    DEFAULT_IMAGE_ANALYSIS_MAX_SIZE_MB,
    PDF_OCR_MAX_PAGES,
)
from onyx.file_processing.pdf_ocr import render_pdf_pages_for_ocr
from onyx.llm.models import FileAttachment, LanguageModelInput, UserMessage
from onyx.utils.logger import setup_logger

logger = setup_logger()

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_IMAGE_EXTENSIONS = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class StagedFile(NamedTuple):
    attachment: FileAttachment
    path: str


class RenderedFileImage(NamedTuple):
    source_filename: str
    page_number: int
    total_pages: int
    path: str


class PreparedCLIWorkspace(NamedTuple):
    files: list[StagedFile]
    rendered_images: list[RenderedFileImage]


def collect_file_attachments(prompt: LanguageModelInput) -> list[FileAttachment]:
    messages = prompt if isinstance(prompt, list) else [prompt]
    attachments: list[FileAttachment] = []
    seen_file_ids: set[str] = set()
    for message in messages:
        if not isinstance(message, UserMessage) or not message.file_attachments:
            continue
        for attachment in message.file_attachments:
            if attachment.file_id in seen_file_ids:
                continue
            seen_file_ids.add(attachment.file_id)
            attachments.append(attachment)
    return attachments


def _safe_filename(filename: str, fallback: str) -> str:
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    sanitized = _SAFE_FILENAME_RE.sub("_", basename).strip("._")
    return sanitized or fallback


def _set_owner(path: str, owner: tuple[int, int] | None, mode: int) -> None:
    os.chmod(path, mode)
    if owner is not None:
        shutil.chown(path, user=owner[0], group=owner[1])


def prepare_cli_file_workspace(
    prompt: LanguageModelInput,
    workspace_path: str,
    owner: tuple[int, int] | None = None,
) -> PreparedCLIWorkspace:
    attachments = collect_file_attachments(prompt)
    os.makedirs(workspace_path, exist_ok=True)
    _set_owner(workspace_path, owner, 0o700)

    attachments_path = os.path.join(workspace_path, "attachments")
    rendered_path = os.path.join(workspace_path, "rendered-pdf-pages")
    os.makedirs(attachments_path, exist_ok=True)
    os.makedirs(rendered_path, exist_ok=True)

    staged_files: list[StagedFile] = []
    rendered_images: list[RenderedFileImage] = []
    remaining_pdf_pages = PDF_OCR_MAX_PAGES
    for index, attachment in enumerate(attachments, start=1):
        filename = _safe_filename(attachment.filename, f"file-{index}")
        destination = os.path.join(attachments_path, f"{index:03d}-{filename}")
        Path(destination).write_bytes(attachment.content)
        staged_files.append(StagedFile(attachment=attachment, path=destination))

        if attachment.mime_type != "application/pdf" or remaining_pdf_pages == 0:
            continue
        rendered_pdf = render_pdf_pages_for_ocr(
            attachment.content,
            max_pages=remaining_pdf_pages,
        )
        remaining_pdf_pages -= len(rendered_pdf.pages)
        logger.info(
            "Rendered %d low-text PDF page(s) for CLI OCR: "
            "file_id=%s total_pages=%d omitted=%d",
            len(rendered_pdf.pages),
            attachment.file_id,
            rendered_pdf.total_pages,
            rendered_pdf.omitted_page_count,
        )
        for page in rendered_pdf.pages:
            image_name = f"{index:03d}-{filename}-page-{page.page_number}.jpg"
            image_path = os.path.join(rendered_path, image_name)
            Path(image_path).write_bytes(page.image_bytes)
            rendered_images.append(
                RenderedFileImage(
                    source_filename=filename,
                    page_number=page.page_number,
                    total_pages=rendered_pdf.total_pages,
                    path=image_path,
                )
            )

    for directory in (attachments_path, rendered_path):
        _set_owner(directory, owner, 0o700)
    for staged_file in staged_files:
        _set_owner(staged_file.path, owner, 0o600)
    for rendered_image in rendered_images:
        _set_owner(rendered_image.path, owner, 0o600)

    return PreparedCLIWorkspace(
        files=staged_files,
        rendered_images=rendered_images,
    )


def materialize_data_url_images(
    image_urls: list[str],
    workspace_path: str,
    owner: tuple[int, int] | None = None,
) -> list[str]:
    if not image_urls:
        return []

    images_path = os.path.join(workspace_path, "prompt-images")
    os.makedirs(images_path, exist_ok=True)
    image_paths: list[str] = []
    max_image_bytes = DEFAULT_IMAGE_ANALYSIS_MAX_SIZE_MB * 1024 * 1024

    for index, image_url in enumerate(image_urls, start=1):
        header, separator, encoded = image_url.partition(",")
        if not separator or not header.startswith("data:") or ";base64" not in header:
            continue
        mime_type = header[5:].split(";", 1)[0].lower()
        extension = _IMAGE_EXTENSIONS.get(mime_type)
        if extension is None:
            continue
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            continue
        if not image_bytes or len(image_bytes) > max_image_bytes:
            continue

        image_path = os.path.join(images_path, f"image-{index:03d}{extension}")
        Path(image_path).write_bytes(image_bytes)
        _set_owner(image_path, owner, 0o600)
        image_paths.append(image_path)

    _set_owner(images_path, owner, 0o700)
    return image_paths


def append_cli_file_instructions(
    prompt_text: str,
    workspace: PreparedCLIWorkspace,
) -> str:
    if not workspace.files:
        return prompt_text

    lines = [
        "<attached-files>",
        "The original user files are available at these local paths:",
    ]
    lines.extend(f"- {staged_file.path}" for staged_file in workspace.files)
    if workspace.rendered_images:
        lines.append(
            "Low-text PDF pages were also rendered for visual OCR at these paths:"
        )
        lines.extend(
            f"- {image.path} (page {image.page_number} of {image.total_pages} "
            f"from {image.source_filename})"
            for image in workspace.rendered_images
        )
    lines.extend(
        [
            "Inspect these files before you say that their contents are unavailable.",
            "For scanned PDFs, read the rendered pages directly with vision or the "
            "available file reader.",
            "Do not run Python or install PDF/OCR packages merely to inspect these "
            "attachments.",
            "If the task requires a new PDF, use the installed reportlab and Pillow "
            "packages instead of probing or installing other PDF libraries.",
            "</attached-files>",
        ]
    )
    return f"{prompt_text}\n\n" + "\n".join(lines)
