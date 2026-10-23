import os
import re
import tempfile
import uuid
from pathlib import Path

from werkzeug.utils import secure_filename

ATTACHMENT_DIR = Path(os.getenv("TRIP_ATTACHMENT_DIR") or Path.home() / "ControleViagemAttachments").expanduser()
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_FILES = 5
_ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
_MAGIC_PREFIXES = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
}
_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


class AttachmentError(ValueError):
    pass


def prepare_upload(upload):
    original_name = upload.filename or ""
    data = upload.stream.read(MAX_ATTACHMENT_BYTES + 1)
    return prepare_bytes(data, original_name)


def prepare_bytes(data, original_name):
    original_name = secure_filename(original_name or "")
    if not original_name:
        raise AttachmentError("O nome do arquivo é inválido.")
    extension = Path(original_name).suffix.lower()
    if extension not in _ALLOWED_EXTENSIONS:
        raise AttachmentError("Anexe apenas arquivos PDF, JPG ou PNG.")
    if not isinstance(data, bytes):
        raise AttachmentError("O conteúdo do arquivo é inválido.")
    if not data:
        raise AttachmentError("O arquivo está vazio.")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise AttachmentError("Cada anexo pode ter no máximo 10 MB.")
    if not any(data.startswith(prefix) for prefix in _MAGIC_PREFIXES[extension]):
        raise AttachmentError("O conteúdo do arquivo não corresponde à extensão informada.")
    return {
        "nome_original": original_name[:255],
        "mime_type": _MIME_TYPES[extension],
        "tamanho_bytes": len(data),
        "extension": extension,
        "data": data,
    }


def save_prepared_upload(trip_id, prepared):
    stored_name = f"{int(trip_id)}/{uuid.uuid4().hex}{prepared['extension']}"
    destination = _safe_path(stored_name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".upload-", delete=False) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(prepared["data"])
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, destination)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
    return {
        "nome_original": prepared["nome_original"],
        "nome_armazenado": stored_name,
        "mime_type": prepared["mime_type"],
        "tamanho_bytes": prepared["tamanho_bytes"],
    }


def _safe_path(stored_name):
    if not isinstance(stored_name, str) or not re.fullmatch(r"\d+/[a-f0-9]{32}\.(pdf|png|jpg|jpeg)", stored_name):
        raise AttachmentError("Caminho de anexo inválido.")
    root = ATTACHMENT_DIR.resolve()
    path = (ATTACHMENT_DIR / stored_name).resolve()
    if not path.is_relative_to(root):
        raise AttachmentError("Caminho de anexo fora da pasta permitida.")
    return path


def open_attachment(stored_name):
    path = _safe_path(stored_name)
    return path


def delete_attachment(stored_name):
    path = _safe_path(stored_name)
    path.unlink(missing_ok=True)


def read_attachment(stored_name):
    path = _safe_path(stored_name)
    return path.read_bytes()
