from onyx.chat.chat_state import ChatStateContainer
from onyx.file_store.models import ChatFileType, FileDescriptor


def test_generated_files_are_deduplicated_and_copied() -> None:
    container = ChatStateContainer()
    descriptor = FileDescriptor(
        id="generated-pdf-id",
        type=ChatFileType.DOC,
        name="report.pdf",
    )

    container.add_generated_files([descriptor, descriptor])
    result = container.get_generated_files()
    result[0]["name"] = "changed.pdf"

    assert len(result) == 1
    assert container.get_generated_files()[0]["name"] == "report.pdf"
