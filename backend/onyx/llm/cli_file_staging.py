"""Temporary attachment workspaces for local CLI-backed LLM providers."""

import base64
import binascii
import os
import re
import shutil
from io import BytesIO
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote

from onyx.configs.app_configs import (
    CLI_GENERATED_PDF_MAX_FILES,
    CLI_GENERATED_PDF_MAX_SIZE_MB,
    DEFAULT_IMAGE_ANALYSIS_MAX_SIZE_MB,
    PDF_OCR_MAX_PAGES,
)
from onyx.configs.constants import FileOrigin
from onyx.file_processing.pdf_ocr import render_pdf_pages_for_ocr
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import ChatFileType, FileDescriptor
from onyx.file_store.utils import build_full_frontend_file_url
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
_SANDBOX_PDF_LINK_RE = re.compile(r"sandbox:(?P<path>[^)\s]+\.pdf)", re.IGNORECASE)
_PDF_MIME_TYPE = "application/pdf"


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
    output_directory: str


class PublishedCLIArtifact(NamedTuple):
    descriptor: FileDescriptor
    markdown_link: str


class CLIArtifactPublication(NamedTuple):
    artifacts: list[PublishedCLIArtifact]
    rejected_count: int


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
    output_path = os.path.join(workspace_path, "outputs")
    os.makedirs(attachments_path, exist_ok=True)
    os.makedirs(rendered_path, exist_ok=True)
    os.makedirs(output_path, exist_ok=True)

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

    for directory in (attachments_path, rendered_path, output_path):
        _set_owner(directory, owner, 0o700)
    for staged_file in staged_files:
        _set_owner(staged_file.path, owner, 0o600)
    for rendered_image in rendered_images:
        _set_owner(rendered_image.path, owner, 0o600)

    return PreparedCLIWorkspace(
        files=staged_files,
        rendered_images=rendered_images,
        output_directory=output_path,
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
    lines = ["<local-workspace>"]
    if workspace.files:
        lines.append("The original user files are available at these local paths:")
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
            ]
        )
    lines.extend(
        [
            "If the task requires a new PDF, use the installed reportlab and Pillow "
            "packages instead of probing or installing other PDF libraries.",
            "If the task requests a downloadable PDF, save every final PDF directly "
            f"in {workspace.output_directory}.",
            "Do not save intermediate files in that directory.",
            "Do not include sandbox: or local-file links in the answer. Onyx will "
            "publish validated PDFs from the output directory and append download links.",
            "</local-workspace>",
        ]
    )
    return f"{prompt_text}\n\n" + "\n".join(lines)


def _is_path_inside(candidate: Path, directory: Path) -> bool:
    try:
        candidate.relative_to(directory)
    except ValueError:
        return False
    return True


def _candidate_generated_pdf_paths(
    workspace_path: str,
    output_directory: str,
    response_text: str,
) -> list[Path]:
    workspace = Path(workspace_path).resolve()
    output_path = Path(output_directory).resolve()
    candidates: list[Path] = []

    for directory in (output_path, workspace):
        if not directory.is_dir():
            continue
        candidates.extend(
            path
            for path in sorted(directory.iterdir())
            if path.suffix.lower() == ".pdf"
        )

    for match in _SANDBOX_PDF_LINK_RE.finditer(response_text):
        raw_path = unquote(match.group("path"))
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = workspace / candidate
        candidates.append(candidate)

    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError):
            logger.warning("Could not resolve CLI PDF output path: %s", candidate)
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(candidate)
    return unique


def publish_cli_generated_pdfs(
    workspace_path: str,
    output_directory: str,
    response_text: str,
) -> CLIArtifactPublication:
    """Validate and persist PDFs created inside a CLI workspace."""
    workspace = Path(workspace_path).resolve()
    max_size_bytes = CLI_GENERATED_PDF_MAX_SIZE_MB * 1024 * 1024
    artifacts: list[PublishedCLIArtifact] = []
    rejected_count = 0
    candidates = _candidate_generated_pdf_paths(
        workspace_path,
        output_directory,
        response_text,
    )

    for candidate in candidates[:CLI_GENERATED_PDF_MAX_FILES]:
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError):
            rejected_count += 1
            logger.warning("Could not resolve CLI PDF output path: %s", candidate)
            continue

        if (
            not _is_path_inside(resolved, workspace)
            or candidate.is_symlink()
            or not resolved.is_file()
            or resolved.suffix.lower() != ".pdf"
        ):
            rejected_count += 1
            logger.warning("Rejected unsafe or missing CLI PDF output: %s", candidate)
            continue

        try:
            file_size = resolved.stat().st_size
        except OSError:
            rejected_count += 1
            logger.warning("Could not inspect CLI PDF output: %s", resolved)
            continue
        if file_size == 0 or file_size > max_size_bytes:
            rejected_count += 1
            logger.warning(
                "Rejected CLI PDF output with invalid size: path=%s size=%d",
                resolved,
                file_size,
            )
            continue

        try:
            content = resolved.read_bytes()
        except OSError:
            rejected_count += 1
            logger.warning("Could not read CLI PDF output: %s", resolved)
            continue
        if not content.startswith(b"%PDF-"):
            rejected_count += 1
            logger.warning(
                "Rejected CLI output with an invalid PDF header: %s", resolved
            )
            continue

        try:
            validation = render_pdf_pages_for_ocr(content, max_pages=1)
        except Exception:
            rejected_count += 1
            logger.warning(
                "Rejected unreadable CLI PDF output: %s",
                resolved,
                exc_info=True,
            )
            continue
        if validation.total_pages <= 0:
            rejected_count += 1
            logger.warning("Rejected unreadable CLI PDF output: %s", resolved)
            continue

        filename = _safe_filename(resolved.name, "generated-report.pdf")
        file_id = get_default_file_store().save_file(
            content=BytesIO(content),
            display_name=filename,
            file_origin=FileOrigin.CHAT_IMAGE_GEN,
            file_type=_PDF_MIME_TYPE,
        )
        file_url = build_full_frontend_file_url(file_id)
        artifacts.append(
            PublishedCLIArtifact(
                descriptor=FileDescriptor(
                    id=file_id,
                    type=ChatFileType.DOC,
                    name=filename,
                ),
                markdown_link=f"[{filename}]({file_url})",
            )
        )
        logger.info(
            "Published CLI-generated PDF: file_id=%s filename=%s pages=%d size=%d",
            file_id,
            filename,
            validation.total_pages,
            file_size,
        )

    rejected_count += max(0, len(candidates) - CLI_GENERATED_PDF_MAX_FILES)
    return CLIArtifactPublication(
        artifacts=artifacts,
        rejected_count=rejected_count,
    )


def format_cli_artifact_downloads(publication: CLIArtifactPublication) -> str:
    lines: list[str] = []
    if publication.artifacts:
        lines.extend(
            [
                "\n\n### Downloads",
                "",
                *(f"- {artifact.markdown_link}" for artifact in publication.artifacts),
            ]
        )
    if publication.rejected_count:
        lines.extend(
            [
                "\n\nA generated PDF could not be published because it was missing, "
                "invalid, unsafe, or over the configured limit."
            ]
        )
    return "\n".join(lines)
