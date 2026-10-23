import copy
import io
import json
import os
import re
import tempfile
import uuid
import zipfile
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

import attachment_service
from currency_rates import SUPPORTED_CURRENCIES
from trip_flags import normalize_country_code

BACKUP_DIR = Path(os.getenv("TRIP_BACKUP_DIR") or Path.home() / "ControleViagemBackups").expanduser()
BACKUP_FORMAT = "controle-viagem-backup"
TRIP_FORMAT = "controle-viagem-trip"
SCHEMA_VERSION = 1
MAX_BACKUP_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 120 * 1024 * 1024
MAX_ARCHIVE_FILES = 500
MAX_TRIPS = 100
MAX_DAILY_BACKUPS = 30
ACTIVITY_STATUSES = {"planejada", "reservada", "realizada", "cancelada"}
RESERVATION_TYPES = {"hospedagem", "transporte", "passeio", "restaurante", "outro"}
RESERVATION_STATUSES = {"pendente", "confirmada", "cancelada", "utilizada"}
PAYMENT_METHODS = {"Pix", "Cartão", "Dinheiro"}


def _json_default(value):
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Tipo não serializável: {type(value).__name__}")


def _strip_ids(trip):
    copied_trip = copy.deepcopy(trip)
    people_by_id = {
        person.get("id"): person.get("nome", "")
        for person in copied_trip.get("pessoas", [])
    }
    expense_refs = {item.get("id"): index for index, item in enumerate(copied_trip.get("gastos", []))}
    activity_refs = {item.get("id"): index for index, item in enumerate(copied_trip.get("atividades", []))}
    copied_trip.pop("id", None)
    for collection in ("gastos", "atividades", "reservas", "planejamento", "pessoas"):
        for item in copied_trip.get(collection, []):
            if collection == "gastos":
                for payment in item.get("pagamentos", []):
                    payment["participante_nome"] = people_by_id.get(payment.get("participante_id"), "")
                    payment.pop("participante_id", None)
                    payment.pop("id", None)
            item.pop("id", None)
    for attachment in copied_trip.get("anexos", []):
        expense_id = attachment.pop("gasto_id", None)
        activity_id = attachment.pop("atividade_id", None)
        attachment["gasto_ref"] = expense_refs.get(expense_id)
        attachment["atividade_ref"] = activity_refs.get(activity_id)
        attachment.pop("id", None)
    return copied_trip


def make_trip_export(trip, exported_at=None):
    return {
        "format": TRIP_FORMAT,
        "schema_version": SCHEMA_VERSION,
        "exported_at": (exported_at or datetime.now().astimezone()).isoformat(timespec="seconds"),
        "trip": _strip_ids(trip),
    }


def make_daily_backup(trips, created_at=None):
    return {
        "format": BACKUP_FORMAT,
        "schema_version": SCHEMA_VERSION,
        "created_at": (created_at or datetime.now().astimezone()).isoformat(timespec="seconds"),
        "trips": [_strip_ids(trip) for trip in trips],
    }


def _normalize_date(value, field):
    if not isinstance(value, str):
        raise ValueError(f"Data inválida no campo {field}.")
    for date_format in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, date_format).strftime("%d/%m/%Y")
        except ValueError:
            continue
    raise ValueError(f"Data inválida no campo {field}.")


def _text(value, field, max_length, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"Texto inválido no campo {field}.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"O campo {field} é obrigatório.")
    if len(value) > max_length:
        raise ValueError(f"O campo {field} excede o limite permitido.")
    return value


def _amount(value, field, allow_zero=False):
    if isinstance(value, bool):
        raise ValueError(f"Valor inválido no campo {field}.")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Valor inválido no campo {field}.") from exc
    if not amount.is_finite() or amount < 0 or (amount == 0 and not allow_zero):
        raise ValueError(f"Valor inválido no campo {field}.")
    return amount


def _collection(value, field):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Lista inválida no campo {field}.")
    return value


def _normalize_trip(trip):
    if not isinstance(trip, dict):
        raise ValueError("Cada viagem do backup deve ser um objeto JSON.")
    destination = _text(trip.get("destino"), "destino", 150, required=True)
    departure = _normalize_date(trip.get("data_ida"), "data_ida")
    return_date = _normalize_date(trip.get("data_volta"), "data_volta")
    departure_date = datetime.strptime(departure, "%d/%m/%Y").date()
    end_date = datetime.strptime(return_date, "%d/%m/%Y").date()
    if end_date < departure_date:
        raise ValueError("A data de volta não pode ser anterior à data de ida.")

    planning = []
    categories = set()
    for item in _collection(trip.get("planejamento"), "planejamento"):
        if not isinstance(item, dict):
            raise ValueError("Categoria inválida no backup.")
        category = _text(item.get("categoria"), "categoria", 100, required=True)
        category_key = category.casefold()
        if category_key in categories:
            raise ValueError(f"A categoria {category} aparece mais de uma vez.")
        categories.add(category_key)
        amount = _amount(item.get("valor_previsto", 0), "valor_previsto", allow_zero=True)
        planning.append({"categoria": category, "valor_previsto": float(amount)})

    people = []
    people_by_name = {}
    for item in _collection(trip.get("pessoas"), "pessoas"):
        if not isinstance(item, dict):
            raise ValueError("Participante inválido no backup.")
        name = _text(item.get("nome"), "nome do participante", 150, required=True)
        if name.casefold() in people_by_name:
            raise ValueError(f"O participante {name} aparece mais de uma vez.")
        person = {"nome": name}
        people.append(person)
        people_by_name[name.casefold()] = person

    expenses = []
    for item in _collection(trip.get("gastos"), "gastos"):
        if not isinstance(item, dict):
            raise ValueError("Gasto inválido no backup.")
        description = _text(item.get("descricao"), "descricao", 255, required=True)
        category = _text(item.get("categoria"), "categoria", 100, required=True)
        currency = _text(item.get("moeda", "BRL"), "moeda", 3, required=True).upper()
        if currency not in SUPPORTED_CURRENCIES:
            raise ValueError(f"Moeda não suportada no backup: {currency}.")
        original = _amount(item.get("valor_original", item.get("valor_real")), "valor_original")
        rate = _amount(item.get("cotacao", 1), "cotacao")
        if currency == "BRL" and rate != Decimal("1"):
            raise ValueError("A cotação de gastos em BRL deve ser 1.")
        expense_date = _normalize_date(item.get("data_gasto", departure), "data_gasto")
        payment_method = item.get("forma_pagamento")
        if payment_method is not None:
            payment_method = _text(payment_method, "forma_pagamento", 30)
        paid = item.get("pago", False)
        if not isinstance(paid, bool):
            raise ValueError("A situação de pagamento de um gasto é inválida.")
        note = _text(item.get("observacao"), "observacao", 10000)
        converted = (original * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        payments = []
        allocated = Decimal("0.00")
        for payment in _collection(item.get("pagamentos"), "pagamentos"):
            if not isinstance(payment, dict):
                raise ValueError(f"Pagamento inválido no gasto {description}.")
            person_name = _text(payment.get("participante_nome"), "participante_nome", 150)
            person = people_by_name.get(person_name.casefold()) if person_name else None
            if person_name and person is None:
                raise ValueError(f"O pagador {person_name} não está cadastrado nesta viagem.")
            payment_amount = _amount(payment.get("valor_brl"), "valor_brl")
            allocated += payment_amount
            method = _text(payment.get("forma_pagamento"), "forma_pagamento", 30)
            if method and method not in PAYMENT_METHODS:
                raise ValueError("Forma de pagamento inválida no backup.")
            payments.append({
                "participante_nome": person["nome"] if person else "",
                "valor_brl": float(payment_amount),
                "forma_pagamento": method,
            })
        if allocated > converted:
            raise ValueError(f"Os pagamentos do gasto {description} excedem o valor total.")
        expenses.append({
            "data_gasto": expense_date,
            "descricao": description,
            "categoria": category,
            "moeda": currency,
            "valor_original": float(original),
            "cotacao": float(rate),
            "valor_em_brl": float(converted),
            "forma_pagamento": payment_method or None,
            "observacao": note,
            "pago": paid,
            "pagamentos": payments,
        })
        if category.casefold() not in categories:
            categories.add(category.casefold())
            planning.append({"categoria": category, "valor_previsto": 0.0})

    activities = []
    for item in _collection(trip.get("atividades"), "atividades"):
        if not isinstance(item, dict):
            raise ValueError("Atividade inválida no backup.")
        name = _text(item.get("nome"), "nome", 150, required=True)
        activity_date = _normalize_date(item.get("data"), "data")
        parsed_activity_date = datetime.strptime(activity_date, "%d/%m/%Y").date()
        if not departure_date <= parsed_activity_date <= end_date:
            raise ValueError(f"A atividade {name} está fora do período da viagem.")
        time_value = _text(item.get("horario"), "horario", 5)
        if time_value:
            try:
                time_value = datetime.strptime(time_value, "%H:%M").strftime("%H:%M")
            except ValueError as exc:
                raise ValueError(f"Horário inválido na atividade {name}.") from exc
        status = _text(item.get("situacao", "planejada"), "situacao", 20) or "planejada"
        if status not in ACTIVITY_STATUSES:
            raise ValueError(f"Situação inválida na atividade {name}.")
        cost_value = item.get("custo_estimado")
        cost = None if cost_value in (None, "") else float(_amount(cost_value, "custo_estimado", allow_zero=True))
        activities.append({
            "nome": name,
            "data": activity_date,
            "horario": time_value,
            "local": _text(item.get("local"), "local", 255),
            "custo_estimado": cost,
            "observacao": _text(item.get("observacao"), "observacao", 10000),
            "situacao": status,
        })

    reservations = []
    for item in _collection(trip.get("reservas"), "reservas"):
        if not isinstance(item, dict):
            raise ValueError("Reserva inválida no backup.")
        provider = _text(item.get("fornecedor"), "fornecedor", 150, required=True)
        reservation_type = _text(item.get("tipo"), "tipo", 30, required=True)
        if reservation_type not in RESERVATION_TYPES:
            raise ValueError(f"Tipo inválido na reserva {provider}.")
        start = _normalize_date(item.get("data_inicio"), "data_inicio")
        end = _normalize_date(item.get("data_fim"), "data_fim")
        parsed_start = datetime.strptime(start, "%d/%m/%Y").date()
        parsed_end = datetime.strptime(end, "%d/%m/%Y").date()
        if parsed_end < parsed_start:
            raise ValueError(f"A data final da reserva {provider} antecede a data inicial.")
        if not departure_date <= parsed_start <= parsed_end <= end_date:
            raise ValueError(f"A reserva {provider} está fora do período da viagem.")
        checkin_time = _normalize_reservation_time(item.get("horario_checkin"), "check-in", provider)
        checkout_time = _normalize_reservation_time(item.get("horario_checkout"), "check-out", provider)
        cancellation_deadline = item.get("prazo_cancelamento")
        if cancellation_deadline:
            cancellation_deadline = _normalize_date(cancellation_deadline, "prazo_cancelamento")
        status = _text(item.get("situacao", "pendente"), "situacao", 20) or "pendente"
        if status not in RESERVATION_STATUSES:
            raise ValueError(f"Situação inválida na reserva {provider}.")
        reservations.append({
            "tipo": reservation_type,
            "fornecedor": provider,
            "codigo_confirmacao": _text(item.get("codigo_confirmacao"), "codigo_confirmacao", 150),
            "data_inicio": start,
            "horario_checkin": checkin_time,
            "data_fim": end,
            "horario_checkout": checkout_time,
            "local": _text(item.get("local"), "local", 255),
            "prazo_cancelamento": cancellation_deadline or "",
            "situacao": status,
            "observacao": _text(item.get("observacao"), "observacao", 10000),
        })

    attachments = []
    for item in _collection(trip.get("anexos"), "anexos"):
        if not isinstance(item, dict):
            raise ValueError("Anexo inválido no backup.")
        original_name = _text(item.get("nome_original"), "nome_original", 255, required=True)
        mime_type = _text(item.get("mime_type"), "mime_type", 80, required=True)
        if mime_type not in {"application/pdf", "image/jpeg", "image/png"}:
            raise ValueError(f"Tipo de anexo não suportado: {mime_type}.")
        size = item.get("tamanho_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= attachment_service.MAX_ATTACHMENT_BYTES:
            raise ValueError("Tamanho de anexo inválido no backup.")
        archive_path = item.get("archive_path")
        if not isinstance(archive_path, str) or not re.fullmatch(r"attachments/\d+/\d+\.(pdf|png|jpg|jpeg)", archive_path):
            raise ValueError("O backup precisa ser ZIP para incluir anexos.")
        expense_ref = item.get("gasto_ref")
        activity_ref = item.get("atividade_ref")
        if expense_ref is not None and (
            isinstance(expense_ref, bool) or not isinstance(expense_ref, int) or not 0 <= expense_ref < len(expenses)
        ):
            raise ValueError("Referência de gasto inválida no anexo.")
        if activity_ref is not None and (
            isinstance(activity_ref, bool) or not isinstance(activity_ref, int) or not 0 <= activity_ref < len(activities)
        ):
            raise ValueError("Referência de atividade inválida no anexo.")
        if expense_ref is not None and activity_ref is not None:
            raise ValueError("Um anexo não pode pertencer a um gasto e a uma atividade ao mesmo tempo.")
        is_cover = item.get("is_capa", False)
        if not isinstance(is_cover, bool):
            raise ValueError("A marcação de imagem de capa é inválida.")
        if is_cover and mime_type not in {"image/jpeg", "image/png"}:
            raise ValueError("A imagem de capa precisa ser JPG ou PNG.")
        attachments.append({
            "nome_original": original_name,
            "mime_type": mime_type,
            "tamanho_bytes": size,
            "archive_path": archive_path,
            "gasto_ref": expense_ref,
            "atividade_ref": activity_ref,
            "is_capa": is_cover,
        })

    if sum(1 for attachment in attachments if attachment["is_capa"]) > 1:
        raise ValueError("Cada viagem pode ter apenas uma imagem de capa.")

    return {
        "destino": destination,
        "bandeira": normalize_country_code(trip.get("bandeira"), strict=False),
        "data_ida": departure,
        "data_volta": return_date,
        "pessoas": people,
        "gastos": expenses,
        "atividades": activities,
        "reservas": reservations,
        "planejamento": planning,
        "anexos": attachments,
    }


def _normalize_reservation_time(value, field, provider):
    time_value = _text(value, field, 5)
    if not time_value:
        return ""
    try:
        return datetime.strptime(time_value, "%H:%M").strftime("%H:%M")
    except ValueError as exc:
        raise ValueError(f"Horário de {field} inválido na reserva {provider}.") from exc


def validate_backup_document(document):
    if not isinstance(document, dict):
        raise ValueError("O arquivo precisa conter um objeto JSON.")

    backup_format = document.get("format")
    if backup_format == TRIP_FORMAT and document.get("schema_version") == SCHEMA_VERSION:
        source_trips = [document.get("trip")]
    elif backup_format == BACKUP_FORMAT and document.get("schema_version") == SCHEMA_VERSION:
        source_trips = document.get("trips")
    elif not backup_format and isinstance(document.get("viagens"), list):
        source_trips = document["viagens"]
    elif not backup_format and isinstance(document.get("viagem"), dict):
        source_trips = [document["viagem"]]
    else:
        raise ValueError("Formato ou versão de backup não suportado.")

    if not isinstance(source_trips, list) or not source_trips:
        raise ValueError("O backup não contém viagens para restaurar.")
    if len(source_trips) > MAX_TRIPS:
        raise ValueError(f"O backup excede o limite de {MAX_TRIPS} viagens.")
    return [_normalize_trip(trip) for trip in source_trips]


def parse_backup_bytes(raw_bytes):
    if not isinstance(raw_bytes, bytes) or len(raw_bytes) > MAX_BACKUP_BYTES:
        raise ValueError("O arquivo de backup excede o limite de 100 MB.")
    try:
        document = json.loads(raw_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("O arquivo não contém um JSON válido em UTF-8.") from exc
    return validate_backup_document(document)


def write_json_atomic(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".backup-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(document, temporary_file, ensure_ascii=False, indent=2, default=_json_default)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def write_bytes_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=".backup-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(data)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def _build_archive(document, source_trips):
    output = io.BytesIO()
    document_trips = document.get("trips") if document.get("format") == BACKUP_FORMAT else [document["trip"]]
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for trip_index, source_trip in enumerate(source_trips):
            for attachment_index, source_attachment in enumerate(source_trip.get("anexos", [])):
                stored_name = source_attachment.get("nome_armazenado")
                try:
                    file_data = attachment_service.read_attachment(stored_name)
                except (OSError, attachment_service.AttachmentError) as exc:
                    raise ValueError(f"Não foi possível incluir o anexo {source_attachment.get('nome_original', '')}.") from exc
                prepared = attachment_service.prepare_bytes(file_data, source_attachment.get("nome_original", ""))
                if prepared["mime_type"] != source_attachment.get("mime_type"):
                    raise ValueError("O tipo do anexo não corresponde ao arquivo armazenado.")
                suffix = prepared["extension"]
                archive_path = f"attachments/{trip_index}/{attachment_index}{suffix}"
                document_trips[trip_index]["anexos"][attachment_index]["archive_path"] = archive_path
                archive.writestr(archive_path, file_data)
        archive.writestr(
            "backup.json",
            json.dumps(document, ensure_ascii=False, indent=2, default=_json_default).encode("utf-8"),
        )
    payload = output.getvalue()
    if len(payload) > MAX_BACKUP_BYTES:
        raise ValueError("O pacote de backup excede o limite de 100 MB.")
    return payload


def build_trip_archive(trip):
    return _build_archive(make_trip_export(trip), [trip])


def build_daily_archive(trips, created_at=None):
    return _build_archive(make_daily_backup(trips, created_at=created_at), trips)


def parse_backup_archive(raw_bytes):
    if not isinstance(raw_bytes, bytes) or len(raw_bytes) > MAX_BACKUP_BYTES:
        raise ValueError("O arquivo de backup excede o limite permitido.")
    if not zipfile.is_zipfile(io.BytesIO(raw_bytes)):
        raise ValueError("O arquivo ZIP de backup é inválido.")

    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes), "r") as archive:
            members = {}
            total_uncompressed = 0
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                if name.startswith("/") or "\\" in name or ".." in Path(name).parts:
                    raise ValueError("O backup contém um caminho inválido.")
                if name != "backup.json" and not re.fullmatch(r"attachments/\d+/\d+\.(pdf|png|jpg|jpeg)", name):
                    raise ValueError("O backup contém um arquivo não permitido.")
                if name in members:
                    raise ValueError("O backup contém nomes de arquivo duplicados.")
                total_uncompressed += info.file_size
                if info.file_size > attachment_service.MAX_ATTACHMENT_BYTES and name != "backup.json":
                    raise ValueError("Um anexo excede o limite de 10 MB.")
                if total_uncompressed > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise ValueError("O conteúdo descompactado excede o limite permitido.")
                members[name] = archive.read(info)
            if len(members) > MAX_ARCHIVE_FILES or "backup.json" not in members:
                raise ValueError("O backup está incompleto ou tem arquivos demais.")
            document = json.loads(members["backup.json"].decode("utf-8-sig"))
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Não foi possível ler o backup ZIP.") from exc

    trips = validate_backup_document(document)
    expected_files = set()
    for trip in trips:
        for attachment in trip.get("anexos", []):
            archive_path = attachment["archive_path"]
            expected_files.add(archive_path)
            file_data = members.get(archive_path)
            if file_data is None or len(file_data) != attachment["tamanho_bytes"]:
                raise ValueError(f"O anexo {attachment['nome_original']} está ausente ou incompleto.")
            prepared = attachment_service.prepare_bytes(file_data, attachment["nome_original"])
            if prepared["mime_type"] != attachment["mime_type"]:
                raise ValueError(f"O anexo {attachment['nome_original']} tem tipo inválido.")
    if set(members) - {"backup.json"} != expected_files:
        raise ValueError("O backup contém anexos não associados a uma viagem.")
    return trips, {path: members[path] for path in expected_files}


def parse_backup_upload(raw_bytes):
    if isinstance(raw_bytes, bytes) and raw_bytes.startswith(b"PK\x03\x04"):
        return parse_backup_archive(raw_bytes)
    return parse_backup_bytes(raw_bytes), {}


def write_daily_backup(trips, now=None):
    if not trips:
        return None
    now = now or datetime.now().astimezone()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / f"controle-viagem-{now:%Y-%m-%d}.zip"
    if backup_path.exists():
        return backup_path
    write_bytes_atomic(backup_path, build_daily_archive(trips, created_at=now))
    daily_files = [*BACKUP_DIR.glob("controle-viagem-????-??-??.json"), *BACKUP_DIR.glob("controle-viagem-????-??-??.zip")]
    daily_dates = sorted({path.stem.removeprefix("controle-viagem-") for path in daily_files}, reverse=True)
    expired_dates = set(daily_dates[MAX_DAILY_BACKUPS:])
    for old_file in daily_files:
        if old_file.stem.removeprefix("controle-viagem-") in expired_dates:
            old_file.unlink(missing_ok=True)
    return backup_path


def stage_restore_document(trips):
    staging_dir = BACKUP_DIR / ".restore-staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now().timestamp() - 86400
    for staged_file in staging_dir.glob("*.json"):
        if staged_file.stat().st_mtime < cutoff:
            staged_file.unlink(missing_ok=True)
    token = uuid.uuid4().hex
    staged_path = staging_dir / f"{token}.json"
    write_json_atomic(staged_path, make_daily_backup(trips))
    return token


def stage_restore_upload(raw_bytes):
    if not isinstance(raw_bytes, bytes) or len(raw_bytes) > MAX_BACKUP_BYTES:
        raise ValueError("O arquivo de backup excede o limite permitido.")
    staging_dir = BACKUP_DIR / ".restore-staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now().timestamp() - 86400
    for staged_file in staging_dir.glob("*.upload"):
        if staged_file.stat().st_mtime < cutoff:
            staged_file.unlink(missing_ok=True)
    token = uuid.uuid4().hex
    write_bytes_atomic(staging_dir / f"{token}.upload", raw_bytes)
    return token


def read_staged_restore(token):
    if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{32}", token):
        raise ValueError("Token de restauração inválido.")
    staged_path = BACKUP_DIR / ".restore-staging" / f"{token}.upload"
    try:
        size = staged_path.stat().st_size
    except OSError as exc:
        raise ValueError("A prévia de restauração expirou. Envie o arquivo novamente.") from exc
    if size > MAX_BACKUP_BYTES:
        raise ValueError("O arquivo excede o limite permitido.")
    try:
        with staged_path.open("rb") as staged_file:
            return parse_backup_upload(staged_file.read(MAX_BACKUP_BYTES + 1))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Não foi possível ler a prévia do backup.") from exc


def discard_staged_restore(token):
    if isinstance(token, str) and re.fullmatch(r"[a-f0-9]{32}", token):
        staged_path = BACKUP_DIR / ".restore-staging" / f"{token}.upload"
        staged_path.unlink(missing_ok=True)
