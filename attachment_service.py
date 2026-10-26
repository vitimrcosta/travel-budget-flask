import io
import logging
import os
import re
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

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


def ensure_storage_configuration():
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
    api_key = os.getenv("CLOUDINARY_API_KEY", "").strip()
    api_secret = os.getenv("CLOUDINARY_API_SECRET", "").strip()
    configured = (cloud_name, api_key, api_secret)
    required = os.getenv("CLOUDINARY_REQUIRED", "").strip().lower() in {"1", "true", "yes"}
    if any(configured) and not all(configured):
        raise AttachmentError(
            "Configure CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY e CLOUDINARY_API_SECRET."
        )
    if required and not all(configured):
        raise AttachmentError("Cloudinary é obrigatório, mas as credenciais não estão configuradas.")


def cloudinary_enabled():
    return all(os.getenv(key, "").strip() for key in (
        "CLOUDINARY_CLOUD_NAME",
        "CLOUDINARY_API_KEY",
        "CLOUDINARY_API_SECRET",
    ))


def is_cloudinary_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
    return (
        parsed.scheme == "https"
        and parsed.hostname == "res.cloudinary.com"
        and bool(cloud_name)
        and parsed.path.startswith(f"/{cloud_name}/")
    )


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
    if cloudinary_enabled():
        return _save_cloudinary_upload(trip_id, prepared)
    if os.getenv("CLOUDINARY_REQUIRED", "").strip().lower() in {"1", "true", "yes"}:
        raise AttachmentError("O armazenamento Cloudinary é obrigatório e não está configurado.")

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


def _save_cloudinary_upload(trip_id, prepared):
    import cloudinary
    import cloudinary.uploader

    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
        secure=True,
    )
    resource_type = "raw" if prepared["mime_type"] == "application/pdf" else "image"
    public_id = f"travel-attachments/{int(trip_id)}/{uuid.uuid4().hex}"
    if resource_type == "raw":
        public_id += prepared["extension"]
    try:
        result = cloudinary.uploader.upload(
            io.BytesIO(prepared["data"]),
            public_id=public_id,
            resource_type=resource_type,
            overwrite=False,
            unique_filename=False,
        )
    except Exception as error:
        logging.getLogger(__name__).error(
            "Falha no upload Cloudinary: %s: %s", type(error).__name__, str(error)[:300]
        )
        raise AttachmentError("Não foi possível enviar o arquivo para o Cloudinary.") from error

    secure_url = result.get("secure_url")
    if not is_cloudinary_url(secure_url):
        try:
            cloudinary.uploader.destroy(
                result.get("public_id", public_id),
                resource_type=resource_type,
                invalidate=True,
            )
        except Exception as error:
            raise AttachmentError(
                "O Cloudinary retornou uma URL inválida e não foi possível limpar o arquivo enviado."
            ) from error
        raise AttachmentError("O Cloudinary não retornou uma URL segura válida.")
    return {
        "nome_original": prepared["nome_original"],
        "nome_armazenado": secure_url,
        "mime_type": prepared["mime_type"],
        "tamanho_bytes": prepared["tamanho_bytes"],
    }


def _cloudinary_asset(stored_name):
    if not is_cloudinary_url(stored_name):
        raise AttachmentError("URL de anexo Cloudinary inválida.")
    parsed = urlsplit(stored_name)
    path_parts = [unquote(part) for part in parsed.path.split("/") if part]
    try:
        upload_index = path_parts.index("upload")
        resource_type = path_parts[upload_index - 1]
        asset_parts = path_parts[upload_index + 1:]
    except (ValueError, IndexError) as error:
        raise AttachmentError("URL de anexo Cloudinary inválida.") from error
    if asset_parts and re.fullmatch(r"v\d+", asset_parts[0]):
        asset_parts = asset_parts[1:]
    public_id = "/".join(asset_parts)
    if resource_type not in {"image", "raw"} or not public_id:
        raise AttachmentError("URL de anexo Cloudinary inválida.")
    if resource_type == "image":
        public_id = re.sub(r"\.(jpg|jpeg|png)$", "", public_id, flags=re.IGNORECASE)
    return public_id, resource_type


def _delete_cloudinary_asset(stored_name):
    import cloudinary
    import cloudinary.uploader

    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
        secure=True,
    )
    public_id, resource_type = _cloudinary_asset(stored_name)
    try:
        result = cloudinary.uploader.destroy(
            public_id,
            resource_type=resource_type,
            invalidate=True,
        )
    except Exception as error:
        raise AttachmentError("Não foi possível remover o arquivo do Cloudinary.") from error
    if result.get("result") not in {"ok", "not found"}:
        raise AttachmentError("O Cloudinary não confirmou a remoção do arquivo.")


def _safe_path(stored_name):
    if not isinstance(stored_name, str) or not re.fullmatch(r"\d+/[a-f0-9]{32}\.(pdf|png|jpg|jpeg)", stored_name):
        raise AttachmentError("Caminho de anexo inválido.")
    root = ATTACHMENT_DIR.resolve()
    path = (ATTACHMENT_DIR / stored_name).resolve()
    if not path.is_relative_to(root):
        raise AttachmentError("Caminho de anexo fora da pasta permitida.")
    return path


def open_attachment(stored_name):
    if is_cloudinary_url(stored_name):
        raise AttachmentError("Arquivos Cloudinary devem ser acessados pela URL segura.")
    path = _safe_path(stored_name)
    return path


def delete_attachment(stored_name):
    if is_cloudinary_url(stored_name):
        return _delete_cloudinary_asset(stored_name)
    path = _safe_path(stored_name)
    path.unlink(missing_ok=True)


def read_attachment(stored_name):
    if is_cloudinary_url(stored_name):
        try:
            with urllib.request.urlopen(stored_name, timeout=30) as response:
                data = response.read(MAX_ATTACHMENT_BYTES + 1)
        except (OSError, urllib.error.URLError) as error:
            raise AttachmentError("Não foi possível baixar o anexo armazenado no Cloudinary.") from error
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise AttachmentError("O anexo Cloudinary excede o limite de 10 MB.")
        return data
    path = _safe_path(stored_name)
    return path.read_bytes()
