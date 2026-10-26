import io
import hmac
import json
import os
import secrets
import unicodedata
from datetime import date, datetime, time as datetime_time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import ceil
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, abort, flash, jsonify, make_response, redirect, render_template, request, send_file, session, url_for
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename

from db_service import storage_manager
import attachment_service
import backup_service
from currency_rates import CURRENCY_NAMES, SUPPORTED_CURRENCIES, ExchangeRateError, get_historical_rate
from main import calcular_totais, data_esta_no_periodo, valores_pagamento_gasto
from trip_flags import normalize_country_code

PAYMENT_METHODS = ("Pix", "Cartão", "Dinheiro")
ACTIVITY_STATUSES = ("planejada", "reservada", "realizada", "cancelada")
RESERVATION_TYPES = ("hospedagem", "transporte", "passeio", "restaurante", "outro")
RESERVATION_STATUSES = ("pendente", "confirmada", "cancelada", "utilizada")


def add_reservation_deadline_alerts(reservations, today=None):
    current_date = today or date.today()
    annotated = []
    for reservation in reservations:
        item = dict(reservation)
        deadline_value = item.get("prazo_cancelamento")
        if deadline_value and item.get("situacao", "pendente") in ("pendente", "confirmada"):
            deadline = datetime.strptime(deadline_value, "%d/%m/%Y").date()
            days_remaining = (deadline - current_date).days
            if days_remaining < 0:
                item["alerta_prazo"] = f"Prazo de cancelamento gratuito encerrado em {deadline_value}."
            elif days_remaining == 0:
                item["alerta_prazo"] = "O prazo de cancelamento gratuito termina hoje."
            elif days_remaining <= 7:
                item["alerta_prazo"] = f"Cancelamento gratuito até {deadline_value}."
        annotated.append(item)
    return annotated
COUNTRIES = json.loads(
    (Path(__file__).with_name("static") / "countries.json").read_text(encoding="utf-8")
)
COUNTRIES_BY_CODE = {country["code"]: country for country in COUNTRIES}

app = Flask(__name__)
REQUIRE_LOGIN = os.getenv("REQUIRE_LOGIN", "").strip().lower() in {"1", "true", "yes"}
APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", "").strip()
LOGIN_USERNAME = os.getenv("APP_LOGIN_USERNAME", "")
LOGIN_PASSWORD = os.getenv("APP_LOGIN_PASSWORD", "")
if REQUIRE_LOGIN and not APP_SECRET_KEY:
    raise RuntimeError("APP_SECRET_KEY precisa estar configurada quando REQUIRE_LOGIN estiver ativo.")
if REQUIRE_LOGIN and (not LOGIN_USERNAME or not LOGIN_PASSWORD):
    raise RuntimeError("Configure APP_LOGIN_USERNAME e APP_LOGIN_PASSWORD para habilitar o login.")

app.config["SECRET_KEY"] = APP_SECRET_KEY or secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv(
    "SESSION_COOKIE_SECURE", "true" if REQUIRE_LOGIN else "false"
).strip().lower() in {"1", "true", "yes"}
app.config["MAX_CONTENT_LENGTH"] = backup_service.MAX_BACKUP_BYTES + (1024 * 1024)
CSRFProtect(app)
attachment_service.ensure_storage_configuration()


def safe_next_url(value):
    if not value or "\\" in value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return None
    return value


@app.before_request
def require_shared_login():
    if not REQUIRE_LOGIN or request.endpoint in {
        None, "login", "healthz", "static", "pwa_manifest", "service_worker", "offline_page",
    }:
        return None
    if session.get("authenticated"):
        return None
    return redirect(url_for("login", next=request.full_path if request.query_string else request.path))


@app.before_request
def keep_database_alive():
    if request.endpoint not in {"static", "healthz", "pwa_manifest", "service_worker", "offline_page"}:
        storage_manager.ensure_connection()


@app.get("/healthz")
def healthz():
    return jsonify(status="ok")


@app.get("/status")
def status():
    configured = lambda *names: {name: bool(os.getenv(name)) for name in names}
    error = storage_manager.mysql_error
    return jsonify(
        mysql_connected=storage_manager.mysql_enabled,
        mysql_error=type(error).__name__ if error else None,
        mysql_error_message=str(error)[:200] if error else None,
        require_mysql=os.getenv("REQUIRE_MYSQL", "").strip().lower() in {"1", "true", "yes"},
        database_env=configured("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME", "DB_SSL_REQUIRED"),
        cloudinary_env=configured("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET", "CLOUDINARY_REQUIRED"),
        cloudinary_active=attachment_service.cloudinary_enabled(),
    )


def static_version():
    static_dir = Path(app.static_folder)
    stamps = [
        int((static_dir / name).stat().st_mtime)
        for name in ("app.css", "app.js")
        if (static_dir / name).exists()
    ]
    return str(max(stamps, default=0))


@app.get("/manifest.webmanifest")
def pwa_manifest():
    icons = [
        {"src": url_for("static", filename="icons/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": url_for("static", filename="icons/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": url_for("static", filename="icons/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ]
    manifest = {
        "id": "/",
        "name": "Rota | Controle de viagem",
        "short_name": "Rota",
        "description": "Orçamento, gastos, roteiro e reservas da sua viagem.",
        "lang": "pt-BR",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#173f35",
        "theme_color": "#173f35",
        "icons": icons,
    }
    response = jsonify(manifest)
    response.headers["Content-Type"] = "application/manifest+json"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/sw.js")
def service_worker():
    response = make_response(render_template("sw.js", version=static_version()))
    response.headers["Content-Type"] = "application/javascript; charset=utf-8"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@app.get("/offline")
def offline_page():
    return render_template("offline.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if not REQUIRE_LOGIN:
        abort(404)
    if session.get("authenticated"):
        return redirect(url_for("index"))
    next_url = safe_next_url(request.values.get("next"))
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if hmac.compare_digest(username.encode("utf-8"), LOGIN_USERNAME.encode("utf-8")) and hmac.compare_digest(
            password.encode("utf-8"), LOGIN_PASSWORD.encode("utf-8")
        ):
            session.clear()
            session["authenticated"] = True
            return redirect(next_url or url_for("index"))
        flash("Usuário ou senha incorretos.", "error")
    return render_template("login.html", next_url=next_url or "")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.template_filter("category_icon")
def category_icon(name):
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    for keywords, icon in (
        (("aliment", "restaur", "comida", "refei"), "🍽️"),
        (("hosped", "hotel", "airbnb"), "🏨"),
        (("passagem", "voo", "aere"), "✈️"),
        (("transport", "uber", "taxi", "onibus", "metro", "carro"), "🚌"),
        (("passeio", "atra", "ingresso", "lazer"), "🎟️"),
        (("compra", "souvenir"), "🛍️"),
        (("seguro", "saude"), "🛡️"),
        (("chip", "internet", "telefone"), "📶"),
    ):
        if any(word in text for word in keywords):
            return icon
    return "🧾"


@app.template_filter("money")
def format_money(value, currency="BRL"):
    formatted = f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}" if currency == "BRL" else f"{formatted} {currency}"


@app.template_filter("input_date")
def format_input_date(value):
    try:
        return datetime.strptime(value, "%d/%m/%Y").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


@app.template_filter("money_value")
def format_money_value(value):
    if value in (None, ""):
        return ""
    return f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@app.template_filter("payment_status")
def format_payment_status(expense):
    paid, outstanding = valores_pagamento_gasto(expense)
    if outstanding <= 0:
        return "Pago"
    if paid > 0:
        return "Parcial"
    return "Pendente"


@app.template_filter("payment_people")
def format_payment_people(payments):
    labels = []
    for payment in payments or []:
        name = payment.get("participante_nome") or "Não identificado"
        amount = format_money(payment.get("valor_brl", 0))
        method = payment.get("forma_pagamento") or "forma não informada"
        labels.append(f"{name}: {amount} ({method})")
    return "; ".join(labels) or "—"


@app.context_processor
def add_template_context():
    daily_backups_disabled = os.getenv("DISABLE_DAILY_BACKUPS", "").strip().lower() in {"1", "true", "yes"}
    return {
        "trips": [] if request.endpoint in {"login", "offline_page"} else storage_manager.list_viagens(),
        "selected_trip_id": session.get("selected_trip_id"),
        "mysql_available": storage_manager.mysql_enabled,
        "currency_codes": SUPPORTED_CURRENCIES,
        "currency_names": CURRENCY_NAMES,
        "backup_directory": str(backup_service.BACKUP_DIR),
        "backup_available": not daily_backups_disabled and storage_manager.backup_error is None,
        "daily_backups_disabled": daily_backups_disabled,
        "countries": COUNTRIES,
        "countries_by_code": COUNTRIES_BY_CODE,
        "require_login": REQUIRE_LOGIN,
    }


def get_trip_or_404(trip_id):
    trip = storage_manager.get_viagem(trip_id)
    if trip is None:
        abort(404)
    return trip


def select_trip(trip_id):
    session["selected_trip_id"] = trip_id


def parse_form_date(value, label):
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y"), None
    except (TypeError, ValueError):
        return None, f"Informe {label} como uma data válida."


def parse_country_code(value):
    code = normalize_country_code(value)
    if code and code not in COUNTRIES_BY_CODE:
        raise ValueError("Selecione um país válido da lista.")
    return code


def parse_amount(value, label, required=True):
    try:
        normalized = (value or "").strip().replace("R$", "").replace(" ", "")
        if not normalized and not required:
            return None, None
        if "," in normalized:
            normalized = normalized.replace(".", "").replace(",", ".")
        amount = Decimal(normalized)
        if not amount.is_finite() or amount < 0:
            raise InvalidOperation
        return float(amount), None
    except (InvalidOperation, AttributeError):
        return None, f"{label} deve ser um valor igual ou maior que zero."


def prepare_attachment_uploads(files):
    uploads = [uploaded for uploaded in files if uploaded and uploaded.filename]
    if len(uploads) > attachment_service.MAX_UPLOAD_FILES:
        raise attachment_service.AttachmentError(
            f"Envie no máximo {attachment_service.MAX_UPLOAD_FILES} arquivos por vez."
        )
    return [attachment_service.prepare_upload(uploaded) for uploaded in uploads]


def save_trip_attachments(trip, uploads, expense_id=None, activity_id=None):
    saved_files = []
    attachments = trip.setdefault("anexos", [])
    try:
        for prepared in uploads:
            metadata = attachment_service.save_prepared_upload(trip["id"], prepared)
            saved_files.append(metadata["nome_armazenado"])
            metadata.update({"gasto_id": expense_id, "atividade_id": activity_id, "is_capa": False})
            attachments.append(metadata)
        if uploads:
            storage_manager.save_viagem(trip)
    except Exception:
        if saved_files:
            trip["anexos"] = [
                attachment for attachment in attachments
                if attachment.get("nome_armazenado") not in saved_files
            ]
            for stored_name in saved_files:
                attachment_service.delete_attachment(stored_name)
            try:
                storage_manager.save_viagem(trip)
            except Exception:
                pass
        raise


def attachments_for_record(trip, expense_id=None, activity_id=None, general=False):
    if not general and expense_id is None and activity_id is None:
        return []
    if general:
        return [
            attachment for attachment in trip.get("anexos", [])
            if attachment.get("gasto_id") is None
            and attachment.get("atividade_id") is None
            and not attachment.get("is_capa")
        ]
    if expense_id is not None:
        return [
            attachment for attachment in trip.get("anexos", [])
            if attachment.get("gasto_id") == expense_id and attachment.get("atividade_id") is None
        ]
    return [
        attachment for attachment in trip.get("anexos", [])
        if attachment.get("atividade_id") == activity_id and attachment.get("gasto_id") is None
    ]


@app.post("/trips/<int:trip_id>/cover")
def upload_trip_cover(trip_id):
    trip = get_trip_or_404(trip_id)
    uploaded_file = request.files.get("capa")
    try:
        prepared = attachment_service.prepare_upload(uploaded_file) if uploaded_file and uploaded_file.filename else None
        if prepared is None:
            raise attachment_service.AttachmentError("Selecione uma imagem para a capa.")
        if prepared["mime_type"] not in {"image/jpeg", "image/png"}:
            raise attachment_service.AttachmentError("A capa deve estar no formato JPG ou PNG.")
        new_cover = attachment_service.save_prepared_upload(trip_id, prepared)
        new_cover.update({"gasto_id": None, "atividade_id": None, "is_capa": True})
        old_covers = [attachment for attachment in trip.get("anexos", []) if attachment.get("is_capa")]
        trip["anexos"] = [attachment for attachment in trip.get("anexos", []) if not attachment.get("is_capa")]
        trip["anexos"].append(new_cover)
        try:
            storage_manager.save_viagem(trip)
        except Exception:
            attachment_service.delete_attachment(new_cover["nome_armazenado"])
            raise
    except attachment_service.AttachmentError as error:
        flash(str(error), "error")
        return redirect(url_for("dashboard", trip_id=trip_id))
    except Exception:
        flash("Não foi possível salvar a imagem da capa.", "error")
        return redirect(url_for("dashboard", trip_id=trip_id))
    for old_cover in old_covers:
        attachment_service.delete_attachment(old_cover["nome_armazenado"])
    flash("Imagem da capa atualizada.", "success")
    return redirect(url_for("dashboard", trip_id=trip_id))


@app.get("/trips/<int:trip_id>/cover/<int:attachment_id>")
def trip_cover_image(trip_id, attachment_id):
    trip = get_trip_or_404(trip_id)
    cover = next((
        item for item in trip.get("anexos", [])
        if item.get("id") == attachment_id and item.get("is_capa")
    ), None)
    if cover is None or cover.get("mime_type") not in {"image/jpeg", "image/png"}:
        abort(404)
    try:
        image_data = attachment_service.read_attachment(cover["nome_armazenado"])
    except (OSError, attachment_service.AttachmentError):
        abort(404)
    return send_file(io.BytesIO(image_data), mimetype=cover["mime_type"], as_attachment=False, max_age=0)


def report_attachment_error(error):
    if isinstance(error, attachment_service.AttachmentError):
        return str(error)
    return "Não foi possível salvar o anexo. O registro principal foi mantido."


@app.get("/api/exchange-rate")
def exchange_rate_api():
    currency = request.args.get("currency", "").strip().upper()
    date_value = request.args.get("date", "").strip()
    if currency not in SUPPORTED_CURRENCIES:
        return jsonify(error="Selecione uma moeda suportada."), 400
    try:
        requested_date = datetime.strptime(date_value, "%Y-%m-%d").date()
    except ValueError:
        return jsonify(error="Informe uma data válida para consultar a cotação."), 400
    if currency == "BRL":
        return jsonify(currency=currency, rate="1", date=requested_date.isoformat())
    try:
        quote = get_historical_rate(currency, requested_date)
    except ExchangeRateError as error:
        return jsonify(error=str(error)), 502
    return jsonify(
        currency=quote["currency"],
        rate=str(quote["rate"]),
        date=quote["date"],
    )


def activity_order_key(activity):
    return (
        datetime.strptime(activity["data"], "%d/%m/%Y"),
        activity.get("horario") or "99:99",
        activity.get("nome", "").casefold(),
    )


def find_next_activity(activities, now=None):
    current_time = now or datetime.now()
    upcoming = []
    today_activities = []
    for activity in activities:
        if activity.get("situacao", "planejada") not in ("planejada", "reservada"):
            continue
        activity_date = datetime.strptime(activity["data"], "%d/%m/%Y").date()
        raw_time = str(activity.get("horario") or "").strip()
        normalized_time = raw_time[:-1] if raw_time.endswith(":") else raw_time
        if normalized_time:
            try:
                activity_time = datetime.strptime(normalized_time, "%H:%M").time()
            except ValueError:
                try:
                    activity_time = datetime.strptime(normalized_time, "%H:%M:%S").time()
                except ValueError:
                    app.logger.warning(
                        "Horário inválido na atividade %r: %r; será tratado como não informado.",
                        activity.get("nome", ""),
                        raw_time,
                    )
                    activity_time = datetime_time.min
                    normalized_time = ""
        else:
            activity_time = datetime_time.min
        scheduled_at = datetime.combine(activity_date, activity_time)
        selected_activity = dict(activity)
        selected_activity["horario"] = activity_time.strftime("%H:%M") if normalized_time else ""
        if activity_date == current_time.date():
            today_activities.append((scheduled_at, activity.get("nome", "").casefold(), selected_activity))
        if scheduled_at >= current_time:
            upcoming.append((scheduled_at, activity.get("nome", "").casefold(), selected_activity))
    if upcoming:
        return min(upcoming, key=lambda item: (item[0], item[1]))[2]
    if today_activities:
        return max(today_activities, key=lambda item: (item[0], item[1]))[2]
    return None


def group_activities_by_day(activities):
    days = []
    for activity in activities:
        if not days or days[-1]["data"] != activity["data"]:
            days.append({"data": activity["data"], "items": []})
        days[-1]["items"].append(activity)
    return days


@app.get("/")
def index():
    trip_id = session.get("selected_trip_id")
    if trip_id is not None and storage_manager.get_viagem(trip_id) is None:
        session.pop("selected_trip_id", None)
    return render_template("dashboard.html", trip=None, totals=None)


@app.get("/trips/<int:trip_id>")
def dashboard(trip_id):
    trip = get_trip_or_404(trip_id)
    select_trip(trip_id)
    recent_expenses = sorted(
        trip.get("gastos", []),
        key=lambda expense: datetime.strptime(expense["data_gasto"], "%d/%m/%Y"),
        reverse=True,
    )[:5]
    next_activity = find_next_activity(trip.get("atividades", []))
    recent_reservations = sorted(
        trip.get("reservas", []),
        key=lambda item: (datetime.strptime(item["data_inicio"], "%d/%m/%Y"), item.get("fornecedor", "").casefold()),
    )[:3]
    recent_reservations = add_reservation_deadline_alerts(recent_reservations)
    return render_template(
        "dashboard.html",
        trip=trip,
        totals=calcular_totais(trip),
        recent_expenses=recent_expenses,
        next_activity=next_activity,
        recent_reservations=recent_reservations,
        cover_attachment=next((item for item in trip.get("anexos", []) if item.get("is_capa")), None),
    )


@app.get("/trips/<int:trip_id>/report")
def trip_report(trip_id):
    trip = get_trip_or_404(trip_id)
    select_trip(trip_id)
    return render_template(
        "report.html",
        trip=trip,
        totals=calcular_totais(trip),
    )


@app.get("/trips/<int:trip_id>/backup/export")
def export_trip_backup(trip_id):
    trip = get_trip_or_404(trip_id)
    select_trip(trip_id)
    payload = backup_service.build_trip_archive(trip)
    destination = secure_filename(trip["destino"]) or "viagem"
    filename = f"{destination}-{trip['data_ida'].replace('/', '-')}.zip"
    return send_file(
        io.BytesIO(payload),
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename,
        max_age=0,
    )


@app.route("/trips/<int:trip_id>/documents", methods=["GET", "POST"])
def trip_documents(trip_id):
    trip = get_trip_or_404(trip_id)
    select_trip(trip_id)
    if request.method == "POST":
        try:
            uploads = prepare_attachment_uploads(request.files.getlist("anexos"))
            if not uploads:
                raise attachment_service.AttachmentError("Selecione ao menos um arquivo.")
            save_trip_attachments(trip, uploads)
        except attachment_service.AttachmentError as error:
            flash(str(error), "error")
        except Exception:
            flash("Não foi possível salvar os anexos desta viagem.", "error")
        else:
            flash(f"{len(uploads)} anexo(s) salvo(s).", "success")
        return redirect(url_for("trip_documents", trip_id=trip_id))
    return render_template("documents.html", trip=trip, attachments=attachments_for_record(trip, general=True))


@app.get("/trips/<int:trip_id>/attachments/<int:attachment_id>")
def download_trip_attachment(trip_id, attachment_id):
    trip = get_trip_or_404(trip_id)
    attachment = next(
        (item for item in trip.get("anexos", []) if item.get("id") == attachment_id),
        None,
    )
    if attachment is None:
        abort(404)
    try:
        attachment_data = attachment_service.read_attachment(attachment["nome_armazenado"])
    except (OSError, attachment_service.AttachmentError):
        abort(404)
    return send_file(
        io.BytesIO(attachment_data),
        mimetype=attachment["mime_type"],
        as_attachment=True,
        download_name=attachment["nome_original"],
        max_age=0,
    )


@app.post("/trips/<int:trip_id>/attachments/<int:attachment_id>/delete")
def delete_trip_attachment(trip_id, attachment_id):
    trip = get_trip_or_404(trip_id)
    attachment = next(
        (item for item in trip.get("anexos", []) if item.get("id") == attachment_id),
        None,
    )
    if attachment is None:
        abort(404)
    trip["anexos"] = [item for item in trip["anexos"] if item.get("id") != attachment_id]
    storage_manager.save_viagem(trip)
    attachment_service.delete_attachment(attachment["nome_armazenado"])
    flash("Anexo removido.", "success")
    if attachment.get("gasto_id"):
        return redirect(url_for("expense_form", trip_id=trip_id, item_id=attachment["gasto_id"]))
    if attachment.get("atividade_id"):
        return redirect(url_for("activity_form", trip_id=trip_id, item_id=attachment["atividade_id"]))
    return redirect(url_for("trip_documents", trip_id=trip_id))


@app.route("/backups/restore", methods=["GET", "POST"])
def restore_backup():
    if request.method == "GET":
        return render_template("backup_restore.html", preview=None, restore_token=None)

    restore_token = request.form.get("restore_token", "").strip()
    if restore_token and request.form.get("action") == "cancel":
        backup_service.discard_staged_restore(restore_token)
        flash("Restauração cancelada.", "success")
        return redirect(url_for("restore_backup"))

    if restore_token:
        try:
            trips_to_restore, archive_files = backup_service.read_staged_restore(restore_token)
        except ValueError as error:
            flash(str(error), "error")
            return render_template("backup_restore.html", preview=None, restore_token=None)
        try:
            restored = restore_trip_copies(trips_to_restore, archive_files)
        except Exception:
            flash("Não foi possível restaurar o arquivo. Nenhuma viagem existente foi substituída.", "error")
            return render_template("backup_restore.html", preview=None, restore_token=None)
        backup_service.discard_staged_restore(restore_token)
        select_trip(restored[0]["id"])
        flash(f"{len(restored)} viagem(ns) restaurada(s) como cópia(s). Os dados originais foram mantidos.", "success")
        return redirect(url_for("dashboard", trip_id=restored[0]["id"]))

    uploaded_file = request.files.get("backup_file")
    if uploaded_file is None or not uploaded_file.filename:
        flash("Selecione um arquivo JSON ou ZIP de backup.", "error")
        return render_template("backup_restore.html", preview=None, restore_token=None)
    try:
        raw_upload = uploaded_file.stream.read(backup_service.MAX_BACKUP_BYTES + 1)
        trips_to_restore, _ = backup_service.parse_backup_upload(raw_upload)
        restore_token = backup_service.stage_restore_upload(raw_upload)
    except (ValueError, OSError, attachment_service.AttachmentError) as error:
        flash(str(error), "error")
        return render_template("backup_restore.html", preview=None, restore_token=None)

    preview = [
        {
            "destino": trip["destino"],
            "data_ida": trip["data_ida"],
            "data_volta": trip["data_volta"],
            "gastos": len(trip["gastos"]),
            "atividades": len(trip["atividades"]),
        }
        for trip in trips_to_restore
    ]
    return render_template(
        "backup_restore.html",
        preview=preview,
        restore_token=restore_token,
    )


def restore_trip_copies(trips, archive_files):
    attachment_specs = [list(trip.get("anexos", [])) for trip in trips]
    for trip in trips:
        trip["anexos"] = []

    old_backup_state = storage_manager._backup_suspended
    storage_manager._backup_suspended = True
    restored = []
    created_files = []
    try:
        restored = storage_manager.restore_viagens(trips, create_backup=False)
        for trip_index, trip in enumerate(restored):
            people_by_name = {
                person["nome"].casefold(): person["id"]
                for person in trip.get("pessoas", [])
            }
            for expense in trip.get("gastos", []):
                for payment in expense.get("pagamentos", []):
                    participant_name = (payment.get("participante_nome") or "").strip()
                    payment["participante_id"] = people_by_name.get(participant_name.casefold()) if participant_name else None
            trip_attachments = []
            for attachment in attachment_specs[trip_index]:
                archive_path = attachment["archive_path"]
                prepared = attachment_service.prepare_bytes(
                    archive_files[archive_path],
                    attachment["nome_original"],
                )
                metadata = attachment_service.save_prepared_upload(trip["id"], prepared)
                created_files.append(metadata["nome_armazenado"])
                expense_ref = attachment.get("gasto_ref")
                activity_ref = attachment.get("atividade_ref")
                metadata["gasto_id"] = trip["gastos"][expense_ref]["id"] if expense_ref is not None else None
                metadata["atividade_id"] = trip["atividades"][activity_ref]["id"] if activity_ref is not None else None
                metadata["is_capa"] = attachment.get("is_capa", False)
                trip_attachments.append(metadata)
            trip["anexos"] = trip_attachments
            storage_manager.save_viagem(trip)
    except Exception:
        for stored_name in created_files:
            attachment_service.delete_attachment(stored_name)
        for trip in restored:
            storage_manager.delete_viagem(trip["id"])
        raise
    finally:
        storage_manager._backup_suspended = old_backup_state

    storage_manager._ensure_daily_backup()
    return restored


@app.get("/trips/<int:trip_id>/expenses")
def expenses_list(trip_id):
    trip = get_trip_or_404(trip_id)
    select_trip(trip_id)

    category_filter = request.args.get("categoria", "").strip()
    paid_filter = request.args.get("pago", "").strip()
    search_term = request.args.get("busca", "").strip().casefold()
    start_raw = request.args.get("data_inicio", "").strip()
    end_raw = request.args.get("data_fim", "").strip()
    start_date = None
    end_date = None
    if start_raw:
        try:
            start_date = datetime.strptime(start_raw, "%Y-%m-%d").date()
        except ValueError:
            flash("A data inicial do filtro é inválida.", "error")
            start_raw = ""
    if end_raw:
        try:
            end_date = datetime.strptime(end_raw, "%Y-%m-%d").date()
        except ValueError:
            flash("A data final do filtro é inválida.", "error")
            end_raw = ""
    if start_date and end_date and start_date > end_date:
        flash("A data inicial deve ser anterior à data final.", "error")
        start_date = end_date = None

    matching = []
    for expense in trip.get("gastos", []):
        expense_date = datetime.strptime(expense["data_gasto"], "%d/%m/%Y").date()
        if category_filter and expense["categoria"] != category_filter:
            continue
        if start_date and expense_date < start_date:
            continue
        if end_date and expense_date > end_date:
            continue
        if paid_filter == "sim" and not expense.get("pago"):
            continue
        if paid_filter == "nao" and expense.get("pago"):
            continue
        if search_term and search_term not in expense["descricao"].casefold():
            continue
        matching.append(expense)

    matching.sort(
        key=lambda expense: datetime.strptime(expense["data_gasto"], "%d/%m/%Y"),
        reverse=True,
    )
    page_size = 25
    page_count = max(1, ceil(len(matching) / page_size))
    try:
        page = min(max(int(request.args.get("pagina", "1")), 1), page_count)
    except ValueError:
        page = 1
    start_index = (page - 1) * page_size
    shown = matching[start_index:start_index + page_size]
    total_brl = sum((Decimal(str(expense["valor_em_brl"])) for expense in matching), Decimal("0.00"))
    paid_brl = sum((valores_pagamento_gasto(expense)[0] for expense in matching), Decimal("0.00"))
    open_brl = sum((valores_pagamento_gasto(expense)[1] for expense in matching), Decimal("0.00"))
    categories = sorted({item["categoria"] for item in trip.get("planejamento", [])})

    return render_template(
        "expenses.html",
        trip=trip,
        expenses=shown,
        categories=categories,
        filters={
            "categoria": category_filter,
            "data_inicio": start_raw,
            "data_fim": end_raw,
            "pago": paid_filter,
            "busca": request.args.get("busca", "").strip(),
        },
        page=page,
        page_count=page_count,
        result_count=len(matching),
        total_brl=float(total_brl),
        paid_brl=float(paid_brl),
        open_brl=float(open_brl),
    )


@app.get("/trips/<int:trip_id>/activities")
def activities_list(trip_id):
    trip = get_trip_or_404(trip_id)
    select_trip(trip_id)

    start_raw = request.args.get("data_inicio", "").strip()
    end_raw = request.args.get("data_fim", "").strip()
    status_filter = request.args.get("situacao", "").strip()
    search_text = request.args.get("busca", "").strip()
    search_term = search_text.casefold()
    start_date = end_date = None
    if start_raw:
        try:
            start_date = datetime.strptime(start_raw, "%Y-%m-%d").date()
        except ValueError:
            flash("A data inicial do filtro é inválida.", "error")
            start_raw = ""
    if end_raw:
        try:
            end_date = datetime.strptime(end_raw, "%Y-%m-%d").date()
        except ValueError:
            flash("A data final do filtro é inválida.", "error")
            end_raw = ""
    if start_date and end_date and start_date > end_date:
        flash("A data inicial deve ser anterior à data final.", "error")
        start_date = end_date = None
        start_raw = end_raw = ""
    if status_filter and status_filter not in ACTIVITY_STATUSES:
        flash("A situação selecionada é inválida.", "error")
        status_filter = ""

    matching = []
    for activity in trip.get("atividades", []):
        activity_date = datetime.strptime(activity["data"], "%d/%m/%Y").date()
        if start_date and activity_date < start_date:
            continue
        if end_date and activity_date > end_date:
            continue
        if status_filter and activity.get("situacao", "planejada") != status_filter:
            continue
        searchable = " ".join((
            activity.get("nome", ""),
            activity.get("local", ""),
            activity.get("observacao", ""),
        )).casefold()
        if search_term and search_term not in searchable:
            continue
        matching.append(activity)

    matching.sort(key=activity_order_key)
    page_size = 25
    page_count = max(1, ceil(len(matching) / page_size))
    try:
        page = min(max(int(request.args.get("pagina", "1")), 1), page_count)
    except ValueError:
        page = 1
    start_index = (page - 1) * page_size
    shown = matching[start_index:start_index + page_size]
    return render_template(
        "activities.html",
        trip=trip,
        activity_days=group_activities_by_day(shown),
        statuses=ACTIVITY_STATUSES,
        filters={
            "data_inicio": start_raw,
            "data_fim": end_raw,
            "situacao": status_filter,
            "busca": search_text,
        },
        page=page,
        page_count=page_count,
        result_count=len(matching),
        total_count=len(trip.get("atividades", [])),
    )


@app.get("/trips/<int:trip_id>/reservations")
def reservations_list(trip_id):
    trip = get_trip_or_404(trip_id)
    select_trip(trip_id)
    type_filter = request.args.get("tipo", "").strip()
    status_filter = request.args.get("situacao", "").strip()
    search_text = request.args.get("busca", "").strip()
    if type_filter and type_filter not in RESERVATION_TYPES:
        flash("O tipo selecionado não é válido.", "error")
        type_filter = ""
    if status_filter and status_filter not in RESERVATION_STATUSES:
        flash("A situação selecionada não é válida.", "error")
        status_filter = ""

    search_term = search_text.casefold()
    matching = []
    for reservation in trip.get("reservas", []):
        if type_filter and reservation.get("tipo") != type_filter:
            continue
        if status_filter and reservation.get("situacao", "pendente") != status_filter:
            continue
        searchable = " ".join((
            reservation.get("fornecedor", ""),
            reservation.get("codigo_confirmacao", ""),
            reservation.get("local", ""),
            reservation.get("observacao", ""),
        )).casefold()
        if search_term and search_term not in searchable:
            continue
        matching.append(reservation)
    matching.sort(key=lambda item: (datetime.strptime(item["data_inicio"], "%d/%m/%Y"), item.get("fornecedor", "").casefold()))
    matching = add_reservation_deadline_alerts(matching)
    return render_template(
        "reservations.html",
        trip=trip,
        reservations=matching,
        filters={"tipo": type_filter, "situacao": status_filter, "busca": search_text},
        types=RESERVATION_TYPES,
        statuses=RESERVATION_STATUSES,
        result_count=len(matching),
    )


@app.route("/trips/<int:trip_id>/reservations/new", methods=["GET", "POST"])
@app.route("/trips/<int:trip_id>/reservations/<int:item_id>/edit", methods=["GET", "POST"])
def reservation_form(trip_id, item_id=None):
    trip = get_trip_or_404(trip_id)
    select_trip(trip_id)
    item = next((entry for entry in trip.get("reservas", []) if entry.get("id") == item_id), None)
    if item_id is not None and item is None:
        abort(404)

    if request.method == "POST":
        reservation_type = request.form.get("tipo", "").strip()
        provider = request.form.get("fornecedor", "").strip()
        start_date, start_error = parse_form_date(request.form.get("data_inicio"), "a data inicial da reserva")
        end_date, end_error = parse_form_date(request.form.get("data_fim"), "a data final da reserva")
        checkin_time = request.form.get("horario_checkin", "").strip()
        checkout_time = request.form.get("horario_checkout", "").strip()
        time_errors = []
        for value, label in ((checkin_time, "check-in"), (checkout_time, "check-out")):
            if value:
                try:
                    datetime.strptime(value, "%H:%M")
                except ValueError:
                    time_errors.append(f"Informe um horário válido para o {label}.")
        cancellation_deadline_raw = request.form.get("prazo_cancelamento", "").strip()
        if cancellation_deadline_raw:
            cancellation_deadline, deadline_error = parse_form_date(
                cancellation_deadline_raw,
                "o prazo de cancelamento",
            )
        else:
            cancellation_deadline, deadline_error = "", None
        status = request.form.get("situacao", "pendente").strip()
        errors = [error for error in (start_error, end_error, deadline_error) if error]
        errors.extend(time_errors)
        if reservation_type not in RESERVATION_TYPES:
            errors.append("Selecione um tipo válido para a reserva.")
        if not provider:
            errors.append("Informe o fornecedor da reserva.")
        if status not in RESERVATION_STATUSES:
            errors.append("Selecione uma situação válida para a reserva.")
        if start_date and end_date:
            start = datetime.strptime(start_date, "%d/%m/%Y").date()
            end = datetime.strptime(end_date, "%d/%m/%Y").date()
            trip_start = datetime.strptime(trip["data_ida"], "%d/%m/%Y").date()
            trip_end = datetime.strptime(trip["data_volta"], "%d/%m/%Y").date()
            if end < start:
                errors.append("A data final da reserva não pode ser anterior à inicial.")
            elif not trip_start <= start <= end <= trip_end:
                errors.append(f"As datas da reserva devem ficar entre {trip['data_ida']} e {trip['data_volta']}.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "reservation_form.html",
                trip=trip,
                item=item,
                types=RESERVATION_TYPES,
                statuses=RESERVATION_STATUSES,
            )

        values = {
            "tipo": reservation_type,
            "fornecedor": provider,
            "codigo_confirmacao": request.form.get("codigo_confirmacao", "").strip(),
            "data_inicio": start_date,
            "horario_checkin": checkin_time,
            "data_fim": end_date,
            "horario_checkout": checkout_time,
            "local": request.form.get("local", "").strip(),
            "prazo_cancelamento": cancellation_deadline,
            "situacao": status,
            "observacao": request.form.get("observacao", "").strip(),
        }
        if item is None:
            trip.setdefault("reservas", []).append(values)
        else:
            item.update(values)
        storage_manager.save_viagem(trip)
        flash("Reserva salva.", "success")
        return redirect(url_for("reservations_list", trip_id=trip_id))

    return render_template(
        "reservation_form.html",
        trip=trip,
        item=item,
        types=RESERVATION_TYPES,
        statuses=RESERVATION_STATUSES,
    )


@app.post("/trips/<int:trip_id>/reservations/<int:item_id>/delete")
def delete_reservation(trip_id, item_id):
    trip = get_trip_or_404(trip_id)
    reservations = trip.get("reservas", [])
    if not any(reservation.get("id") == item_id for reservation in reservations):
        abort(404)
    trip["reservas"] = [reservation for reservation in reservations if reservation.get("id") != item_id]
    storage_manager.save_viagem(trip)
    flash("Reserva removida.", "success")
    return redirect(url_for("reservations_list", trip_id=trip_id))


@app.get("/trips/<int:trip_id>/activities/print")
def itinerary_print(trip_id):
    trip = get_trip_or_404(trip_id)
    select_trip(trip_id)
    activities = sorted(trip.get("atividades", []), key=activity_order_key)
    return render_template(
        "itinerary_print.html",
        trip=trip,
        activity_days=group_activities_by_day(activities),
        activity_count=len(activities),
    )


@app.route("/trips/new", methods=["GET", "POST"])
def new_trip():
    if request.method == "POST":
        destination = request.form.get("destino", "").strip()
        try:
            flag = parse_country_code(request.form.get("bandeira"))
            flag_error = None
        except ValueError as error:
            flag, flag_error = "", str(error)
        departure, departure_error = parse_form_date(request.form.get("data_ida"), "a data de ida")
        return_date, return_error = parse_form_date(request.form.get("data_volta"), "a data de volta")
        errors = [error for error in (departure_error, return_error) if error]
        if flag_error:
            errors.append(flag_error)

        if not destination:
            errors.append("Informe o destino da viagem.")
        if departure and return_date and datetime.strptime(return_date, "%d/%m/%Y") < datetime.strptime(departure, "%d/%m/%Y"):
            errors.append("A data de volta não pode ser anterior à data de ida.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("trip_form.html", trip=None)

        trip = {
            "destino": destination,
            "bandeira": flag,
            "data_ida": departure,
            "data_volta": return_date,
            "orcamento_total": 0.0,
            "gastos": [],
            "atividades": [],
            "planejamento": [],
        }
        storage_manager.save_viagem(trip)
        select_trip(trip["id"])
        flash("Viagem criada.", "success")
        return redirect(url_for("dashboard", trip_id=trip["id"]))

    return render_template("trip_form.html", trip=None)


@app.route("/trips/<int:trip_id>/edit", methods=["GET", "POST"])
def edit_trip(trip_id):
    trip = get_trip_or_404(trip_id)
    select_trip(trip_id)
    if request.method == "POST":
        destination = request.form.get("destino", "").strip()
        try:
            flag = parse_country_code(request.form.get("bandeira"))
            flag_error = None
        except ValueError as error:
            flag, flag_error = "", str(error)
        departure, departure_error = parse_form_date(request.form.get("data_ida"), "a data de ida")
        return_date, return_error = parse_form_date(request.form.get("data_volta"), "a data de volta")
        errors = [error for error in (departure_error, return_error) if error]
        if flag_error:
            errors.append(flag_error)

        if not destination:
            errors.append("Informe o destino da viagem.")
        if departure and return_date and datetime.strptime(return_date, "%d/%m/%Y") < datetime.strptime(departure, "%d/%m/%Y"):
            errors.append("A data de volta não pode ser anterior à data de ida.")

        if not errors:
            updated_trip = {**trip, "data_ida": departure, "data_volta": return_date}
            outside = [
                activity["nome"]
                for activity in trip.get("atividades", [])
                if not data_esta_no_periodo(activity["data"], updated_trip)
            ]
            if outside:
                errors.append(
                    "O novo período deixaria estas atividades fora da viagem: "
                    + ", ".join(outside)
                    + "."
                )

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("trip_form.html", trip=trip)

        trip.update({
            "destino": destination,
            "bandeira": flag,
            "data_ida": departure,
            "data_volta": return_date,
        })
        storage_manager.save_viagem(trip)
        flash("Dados da viagem atualizados.", "success")
        return redirect(url_for("dashboard", trip_id=trip_id))

    return render_template("trip_form.html", trip=trip)


@app.route("/trips/<int:trip_id>/planning", methods=["GET", "POST"])
def edit_planning(trip_id):
    trip = get_trip_or_404(trip_id)
    select_trip(trip_id)
    existing = {item["categoria"]: item for item in trip.get("planejamento", [])}
    categories = [item["categoria"] for item in trip.get("planejamento", [])]

    if request.method == "POST":
        planning = []
        errors = []
        for index, category in enumerate(categories):
            raw_amount = request.form.get(f"previsto_{index}", "")
            amount, error = parse_amount(raw_amount, f"O previsto de {category}", required=False)
            if error:
                errors.append(error)
            else:
                planning.append({"categoria": category, "valor_previsto": amount or 0.0})

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("planning_form.html", trip=trip, planning=existing, categories=categories)

        trip["planejamento"] = planning
        storage_manager.save_viagem(trip)
        flash("Planejamento por categoria salvo.", "success")
        return redirect(url_for("dashboard", trip_id=trip_id) + "#resumo")

    return render_template("planning_form.html", trip=trip, planning=existing, categories=categories)


def apply_posted_planning_amounts(planning):
    for index, item in enumerate(planning):
        raw_amount = request.form.get(f"previsto_{index}")
        if raw_amount is None:
            continue
        amount, error = parse_amount(raw_amount, f"O previsto de {item['categoria']}", required=False)
        if not error:
            item["valor_previsto"] = amount or 0.0


@app.post("/trips/<int:trip_id>/planning/categories")
def add_planning_category(trip_id):
    trip = get_trip_or_404(trip_id)
    category = request.form.get("categoria_nova", "").strip()
    existing = trip.setdefault("planejamento", [])
    apply_posted_planning_amounts(existing)

    if not category:
        flash("Informe o nome da categoria.", "error")
    elif len(category) > 100:
        flash("O nome da categoria deve ter até 100 caracteres.", "error")
    elif any(item["categoria"].casefold() == category.casefold() for item in existing):
        flash("Essa categoria já existe nesta viagem.", "error")
    else:
        existing.append({"categoria": category, "valor_previsto": 0.0})
        flash("Categoria adicionada.", "success")
    storage_manager.save_viagem(trip)
    return redirect(url_for("edit_planning", trip_id=trip_id))


@app.post("/trips/<int:trip_id>/planning/categories/<int:category_index>/delete")
def delete_planning_category(trip_id, category_index):
    trip = get_trip_or_404(trip_id)
    planning = trip.get("planejamento", [])
    if category_index < 0 or category_index >= len(planning):
        abort(404)
    apply_posted_planning_amounts(planning)
    category = planning[category_index]["categoria"]
    if any(expense["categoria"] == category for expense in trip.get("gastos", [])):
        storage_manager.save_viagem(trip)
        flash("Não é possível remover uma categoria que já possui gastos.", "error")
        return redirect(url_for("edit_planning", trip_id=trip_id))

    trip["planejamento"].pop(category_index)
    storage_manager.save_viagem(trip)
    flash("Categoria removida.", "success")
    return redirect(url_for("edit_planning", trip_id=trip_id))


@app.post("/trips/<int:trip_id>/delete")
def delete_trip(trip_id):
    trip = get_trip_or_404(trip_id)
    attachments = list(trip.get("anexos", []))
    storage_manager.delete_viagem(trip_id)
    for attachment in attachments:
        attachment_service.delete_attachment(attachment["nome_armazenado"])
    if session.get("selected_trip_id") == trip_id:
        session.pop("selected_trip_id", None)
    flash("Viagem removida.", "success")
    return redirect(url_for("index"))


@app.route("/trips/<int:trip_id>/people", methods=["GET", "POST"])
def trip_people(trip_id):
    trip = get_trip_or_404(trip_id)
    select_trip(trip_id)
    if request.method == "POST":
        name = request.form.get("nome", "").strip()
        people = trip.setdefault("pessoas", [])
        if not name:
            flash("Informe o nome do participante.", "error")
        elif len(name) > 150:
            flash("O nome deve ter até 150 caracteres.", "error")
        elif any(person["nome"].casefold() == name.casefold() for person in people):
            flash("Esse participante já está cadastrado nesta viagem.", "error")
        else:
            people.append({"nome": name})
            storage_manager.save_viagem(trip)
            flash("Participante adicionado.", "success")
        return redirect(url_for("trip_people", trip_id=trip_id))

    payments_by_person = {}
    for expense in trip.get("gastos", []):
        for payment in expense.get("pagamentos", []):
            participant_id = payment.get("participante_id")
            if participant_id is not None:
                payments_by_person[participant_id] = payments_by_person.get(participant_id, 0.0) + float(payment.get("valor_brl", 0))
    return render_template(
        "participants.html",
        trip=trip,
        payments_by_person=payments_by_person,
    )


@app.post("/trips/<int:trip_id>/people/<int:participant_id>/delete")
def delete_trip_person(trip_id, participant_id):
    trip = get_trip_or_404(trip_id)
    people = trip.get("pessoas", [])
    person = next((person for person in people if person.get("id") == participant_id), None)
    if person is None:
        abort(404)
    if any(
        payment.get("participante_id") == participant_id
        for expense in trip.get("gastos", [])
        for payment in expense.get("pagamentos", [])
    ):
        flash("Não é possível remover uma pessoa associada a pagamentos registrados.", "error")
        return redirect(url_for("trip_people", trip_id=trip_id))
    trip["pessoas"] = [person for person in people if person.get("id") != participant_id]
    storage_manager.save_viagem(trip)
    flash("Participante removido.", "success")
    return redirect(url_for("trip_people", trip_id=trip_id))


def payment_rows_for_expense(expense, form=None):
    if form is not None:
        participant_ids = form.getlist("pagador_id")
        amounts = form.getlist("valor_pago")
        methods = form.getlist("forma_pagamento_pagador")
        row_count = max(len(participant_ids), len(amounts), len(methods))
        submitted_rows = []
        for index in range(row_count):
            participant_id = participant_ids[index] if index < len(participant_ids) else ""
            amount = amounts[index] if index < len(amounts) else ""
            method = methods[index] if index < len(methods) else ""
            submitted_rows.append({
                "participante_id": participant_id,
                "valor_brl": amount,
                "forma_pagamento": method,
            })
        if submitted_rows:
            return submitted_rows
    payments = expense.get("pagamentos", []) if expense else []
    if payments:
        return payments
    if expense and expense.get("pago"):
        return [{
            "participante_id": "",
            "valor_brl": expense.get("valor_em_brl", 0),
            "forma_pagamento": expense.get("forma_pagamento") or "",
        }]
    return []


def parse_expense_payment_rows(form, trip, expense_total):
    participant_ids = form.getlist("pagador_id")
    amounts = form.getlist("valor_pago")
    methods = form.getlist("forma_pagamento_pagador")
    participants = {str(person["id"]): person for person in trip.get("pessoas", []) if person.get("id") is not None}
    payments = []
    errors = []
    total_paid = Decimal("0.00")

    for index in range(max(len(participant_ids), len(amounts), len(methods))):
        participant_raw = participant_ids[index].strip() if index < len(participant_ids) else ""
        amount_raw = amounts[index].strip() if index < len(amounts) else ""
        method = methods[index].strip() if index < len(methods) else ""
        if not participant_raw and not amount_raw and not method:
            continue
        if not amount_raw:
            errors.append("Informe o valor pago em cada contribuição.")
            continue
        amount, amount_error = parse_amount(amount_raw, "O valor pago", required=True)
        if amount_error:
            errors.append(amount_error)
            continue
        if amount <= 0:
            errors.append("Cada contribuição deve ser maior que zero.")
            continue
        participant_id = None
        if participant_raw:
            if participant_raw not in participants:
                errors.append("Selecione uma pessoa cadastrada nesta viagem.")
                continue
            participant_id = int(participant_raw)
        if method and method not in PAYMENT_METHODS:
            errors.append("Selecione uma forma de pagamento válida para cada contribuição.")
            continue
        total_paid += Decimal(str(amount))
        payments.append({
            "participante_id": participant_id,
            "valor_brl": amount,
            "forma_pagamento": method,
        })

    if expense_total is not None and total_paid > expense_total:
        errors.append("A soma paga não pode ultrapassar o valor total do gasto em reais.")
    return payments, total_paid, errors


@app.route("/trips/<int:trip_id>/expenses/new", methods=["GET", "POST"])
@app.route("/trips/<int:trip_id>/expenses/<int:item_id>/edit", methods=["GET", "POST"])
def expense_form(trip_id, item_id=None):
    trip = get_trip_or_404(trip_id)
    select_trip(trip_id)
    item = next((expense for expense in trip.get("gastos", []) if expense.get("id") == item_id), None)
    if item_id is not None and item is None:
        abort(404)

    if request.method == "POST":
        description = request.form.get("descricao", "").strip()
        category = request.form.get("categoria", "").strip()
        expense_date, date_error = parse_form_date(request.form.get("data_gasto"), "a data do gasto")
        is_paid = request.form.get("pago", "0") == "1"
        currency = request.form.get("moeda", "BRL").strip().upper()
        original_amount, original_error = parse_amount(
            request.form.get("valor_original", ""),
            "O valor original",
            required=True,
        )
        payment_method = request.form.get("forma_pagamento", "").strip()
        upload_errors = []
        try:
            uploads = prepare_attachment_uploads(request.files.getlist("anexos"))
        except attachment_service.AttachmentError as error:
            uploads = []
            upload_errors.append(str(error))
        if currency == "BRL":
            rate, rate_error = 1.0, None
        else:
            rate, rate_error = parse_amount(
                request.form.get("cotacao", ""),
                "A cotação",
                required=True,
            )
        converted_total = (
            (Decimal(str(original_amount)) * Decimal(str(rate))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if original_amount is not None and rate is not None
            else None
        )
        payments, total_paid, payment_errors = parse_expense_payment_rows(request.form, trip, converted_total)
        errors = [error for error in (date_error, original_error, rate_error) if error]
        errors.extend(payment_errors)
        errors.extend(upload_errors)
        if not description:
            errors.append("Informe a descrição do gasto.")
        if not category:
            errors.append("Informe a categoria do gasto.")
        elif category not in {item["categoria"] for item in trip.get("planejamento", [])}:
            errors.append("Cadastre a categoria no planejamento desta viagem antes de lançar o gasto.")
        if currency not in SUPPORTED_CURRENCIES:
            errors.append("Selecione uma moeda suportada: BRL, CLP, USD ou EUR.")
        if original_amount is not None and original_amount <= 0:
            errors.append("O valor original deve ser maior que zero.")
        if currency != "BRL" and rate is not None and rate <= 0:
            errors.append(f"A cotação {currency}→BRL deve ser maior que zero.")
        if is_paid and not payments and payment_method not in PAYMENT_METHODS:
            errors.append("Selecione a forma de pagamento do gasto pago.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "record_form.html",
                trip=trip,
                item=item,
                record_type="expense",
                payment_rows=payment_rows_for_expense(item, request.form),
                payment_methods=PAYMENT_METHODS,
                attachments=attachments_for_record(trip, expense_id=item.get("id") if item else None),
            )

        if payments:
            is_paid = total_paid >= converted_total

        values = {
            "data_gasto": expense_date,
            "descricao": description,
            "categoria": category,
            "moeda": currency,
            "valor_original": original_amount,
            "cotacao": rate,
            "valor_em_brl": float(converted_total),
            "forma_pagamento": None if payments else (payment_method or None),
            "observacao": request.form.get("observacao", "").strip(),
            "pago": is_paid,
            "pagamentos": payments,
        }
        if item is None:
            trip.setdefault("gastos", []).append(values)
        else:
            item.update(values)
        storage_manager.save_viagem(trip)
        saved_expense = item if item is not None else values
        if uploads:
            try:
                save_trip_attachments(trip, uploads, expense_id=saved_expense["id"])
            except Exception as error:
                flash(report_attachment_error(error), "error")
        flash("Gasto salvo.", "success")
        return redirect(url_for("dashboard", trip_id=trip_id) + "#gastos")

    return render_template(
        "record_form.html",
        trip=trip,
        item=item,
        record_type="expense",
        payment_rows=payment_rows_for_expense(item),
        payment_methods=PAYMENT_METHODS,
        attachments=attachments_for_record(trip, expense_id=item.get("id") if item else None),
    )


@app.post("/trips/<int:trip_id>/expenses/<int:item_id>/delete")
def delete_expense(trip_id, item_id):
    trip = get_trip_or_404(trip_id)
    expenses = trip.get("gastos", [])
    expense = next((expense for expense in expenses if expense.get("id") == item_id), None)
    if expense is None:
        abort(404)
    removed_attachments = [attachment for attachment in trip.get("anexos", []) if attachment.get("gasto_id") == item_id]
    trip["anexos"] = [attachment for attachment in trip.get("anexos", []) if attachment.get("gasto_id") != item_id]
    trip["gastos"] = [expense for expense in expenses if expense.get("id") != item_id]
    storage_manager.save_viagem(trip)
    for attachment in removed_attachments:
        attachment_service.delete_attachment(attachment["nome_armazenado"])
    flash("Gasto removido.", "success")
    return redirect(url_for(
        "expenses_list",
        trip_id=trip_id,
        categoria=request.form.get("categoria", ""),
        data_inicio=request.form.get("data_inicio", ""),
        data_fim=request.form.get("data_fim", ""),
        pago=request.form.get("pago", ""),
        busca=request.form.get("busca", ""),
        pagina=request.form.get("pagina", "1"),
    ))


@app.route("/trips/<int:trip_id>/activities/new", methods=["GET", "POST"])
@app.route("/trips/<int:trip_id>/activities/<int:item_id>/edit", methods=["GET", "POST"])
def activity_form(trip_id, item_id=None):
    trip = get_trip_or_404(trip_id)
    select_trip(trip_id)
    item = next((activity for activity in trip.get("atividades", []) if activity.get("id") == item_id), None)
    if item_id is not None and item is None:
        abort(404)

    if request.method == "POST":
        name = request.form.get("nome", "").strip()
        activity_date, date_error = parse_form_date(request.form.get("data"), "a data da atividade")
        cost, cost_error = parse_amount(
            request.form.get("custo_estimado", ""),
            "O custo estimado",
            required=False,
        )
        time_value = request.form.get("horario", "").strip()
        if time_value:
            try:
                datetime.strptime(time_value, "%H:%M")
            except ValueError:
                time_error = "Informe um horário válido."
            else:
                time_error = None
        else:
            time_error = None
        status = request.form.get(
            "situacao",
            item.get("situacao", "planejada") if item else "planejada",
        ).strip()
        upload_errors = []
        try:
            uploads = prepare_attachment_uploads(request.files.getlist("anexos"))
        except attachment_service.AttachmentError as error:
            uploads = []
            upload_errors.append(str(error))
        errors = [error for error in (date_error, cost_error, time_error) if error]
        errors.extend(upload_errors)
        if not name:
            errors.append("Informe o nome da atividade.")
        if activity_date and not data_esta_no_periodo(activity_date, trip):
            errors.append(f"A atividade deve ocorrer entre {trip['data_ida']} e {trip['data_volta']}.")
        if status not in ACTIVITY_STATUSES:
            errors.append("Selecione uma situação válida para a atividade.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "record_form.html",
                trip=trip,
                item=item,
                record_type="activity",
                activity_statuses=ACTIVITY_STATUSES,
                attachments=attachments_for_record(trip, activity_id=item.get("id") if item else None),
            )

        values = {
            "nome": name,
            "data": activity_date,
            "horario": time_value,
            "local": request.form.get("local", "").strip(),
            "custo_estimado": cost,
            "observacao": request.form.get("observacao", "").strip(),
            "situacao": status,
        }
        if item is None:
            trip.setdefault("atividades", []).append(values)
        else:
            item.update(values)
        storage_manager.save_viagem(trip)
        saved_activity = item if item is not None else values
        if uploads:
            try:
                save_trip_attachments(trip, uploads, activity_id=saved_activity["id"])
            except Exception as error:
                flash(report_attachment_error(error), "error")
        flash("Atividade salva.", "success")
        return redirect(url_for("activities_list", trip_id=trip_id))

    return render_template(
        "record_form.html",
        trip=trip,
        item=item,
        record_type="activity",
        activity_statuses=ACTIVITY_STATUSES,
        attachments=attachments_for_record(trip, activity_id=item.get("id") if item else None),
    )


@app.get("/trips/<int:trip_id>/activities/<int:item_id>")
def activity_detail(trip_id, item_id):
    trip = get_trip_or_404(trip_id)
    activity = next((item for item in trip.get("atividades", []) if item.get("id") == item_id), None)
    if activity is None:
        abort(404)
    select_trip(trip_id)
    return render_template(
        "activity_detail.html",
        trip=trip,
        activity=activity,
        attachments=attachments_for_record(trip, activity_id=item_id),
    )


@app.post("/trips/<int:trip_id>/activities/<int:item_id>/status")
def update_activity_status(trip_id, item_id):
    trip = get_trip_or_404(trip_id)
    activity = next((item for item in trip.get("atividades", []) if item.get("id") == item_id), None)
    if activity is None:
        abort(404)

    origin = request.form.get("origin")
    if origin not in {"dashboard", "activities"}:
        abort(400)
    action = request.form.get("action")
    if action not in {"complete", "reopen"}:
        abort(400)
    select_trip(trip_id)

    status = activity.get("situacao", "planejada")
    if action == "complete" and status in ("planejada", "reservada"):
        activity["situacao"] = "realizada"
        storage_manager.save_viagem(trip)
        flash("Atividade marcada como realizada.", "success")
    elif action == "reopen" and status == "realizada":
        activity["situacao"] = "planejada"
        storage_manager.save_viagem(trip)
        flash("Atividade reaberta como planejada.", "success")
    elif action == "complete" and status == "realizada":
        flash("Esta atividade já está marcada como realizada.", "info")
    elif action == "reopen" and status in ("planejada", "reservada"):
        flash("Esta atividade já está pendente.", "info")
    else:
        flash("Atividades canceladas não podem ter a situação alterada por esta ação.", "error")

    endpoint = "dashboard" if origin == "dashboard" else "activities_list"
    return redirect(url_for(endpoint, trip_id=trip_id))


@app.post("/trips/<int:trip_id>/activities/<int:item_id>/delete")
def delete_activity(trip_id, item_id):
    trip = get_trip_or_404(trip_id)
    activities = trip.get("atividades", [])
    if not any(activity.get("id") == item_id for activity in activities):
        abort(404)
    removed_attachments = [attachment for attachment in trip.get("anexos", []) if attachment.get("atividade_id") == item_id]
    trip["anexos"] = [attachment for attachment in trip.get("anexos", []) if attachment.get("atividade_id") != item_id]
    trip["atividades"] = [activity for activity in activities if activity.get("id") != item_id]
    storage_manager.save_viagem(trip)
    for attachment in removed_attachments:
        attachment_service.delete_attachment(attachment["nome_armazenado"])
    flash("Atividade removida.", "success")
    return redirect(url_for("activities_list", trip_id=trip_id))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("APP_PORT", "5000")), debug=False)