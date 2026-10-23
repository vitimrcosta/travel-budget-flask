import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
import re
import zipfile
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from werkzeug.datastructures import FileStorage

import backup_service
import attachment_service
import db_service
import main
from currency_rates import ExchangeRateError, get_historical_rate
from backup_service import make_trip_export, parse_backup_archive, parse_backup_bytes, validate_backup_document, write_daily_backup
from web_app import add_reservation_deadline_alerts, app, find_next_activity


class ExchangeRateTests(unittest.TestCase):
    def test_alerta_prazo_cancelamento_se_aproximando_e_vencido(self):
        reservations = [
            {"situacao": "confirmada", "prazo_cancelamento": "08/06/2026"},
            {"situacao": "confirmada", "prazo_cancelamento": "15/06/2026"},
            {"situacao": "pendente", "prazo_cancelamento": "07/06/2026"},
            {"situacao": "cancelada", "prazo_cancelamento": "08/06/2026"},
        ]

        annotated = add_reservation_deadline_alerts(reservations, date(2026, 6, 8))

        self.assertEqual(annotated[0]["alerta_prazo"], "O prazo de cancelamento gratuito termina hoje.")
        self.assertEqual(annotated[1]["alerta_prazo"], "Cancelamento gratuito até 15/06/2026.")
        self.assertEqual(annotated[2]["alerta_prazo"], "Prazo de cancelamento gratuito encerrado em 07/06/2026.")
        self.assertNotIn("alerta_prazo", annotated[3])
        self.assertNotIn("alerta_prazo", reservations[0])

    def test_backup_rejeita_horario_invalido_de_reserva(self):
        trip = {
            "destino": "Lisboa",
            "data_ida": "10/06/2026",
            "data_volta": "15/06/2026",
            "planejamento": [],
            "pessoas": [],
            "gastos": [],
            "atividades": [],
            "anexos": [],
            "reservas": [{
                "tipo": "hospedagem",
                "fornecedor": "Hotel Central",
                "data_inicio": "12/06/2026",
                "horario_checkin": "25:99",
                "data_fim": "14/06/2026",
                "situacao": "confirmada",
            }],
        }

        with self.assertRaisesRegex(ValueError, "Horário de check-in inválido"):
            validate_backup_document(make_trip_export(trip))

    def test_busca_cotacao_historica_e_data_efetiva(self):
        response = Mock()
        response.read.return_value = b'{"date":"2026-06-12","base":"USD","quote":"BRL","rate":5.42}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)

        with patch("currency_rates.urlopen", return_value=response) as mocked_urlopen:
            result = get_historical_rate("USD", date(2026, 6, 12))

        self.assertEqual(result["rate"], Decimal("5.42"))
        self.assertEqual(result["date"], "2026-06-12")
        self.assertIn("/usd/brl?date=2026-06-12", mocked_urlopen.call_args.args[0].full_url)

    def test_rejeita_moeda_nao_suportada_sem_chamar_api(self):
        with patch("currency_rates.urlopen") as mocked_urlopen:
            with self.assertRaises(ExchangeRateError):
                get_historical_rate("JPY", date(2026, 6, 12))

        mocked_urlopen.assert_not_called()


class BackupServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.original_backup_dir = backup_service.BACKUP_DIR
        self.original_attachment_dir = attachment_service.ATTACHMENT_DIR
        backup_service.BACKUP_DIR = Path(self.temp_dir.name)
        attachment_service.ATTACHMENT_DIR = Path(self.temp_dir.name) / "attachments"

    def tearDown(self):
        backup_service.BACKUP_DIR = self.original_backup_dir
        attachment_service.ATTACHMENT_DIR = self.original_attachment_dir
        self.temp_dir.cleanup()

    def sample_trip(self, destination="Rota Backup"):
        return {
            "id": 7,
            "destino": destination,
            "data_ida": "10/06/2026",
            "data_volta": "15/06/2026",
            "planejamento": [{"id": 2, "categoria": "Passeios", "valor_previsto": 500}],
            "reservas": [{
                "id": 5,
                "tipo": "hospedagem",
                "fornecedor": "Hotel Central",
                "codigo_confirmacao": "ABC123",
                "data_inicio": "12/06/2026",
                "data_fim": "14/06/2026",
                "local": "Centro",
                "prazo_cancelamento": "10/06/2026",
                "situacao": "confirmada",
                "observacao": "Check-in após 15h",
            }],
            "gastos": [{
                "id": 3,
                "data_gasto": "12/06/2026",
                "descricao": "Museu",
                "categoria": "Passeios",
                "moeda": "USD",
                "valor_original": 10,
                "cotacao": 5,
                "valor_em_brl": 50,
                "pago": False,
            }],
            "atividades": [{"id": 4, "nome": "Visita", "data": "13/06/2026", "horario": "10:00", "situacao": "reservada"}],
            "pessoas": [],
            "anexos": [],
        }

    def test_exportacao_validacao_e_ids_removidos(self):
        exported = make_trip_export(self.sample_trip())
        restored = validate_backup_document(exported)[0]
        self.assertEqual(restored["gastos"][0]["valor_em_brl"], 50.0)
        self.assertEqual(restored["atividades"][0]["situacao"], "reservada")
        self.assertEqual(restored["reservas"][0]["fornecedor"], "Hotel Central")
        self.assertEqual(restored["reservas"][0]["situacao"], "confirmada")
        self.assertNotIn("id", restored)
        self.assertNotIn("id", restored["gastos"][0])
        self.assertNotIn("id", restored["reservas"][0])
        legacy_trip = self.sample_trip()
        legacy_trip.pop("reservas")
        restored_legacy = validate_backup_document(make_trip_export(legacy_trip))[0]
        self.assertEqual(restored_legacy["reservas"], [])

    def test_backup_diario_nao_sobrescreve_e_retencao_e_limitada(self):
        from datetime import datetime, timezone, timedelta

        first_day = datetime(2026, 1, 1, tzinfo=timezone.utc)
        first = write_daily_backup([self.sample_trip("Original")], first_day)
        write_daily_backup([self.sample_trip("Alterada")], first_day)
        with zipfile.ZipFile(first) as backup_file:
            document = json.loads(backup_file.read("backup.json"))
        self.assertEqual(document["trips"][0]["destino"], "Original")

        for day_offset in range(1, 31):
            write_daily_backup(
                [self.sample_trip()],
                first_day + timedelta(days=day_offset),
            )
        daily_files = list(Path(self.temp_dir.name).glob("controle-viagem-*.zip"))
        self.assertEqual(len(daily_files), backup_service.MAX_DAILY_BACKUPS)

    def test_zip_preserva_anexo_e_referencia_de_gasto(self):
        trip = self.sample_trip()
        prepared = attachment_service.prepare_bytes(b"%PDF-1.7\nrecibo", "recibo.pdf")
        metadata = attachment_service.save_prepared_upload(trip["id"], prepared)
        metadata.update({"gasto_id": 3, "atividade_id": None})
        trip["anexos"].append(metadata)
        try:
            archive_data = backup_service.build_trip_archive(trip)
            restored, files = backup_service.parse_backup_archive(archive_data)
            imported_attachment = restored[0]["anexos"][0]
            self.assertEqual(files[imported_attachment["archive_path"]], b"%PDF-1.7\nrecibo")
            self.assertEqual(imported_attachment["gasto_ref"], 0)
            self.assertIsNone(imported_attachment["atividade_ref"])
        finally:
            attachment_service.delete_attachment(metadata["nome_armazenado"])

    def test_rejeita_json_invalido(self):
        with self.assertRaises(ValueError):
            parse_backup_bytes(b"{invalido")

    def test_rejeita_anexo_com_extensao_falsa(self):
        with self.assertRaises(attachment_service.AttachmentError):
            attachment_service.prepare_upload(
                FileStorage(stream=BytesIO(b"conteudo que nao e PDF"), filename="recibo.pdf")
            )


class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.original_data_file = db_service.DATA_FILE
        self.original_mysql_enabled = db_service.storage_manager.mysql_enabled
        self.original_backup_dir = backup_service.BACKUP_DIR
        self.original_attachment_dir = attachment_service.ATTACHMENT_DIR
        db_service.DATA_FILE = Path(self.temp_dir.name) / "web_data.json"
        backup_service.BACKUP_DIR = Path(self.temp_dir.name) / "backups"
        attachment_service.ATTACHMENT_DIR = Path(self.temp_dir.name) / "attachments"
        db_service.storage_manager.mysql_enabled = False
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = app.test_client()

    def tearDown(self):
        db_service.DATA_FILE = self.original_data_file
        db_service.storage_manager.mysql_enabled = self.original_mysql_enabled
        backup_service.BACKUP_DIR = self.original_backup_dir
        attachment_service.ATTACHMENT_DIR = self.original_attachment_dir
        self.temp_dir.cleanup()

    def test_crud_web_com_validacao_de_periodo(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Planejar uma viagem", response.get_data(as_text=True))
        self.assertIn('data-theme-toggle aria-label="Ativar modo escuro" aria-pressed="false"', response.get_data(as_text=True))
        page = response.get_data(as_text=True)
        self.assertIn('class="button button-primary topbar-link"', page)
        self.assertIn('class="topbar-utility-link"', page)
        self.assertLess(page.index('data-theme-toggle'), page.index('class="topbar-utility-link"'))
        self.assertLess(page.index('class="topbar-utility-link"'), page.index('class="button button-primary topbar-link"'))

        response = self.client.post(
            "/trips/new",
            data={
                "destino": "Rota Teste",
                "data_ida": "2026-06-10",
                "data_volta": "2026-06-15",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Rota Teste", response.get_data(as_text=True))
        with self.client.session_transaction() as browser_session:
            trip_id = browser_session["selected_trip_id"]
        home_response = self.client.get("/")
        self.assertEqual(home_response.status_code, 200)
        self.assertIn("Planejar uma viagem", home_response.get_data(as_text=True))
        self.assertIn("Rota Teste", home_response.get_data(as_text=True))

        self.assertEqual(self.client.get(f"/trips/{trip_id}/edit").status_code, 200)
        self.assertEqual(self.client.get(f"/trips/{trip_id}/expenses/new").status_code, 200)
        expense_form = self.client.get(f"/trips/{trip_id}/expenses/new").get_data(as_text=True)
        self.assertIn("USD · Dólar americano", expense_form)
        self.assertIn("EUR · Euro", expense_form)
        self.assertEqual(self.client.get(f"/trips/{trip_id}/activities/new").status_code, 200)
        activity_form = self.client.get(f"/trips/{trip_id}/activities/new").get_data(as_text=True)
        self.assertIn('class="field-help"', activity_form)
        self.assertIn('aria-label="Ajuda sobre a situação da atividade"', activity_form)
        for status_help in (
            "Planejada:",
            "prevista, ainda sem confirmação.",
            "Reservada:",
            "voo, ingresso ou serviço confirmado.",
            "Realizada:",
            "já aconteceu.",
            "Cancelada:",
            "não vai acontecer.",
        ):
            self.assertIn(status_help, activity_form)
        self.assertEqual(self.client.get(f"/trips/{trip_id}/activities").status_code, 200)
        self.assertEqual(self.client.get(f"/trips/{trip_id}/activities/print").status_code, 200)
        self.assertEqual(self.client.get(f"/trips/{trip_id}/planning").status_code, 200)

        for category in ("Passagens", "Hospedagem", "Passeios"):
            response = self.client.post(
                f"/trips/{trip_id}/planning/categories",
                data={"categoria_nova": category},
                follow_redirects=True,
            )
            self.assertIn("Categoria adicionada", response.get_data(as_text=True))

        response = self.client.post(
            f"/trips/{trip_id}/planning",
            data={"previsto_0": "6.261,30", "previsto_1": "1.200,00"},
            follow_redirects=True,
        )
        self.assertIn("R$ 7.461,30", response.get_data(as_text=True))

        response = self.client.post(
            f"/trips/{trip_id}/expenses/new",
            data={
                "data_gasto": "2026-06-11",
                "descricao": "Hospedagem",
                "categoria": "Hospedagem",
                "valor_original": "180,50",
                "moeda": "BRL",
                "pago": "1",
                "forma_pagamento": "Pix",
            },
            follow_redirects=True,
        )
        self.assertIn("Hospedagem", response.get_data(as_text=True))

        pending_response = self.client.post(
            f"/trips/{trip_id}/expenses/new",
            data={
                "data_gasto": "2026-06-12",
                "descricao": "Passeio futuro",
                "categoria": "Passeios",
                "valor_original": "50.000,00",
                "pago": "0",
                "moeda": "CLP",
                "cotacao": "0,0055",
            },
            follow_redirects=True,
        )
        self.assertIn("Pendente", pending_response.get_data(as_text=True))
        self.assertIn("R$ 455,50", pending_response.get_data(as_text=True))

        with patch(
            "web_app.get_historical_rate",
            return_value={"currency": "USD", "rate": Decimal("5.42"), "date": "2026-06-13"},
        ):
            quote_response = self.client.get(
                "/api/exchange-rate",
                query_string={"currency": "USD", "date": "2026-06-13"},
            )
        self.assertEqual(quote_response.status_code, 200)
        self.assertEqual(quote_response.get_json()["rate"], "5.42")

        usd_response = self.client.post(
            f"/trips/{trip_id}/expenses/new",
            data={
                "data_gasto": "2026-06-13",
                "descricao": "Almoço em dólares",
                "categoria": "Passeios",
                "valor_original": "100,00",
                "moeda": "USD",
                "cotacao": "5.42",
                "pago": "0",
            },
            follow_redirects=True,
        )
        self.assertIn("Almoço em dólares", usd_response.get_data(as_text=True))
        trip = db_service.storage_manager.get_viagem(trip_id)
        usd_expense = next(expense for expense in trip["gastos"] if expense["descricao"] == "Almoço em dólares")
        self.assertEqual(usd_expense["valor_em_brl"], 542.0)

        trip = db_service.storage_manager.get_viagem(trip_id)
        foreign_expense = next(expense for expense in trip["gastos"] if expense["descricao"] == "Passeio futuro")
        self.assertEqual(foreign_expense["valor_em_brl"], 275.0)
        self.assertFalse(foreign_expense["pago"])

        filtered_response = self.client.get(
            f"/trips/{trip_id}/expenses",
            query_string={
                "categoria": "Passeios",
                "data_inicio": "2026-06-12",
                "data_fim": "2026-06-12",
                "pago": "nao",
                "busca": "futuro",
            },
        )
        filtered_page = filtered_response.get_data(as_text=True)
        self.assertEqual(filtered_response.status_code, 200)
        self.assertIn("Gastos encontrados", filtered_page)
        self.assertIn('aria-label="Tabela de gastos" tabindex="0"', filtered_page)
        self.assertIn("Deslize a tabela para o lado", filtered_page)
        self.assertIn("filtered-total-card filtered-total-spent", filtered_page)
        self.assertIn('class="activity-action-link" href="/trips/', filtered_page)
        self.assertIn('class="activity-action-link activity-action-danger"', filtered_page)
        self.assertIn("Passeio futuro", filtered_page)
        self.assertIn("R$ 275,00", filtered_page)
        self.assertNotIn("Hospedagem</td>", filtered_page)

        paid_response = self.client.get(
            f"/trips/{trip_id}/expenses",
            query_string={"pago": "sim"},
        )
        self.assertIn("Hospedagem", paid_response.get_data(as_text=True))
        self.assertNotIn("Passeio futuro", paid_response.get_data(as_text=True))

        delete_response = self.client.post(
            f"/trips/{trip_id}/expenses/{foreign_expense['id']}/delete",
            data={
                "categoria": "Passeios",
                "data_inicio": "2026-06-12",
                "data_fim": "2026-06-12",
                "pago": "nao",
                "busca": "futuro",
                "pagina": "1",
            },
            follow_redirects=True,
        )
        delete_page = delete_response.get_data(as_text=True)
        self.assertEqual(delete_response.status_code, 200)
        self.assertIn("Todos os gastos", delete_page)
        self.assertIn('name="categoria"', delete_page)
        self.assertIn('value="Passeios"', delete_page)
        self.assertIn('value="futuro"', delete_page)
        self.assertIn("0 resultado(s)", delete_page)
        self.assertNotIn("Passeio futuro", delete_page)

        response = self.client.post(
            f"/trips/{trip_id}/activities/new",
            data={"nome": "Museu", "data": "2026-06-16", "custo_estimado": "50"},
        )
        self.assertIn("deve ocorrer entre", response.get_data(as_text=True))

        response = self.client.post(
            f"/trips/{trip_id}/activities/new",
            data={
                "nome": "Museu",
                "data": "2026-06-15",
                "horario": "10:00",
                "local": "Museu Nacional",
                "custo_estimado": "",
                "observacao": "Reserva às 10h",
                "situacao": "reservada",
            },
            follow_redirects=True,
        )

        response = self.client.post(
            f"/trips/{trip_id}/activities/new",
            data={"nome": "Feira", "data": "2026-06-14", "horario": "09:00", "local": "Centro", "custo_estimado": ""},
            follow_redirects=True,
        )
        page = response.get_data(as_text=True)
        self.assertLess(page.index("Feira"), page.index("Museu"))
        self.assertIn("Atividades", page)
        self.assertIn("Museu", page)
        self.assertIn("Reserva às 10h", page)

        dashboard_page = self.client.get(f"/trips/{trip_id}").get_data(as_text=True)
        self.assertIn("Roteiro completo", dashboard_page)
        self.assertIn(f'href="/trips/{trip_id}/activities"', dashboard_page)
        self.assertIn(f'href="/trips/{trip_id}/expenses/new"', dashboard_page)
        self.assertEqual(dashboard_page.count("Adicionar gasto"), 1)
        self.assertIn('class="metric metric-balance', dashboard_page)
        self.assertLess(dashboard_page.index('class="metric metric-balance'), dashboard_page.index("TOTAL PREVISTO"))
        self.assertIn("GASTO REGISTRADO", dashboard_page)
        self.assertIn("TOTAL PAGO", dashboard_page)
        self.assertIn("A PAGAR", dashboard_page)
        self.assertIn("SALDO DO PLANEJAMENTO", dashboard_page)
        self.assertIn('role="progressbar" aria-label="Orçamento utilizado"', dashboard_page)
        self.assertIn("Orçamento utilizado", dashboard_page)
        self.assertIn("Positivo: restante", dashboard_page)
        self.assertIn("15.0% usado", dashboard_page)
        self.assertIn("Sem previsto", dashboard_page)
        self.assertIn("R$ 180,50", dashboard_page)

        activity_response = self.client.get(
            f"/trips/{trip_id}/activities",
            query_string={"situacao": "reservada", "busca": "Museu Nacional"},
        )
        activity_page = activity_response.get_data(as_text=True)
        self.assertEqual(activity_response.status_code, 200)
        self.assertIn("Museu Nacional", activity_page)
        self.assertIn("Reserva às 10h", activity_page)
        self.assertIn("10:00", activity_page)
        self.assertNotIn(">Detalhes</a>", activity_page)
        self.assertNotIn("Feira", activity_page)
        saved_trip = db_service.storage_manager.get_viagem(trip_id)
        museum = next(activity for activity in saved_trip["atividades"] if activity["nome"] == "Museu")
        detail_response = self.client.get(f"/trips/{trip_id}/activities/{museum['id']}")
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn("Museu Nacional", detail_response.get_data(as_text=True))
        self.assertIn("Reserva às 10h", detail_response.get_data(as_text=True))

        itinerary_response = self.client.get(f"/trips/{trip_id}/activities/print")
        itinerary_page = itinerary_response.get_data(as_text=True)
        self.assertEqual(itinerary_response.status_code, 200)
        self.assertIn("Roteiro de viagem", itinerary_page)
        self.assertIn("Museu Nacional", itinerary_page)
        self.assertIn("Reserva às 10h", itinerary_page)
        self.assertNotIn("Resumo financeiro", itinerary_page)

        report_response = self.client.get(f"/trips/{trip_id}/report")
        self.assertEqual(report_response.status_code, 200)
        self.assertIn("Relatório da viagem", report_response.get_data(as_text=True))
        self.assertIn("Saldo do planejamento", report_response.get_data(as_text=True))
        self.assertIn("A pagar", report_response.get_data(as_text=True))

        db_service.storage_manager.delete_viagem(trip_id)
        self.assertIsNone(db_service.storage_manager.get_viagem(trip_id))

    def test_painel_avisa_ao_se_aproximar_e_ao_ultrapassar_orcamento(self):
        self.client.post(
            "/trips/new",
            data={
                "destino": "Viagem com orçamento",
                "data_ida": "2026-06-10",
                "data_volta": "2026-06-15",
            },
            follow_redirects=True,
        )
        with self.client.session_transaction() as browser_session:
            trip_id = browser_session["selected_trip_id"]

        self.client.post(
            f"/trips/{trip_id}/planning/categories",
            data={"categoria_nova": "Hospedagem"},
            follow_redirects=True,
        )
        self.client.post(
            f"/trips/{trip_id}/planning",
            data={"previsto_0": "1000"},
            follow_redirects=True,
        )

        def add_expense(description, amount):
            return self.client.post(
                f"/trips/{trip_id}/expenses/new",
                data={
                    "data_gasto": "2026-06-11",
                    "descricao": description,
                    "categoria": "Hospedagem",
                    "valor_original": str(amount),
                    "moeda": "BRL",
                    "pago": "0",
                },
                follow_redirects=True,
            )

        add_expense("Reserva do hotel", "800")
        warning_page = self.client.get(f"/trips/{trip_id}").get_data(as_text=True)
        self.assertIn("Atenção: 80.0% do orçamento geral utilizado", warning_page)
        self.assertIn("Atenção · 80.0% utilizado", warning_page)
        self.assertIn("near-budget-limit", warning_page)

        add_expense("Taxa extra do hotel", "250")
        over_budget_page = self.client.get(f"/trips/{trip_id}").get_data(as_text=True)
        self.assertIn("O orçamento geral foi ultrapassado em R$ 50,00", over_budget_page)
        self.assertIn("Excedido em R$ 50,00", over_budget_page)
        self.assertIn("over-budget", over_budget_page)

    def test_crud_reservas_filtros_e_preservacao_no_backup(self):
        self.client.post(
            "/trips/new",
            data={
                "destino": "Lisboa",
                "data_ida": "2026-06-10",
                "data_volta": "2026-06-15",
            },
            follow_redirects=True,
        )
        with self.client.session_transaction() as browser_session:
            trip_id = browser_session["selected_trip_id"]

        response = self.client.post(
            f"/trips/{trip_id}/reservations/new",
            data={
                "tipo": "hospedagem",
                "fornecedor": "Hotel Central",
                "codigo_confirmacao": "ABC123",
                "data_inicio": "2026-06-11",
                "horario_checkin": "15:00",
                "data_fim": "2026-06-14",
                "horario_checkout": "11:30",
                "local": "Centro de Lisboa",
                "prazo_cancelamento": "2026-06-09",
                "situacao": "confirmada",
                "observacao": "Check-in após 15h",
            },
            follow_redirects=True,
        )
        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Hotel Central", page)
        self.assertIn("ABC123", page)
        self.assertIn("Centro de Lisboa", page)
        trip = db_service.storage_manager.get_viagem(trip_id)
        reservation = trip["reservas"][0]
        self.assertEqual(reservation["prazo_cancelamento"], "09/06/2026")
        self.assertEqual(reservation["horario_checkin"], "15:00")
        self.assertEqual(reservation["horario_checkout"], "11:30")

        dashboard = self.client.get(f"/trips/{trip_id}").get_data(as_text=True)
        self.assertIn("Reservas (1)", dashboard)
        self.assertIn("Hotel Central", dashboard)
        self.assertIn("15:00", dashboard)
        self.assertIn("11:30", dashboard)

        filtered = self.client.get(
            f"/trips/{trip_id}/reservations",
            query_string={"tipo": "hospedagem", "situacao": "confirmada", "busca": "ABC123"},
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertIn("Hotel Central", filtered.get_data(as_text=True))

        edit_response = self.client.post(
            f"/trips/{trip_id}/reservations/{reservation['id']}/edit",
            data={
                "tipo": "hospedagem",
                "fornecedor": "Hotel Central atualizado",
                "codigo_confirmacao": "ABC123",
                "data_inicio": "2026-06-11",
                "horario_checkin": "16:15",
                "data_fim": "2026-06-14",
                "horario_checkout": "12:00",
                "situacao": "utilizada",
            },
            follow_redirects=True,
        )
        self.assertIn("Hotel Central atualizado", edit_response.get_data(as_text=True))
        self.assertIn("Utilizada", edit_response.get_data(as_text=True))
        trip = db_service.storage_manager.get_viagem(trip_id)
        self.assertEqual(trip["reservas"][0]["horario_checkin"], "16:15")
        self.assertEqual(trip["reservas"][0]["horario_checkout"], "12:00")

        invalid = self.client.post(
            f"/trips/{trip_id}/reservations/new",
            data={
                "tipo": "transporte",
                "fornecedor": "Trem",
                "data_inicio": "2026-06-14",
                "data_fim": "2026-06-11",
                "situacao": "confirmada",
            },
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertIn("data final da reserva não pode ser anterior", invalid.get_data(as_text=True))

        exported_trip = validate_backup_document(make_trip_export(trip))[0]
        self.assertEqual(exported_trip["reservas"][0]["fornecedor"], "Hotel Central atualizado")
        self.assertEqual(exported_trip["reservas"][0]["situacao"], "utilizada")
        self.assertEqual(exported_trip["reservas"][0]["horario_checkin"], "16:15")
        self.assertEqual(exported_trip["reservas"][0]["horario_checkout"], "12:00")

        invalid_time = self.client.post(
            f"/trips/{trip_id}/reservations/new",
            data={
                "tipo": "hospedagem",
                "fornecedor": "Hospedagem inválida",
                "data_inicio": "2026-06-12",
                "horario_checkin": "25:99",
                "data_fim": "2026-06-13",
                "situacao": "pendente",
            },
        )
        self.assertIn("horário válido para o check-in", invalid_time.get_data(as_text=True))

        removed = self.client.post(
            f"/trips/{trip_id}/reservations/{reservation['id']}/delete",
            follow_redirects=True,
        )
        self.assertIn("Reserva removida", removed.get_data(as_text=True))
        self.assertEqual(db_service.storage_manager.get_viagem(trip_id)["reservas"], [])

    def test_painel_exibe_proxima_atividade_e_estado_vazio(self):
        today = date.today()
        activity_day = today + timedelta(days=1)
        response = self.client.post(
            "/trips/new",
            data={
                "destino": "Viagem com roteiro",
                "data_ida": today.isoformat(),
                "data_volta": (today + timedelta(days=5)).isoformat(),
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as browser_session:
            trip_id = browser_session["selected_trip_id"]

        empty_dashboard = self.client.get(f"/trips/{trip_id}").get_data(as_text=True)
        self.assertIn("Nenhuma atividade planejada nesta viagem.", empty_dashboard)
        self.assertIn("Adicionar primeira atividade", empty_dashboard)

        trip = db_service.storage_manager.get_viagem(trip_id)
        trip["atividades"] = [
            {"id": 1, "nome": "Mais tarde", "data": (activity_day + timedelta(days=1)).strftime("%d/%m/%Y"), "horario": "15:00", "local": "Parque", "situacao": "planejada"},
            {"id": 2, "nome": "Próxima visita", "data": activity_day.strftime("%d/%m/%Y"), "horario": "10:30", "local": "Museu", "situacao": "reservada"},
            {"id": 3, "nome": "Cancelada", "data": activity_day.strftime("%d/%m/%Y"), "horario": "09:00", "situacao": "cancelada"},
            {"id": 4, "nome": "Concluída", "data": activity_day.strftime("%d/%m/%Y"), "horario": "08:00", "situacao": "realizada"},
        ]
        db_service.storage_manager.save_viagem(trip)

        dashboard = self.client.get(f"/trips/{trip_id}").get_data(as_text=True)

        self.assertIn("Próxima visita", dashboard)
        self.assertIn("10:30", dashboard)
        self.assertIn("Museu", dashboard)
        self.assertIn("Reservada", dashboard)
        self.assertNotIn("Mais tarde", dashboard)
        self.assertNotIn("Cancelada", dashboard)
        self.assertNotIn("Concluída", dashboard)
        self.assertIn("Roteiro completo", dashboard)

    def test_find_next_activity_skips_elapsed_and_terminal_statuses(self):
        reference_time = datetime(2026, 10, 23, 12, 0)
        activities = [
            {"nome": "Já passou", "data": "23/10/2026", "horario": "11:00", "situacao": "planejada"},
            {"nome": "Cancelada", "data": "24/10/2026", "horario": "09:00", "situacao": "cancelada"},
            {"nome": "A seguir", "data": "24/10/2026", "horario": "09:00", "situacao": "planejada"},
        ]
        self.assertEqual(find_next_activity(activities, reference_time)["nome"], "A seguir")
        self.assertIsNone(find_next_activity([], reference_time))

    def test_find_next_activity_keeps_uncompleted_activity_from_today_visible(self):
        reference_time = datetime(2026, 10, 23, 12, 0)
        activities = [
            {"nome": "Atividade da manhã", "data": "23/10/2026", "horario": "09:00", "situacao": "planejada"},
            {"nome": "Atividade mais recente", "data": "23/10/2026", "horario": "11:48", "situacao": "reservada"},
            {"nome": "Atividade cancelada", "data": "23/10/2026", "horario": "11:55", "situacao": "cancelada"},
        ]
        self.assertEqual(find_next_activity(activities, reference_time)["nome"], "Atividade mais recente")

    def test_find_next_activity_selects_later_today_before_tomorrow(self):
        reference_time = datetime(2026, 10, 23, 11, 57)
        activities = [
            {"id": 1, "nome": "Atividade da manhã", "data": "23/10/2026", "horario": "11:00", "situacao": "planejada"},
            {"id": 2, "nome": "Atividade da noite", "data": "23/10/2026", "horario": "18:00", "situacao": "planejada"},
            {"id": 3, "nome": "Atividade de amanhã", "data": "24/10/2026", "horario": "10:00", "situacao": "reservada"},
        ]
        self.assertEqual(find_next_activity(activities, reference_time)["nome"], "Atividade da noite")

    def test_find_next_activity_handles_duplicate_schedule_and_name(self):
        reference_time = datetime(2026, 10, 23, 10, 0)
        activities = [
            {"id": 1, "nome": "Passeio", "data": "23/10/2026", "horario": "18:00", "situacao": "planejada"},
            {"id": 2, "nome": "Passeio", "data": "23/10/2026", "horario": "18:00", "situacao": "reservada"},
        ]
        self.assertEqual(find_next_activity(activities, reference_time)["id"], 1)

    def test_find_next_activity_normalizes_legacy_trailing_colon_time(self):
        reference_time = datetime(2026, 10, 23, 12, 0)
        activities = [
            {"id": 1, "nome": "Atividade com horário legado", "data": "23/10/2026", "horario": "18:00:", "situacao": "planejada"},
        ]
        selected = find_next_activity(activities, reference_time)
        self.assertEqual(selected["id"], 1)
        self.assertEqual(selected["horario"], "18:00")
        self.assertEqual(activities[0]["horario"], "18:00:")

    def test_marcar_atividade_realizada_no_painel_e_no_roteiro(self):
        tomorrow = date.today() + timedelta(days=1)
        trip = {
            "destino": "Viagem para concluir atividade",
            "data_ida": date.today().strftime("%d/%m/%Y"),
            "data_volta": (date.today() + timedelta(days=5)).strftime("%d/%m/%Y"),
            "gastos": [],
            "atividades": [
                {
                    "nome": "Atividade do painel",
                    "data": tomorrow.strftime("%d/%m/%Y"),
                    "horario": "10:00",
                    "local": "",
                    "custo_estimado": None,
                    "situacao": "planejada",
                },
                {
                    "nome": "Atividade do roteiro",
                    "data": tomorrow.strftime("%d/%m/%Y"),
                    "horario": "11:00",
                    "local": "",
                    "custo_estimado": None,
                    "situacao": "reservada",
                },
                {
                    "nome": "Atividade cancelada",
                    "data": tomorrow.strftime("%d/%m/%Y"),
                    "horario": "12:00",
                    "local": "",
                    "custo_estimado": None,
                    "situacao": "cancelada",
                },
            ],
            "planejamento": [],
        }
        db_service.storage_manager.save_viagem(trip)
        trip_id = trip["id"]
        activities_by_name = {activity["nome"]: activity for activity in trip["atividades"]}

        dashboard = self.client.get(f"/trips/{trip_id}").get_data(as_text=True)
        self.assertIn("Atividade do painel", dashboard)
        self.assertIn(
            f'action="/trips/{trip_id}/activities/{activities_by_name["Atividade do painel"]["id"]}/status"',
            dashboard,
        )
        self.assertIn('name="origin" value="dashboard"', dashboard)
        self.assertIn('name="action" value="complete"', dashboard)

        completed_response = self.client.post(
            f"/trips/{trip_id}/activities/{activities_by_name['Atividade do painel']['id']}/status",
            data={"origin": "dashboard", "action": "complete"},
        )
        self.assertEqual(completed_response.status_code, 302)
        self.assertEqual(completed_response.headers["Location"], f"/trips/{trip_id}")
        saved_trip = db_service.storage_manager.get_viagem(trip_id)
        self.assertEqual(
            next(activity for activity in saved_trip["atividades"] if activity["nome"] == "Atividade do painel")["situacao"],
            "realizada",
        )
        self.assertIn("Atividade do roteiro", self.client.get(f"/trips/{trip_id}").get_data(as_text=True))

        itinerary = self.client.get(f"/trips/{trip_id}/activities").get_data(as_text=True)
        self.assertIn("Marcar realizada", itinerary)
        self.assertIn('class="activity-action-link activity-complete-button', itinerary)
        self.assertIn('class="activity-action-link activity-action-danger"', itinerary)
        self.assertIn("Reabrir atividade", itinerary)
        self.assertIn("Realizada", itinerary)
        self.assertNotIn(
            f'action="/trips/{trip_id}/activities/{activities_by_name["Atividade cancelada"]["id"]}/status"',
            itinerary,
        )

        completed_from_list = self.client.post(
            f"/trips/{trip_id}/activities/{activities_by_name['Atividade do roteiro']['id']}/status",
            data={"origin": "activities", "action": "complete"},
        )
        self.assertEqual(completed_from_list.status_code, 302)
        self.assertEqual(completed_from_list.headers["Location"], f"/trips/{trip_id}/activities")
        saved_trip = db_service.storage_manager.get_viagem(trip_id)
        self.assertEqual(
            next(activity for activity in saved_trip["atividades"] if activity["nome"] == "Atividade do roteiro")["situacao"],
            "realizada",
        )
        completed_itinerary = self.client.get(f"/trips/{trip_id}/activities").get_data(as_text=True)
        self.assertNotIn("Marcar realizada", completed_itinerary)
        self.assertIn("Reabrir atividade", completed_itinerary)

        reopened_response = self.client.post(
            f"/trips/{trip_id}/activities/{activities_by_name['Atividade do roteiro']['id']}/status",
            data={"origin": "activities", "action": "reopen"},
            follow_redirects=True,
        )
        self.assertIn("Atividade reaberta como planejada.", reopened_response.get_data(as_text=True))
        saved_trip = db_service.storage_manager.get_viagem(trip_id)
        self.assertEqual(
            next(activity for activity in saved_trip["atividades"] if activity["nome"] == "Atividade do roteiro")["situacao"],
            "planejada",
        )

        rejected_cancelled = self.client.post(
            f"/trips/{trip_id}/activities/{activities_by_name['Atividade cancelada']['id']}/status",
            data={"origin": "dashboard", "action": "complete"},
            follow_redirects=True,
        )
        self.assertIn("Atividades canceladas", rejected_cancelled.get_data(as_text=True))
        self.assertEqual(
            next(
                activity for activity in db_service.storage_manager.get_viagem(trip_id)["atividades"]
                if activity["nome"] == "Atividade cancelada"
            )["situacao"],
            "cancelada",
        )

    def test_find_next_activity_tolerates_other_invalid_times(self):
        reference_time = datetime(2026, 10, 23, 12, 0)
        activities = [
            {"id": 1, "nome": "Atividade sem horário válido", "data": "23/10/2026", "horario": "inválido", "situacao": "planejada"},
        ]
        with self.assertLogs("web_app", level="WARNING"):
            selected = find_next_activity(activities, reference_time)
        self.assertEqual(selected["id"], 1)
        self.assertEqual(selected["horario"], "")

    def test_categoria_personalizada_e_protecao_de_remocao(self):
        response = self.client.post(
            "/trips/new",
            data={
                "destino": "Viagem de teste",
                "data_ida": "2026-07-10",
                "data_volta": "2026-07-15",
            },
            follow_redirects=True,
        )
        with self.client.session_transaction() as browser_session:
            trip_id = browser_session["selected_trip_id"]

        response = self.client.post(
            f"/trips/{trip_id}/planning/categories",
            data={"categoria_nova": "Pets"},
            follow_redirects=True,
        )
        self.assertIn("Categoria adicionada", response.get_data(as_text=True))
        response = self.client.post(
            f"/trips/{trip_id}/planning/categories",
            data={"categoria_nova": "Outros"},
            follow_redirects=True,
        )
        self.assertIn("Categoria adicionada", response.get_data(as_text=True))
        expense_form = self.client.get(f"/trips/{trip_id}/expenses/new")
        self.assertIn('value="Pets"', expense_form.get_data(as_text=True))
        trip = db_service.storage_manager.get_viagem(trip_id)
        pets_index = next(index for index, row in enumerate(trip["planejamento"]) if row["categoria"] == "Pets")
        expense_response = self.client.post(
            f"/trips/{trip_id}/expenses/new",
            data={
                "data_gasto": "2026-07-11",
                "categoria": "Pets",
                "descricao": "Ração",
                "moeda": "BRL",
                "valor_original": "75,00",
                "pago": "0",
            },
            follow_redirects=True,
        )
        self.assertIn("Ração", expense_response.get_data(as_text=True))

        response = self.client.post(
            f"/trips/{trip_id}/planning/categories/{pets_index}/delete",
            follow_redirects=True,
        )
        self.assertIn("Não é possível remover", response.get_data(as_text=True))
        self.assertIn("Pets", response.get_data(as_text=True))

        trip = db_service.storage_manager.get_viagem(trip_id)
        unused_index = next(index for index, row in enumerate(trip["planejamento"]) if row["categoria"] == "Outros")
        response = self.client.post(
            f"/trips/{trip_id}/planning/categories/{unused_index}/delete",
            follow_redirects=True,
        )
        self.assertNotIn("Outros", [row["categoria"] for row in db_service.storage_manager.get_viagem(trip_id)["planejamento"]])

        db_service.storage_manager.delete_viagem(trip_id)

    def test_painel_mostra_cinco_gastos_e_lista_pagina(self):
        trip = {
            "destino": "Lista extensa",
            "data_ida": "01/08/2026",
            "data_volta": "31/08/2026",
            "orcamento_total": 0.0,
            "gastos": [
                {
                    "data_gasto": f"{day:02d}/08/2026",
                    "descricao": f"Despesa {day:02d}",
                    "categoria": "Compras",
                    "moeda": "BRL",
                    "valor_original": 10.0,
                    "cotacao": 1.0,
                    "valor_em_brl": 10.0,
                    "forma_pagamento": None,
                    "observacao": "",
                    "pago": False,
                }
                for day in range(1, 31)
            ],
            "atividades": [],
            "planejamento": [{"categoria": "Compras", "valor_previsto": 500.0}],
        }
        db_service.storage_manager.save_viagem(trip)
        trip_id = trip["id"]
        try:
            dashboard_response = self.client.get(f"/trips/{trip_id}")
            dashboard_page = dashboard_response.get_data(as_text=True)
            self.assertEqual(dashboard_response.status_code, 200)
            self.assertIn("Ver todos (30)", dashboard_page)
            self.assertIn("Despesa 30", dashboard_page)
            self.assertIn("Despesa 26", dashboard_page)
            self.assertNotIn("Despesa 25", dashboard_page)

            list_response = self.client.get(f"/trips/{trip_id}/expenses?pagina=2")
            list_page = list_response.get_data(as_text=True)
            self.assertEqual(list_response.status_code, 200)
            self.assertIn("Página 2 de 2", list_page)
            self.assertIn("Despesa 05", list_page)
            self.assertNotIn("Despesa 06", list_page)
        finally:
            db_service.storage_manager.delete_viagem(trip_id)

    def test_backup_export_restore_preserva_original_e_cancela_previa(self):
        trip = {
            "destino": "Backup Teste",
            "data_ida": "10/06/2026",
            "data_volta": "15/06/2026",
            "gastos": [],
            "atividades": [],
            "planejamento": [{"categoria": "Passeios", "valor_previsto": 500}],
        }
        db_service.storage_manager.save_viagem(trip)
        original_id = trip["id"]

        try:
            export_response = self.client.get(f"/trips/{original_id}/backup/export")
            self.assertEqual(export_response.status_code, 200)
            self.assertIn("attachment;", export_response.headers["Content-Disposition"])
            self.assertEqual(parse_backup_archive(export_response.data)[0][0]["destino"], "Backup Teste")

            upload = {"backup_file": (BytesIO(export_response.data), "backup.zip")}
            preview_response = self.client.post(
                "/backups/restore",
                data=upload,
                content_type="multipart/form-data",
            )
            preview_page = preview_response.get_data(as_text=True)
            restore_token = re.search(r'name="restore_token" value="([a-f0-9]{32})"', preview_page).group(1)
            self.assertIn("Backup Teste", preview_page)
            self.assertEqual(len(db_service.storage_manager.list_viagens()), 1)

            cancelled = self.client.post(
                "/backups/restore",
                data={"restore_token": restore_token, "action": "cancel"},
                follow_redirects=True,
            )
            self.assertIn("Restauração cancelada", cancelled.get_data(as_text=True))
            self.assertEqual(len(db_service.storage_manager.list_viagens()), 1)

            preview_response = self.client.post(
                "/backups/restore",
                data={"backup_file": (BytesIO(export_response.data), "backup.zip")},
                content_type="multipart/form-data",
            )
            preview_page = preview_response.get_data(as_text=True)
            restore_token = re.search(r'name="restore_token" value="([a-f0-9]{32})"', preview_page).group(1)
            restored = self.client.post(
                "/backups/restore",
                data={"restore_token": restore_token, "action": "confirm"},
                follow_redirects=True,
            )
            self.assertEqual(restored.status_code, 200)
            matching = [item for item in db_service.storage_manager.list_viagens() if item["destino"] == "Backup Teste"]
            self.assertEqual(len(matching), 2)
            self.assertEqual(len({item["id"] for item in matching}), 2)
            self.assertIn("restaurada(s) como cópia(s)", restored.get_data(as_text=True))
        finally:
            for item in db_service.storage_manager.list_viagens():
                if item.get("destino") == "Backup Teste":
                    db_service.storage_manager.delete_viagem(item["id"])

    def test_pagamento_parcial_por_duas_pessoas_e_protecao_de_exclusao(self):
        response = self.client.post(
            "/trips/new",
            data={"destino": "Viagem compartilhada", "data_ida": "2026-06-10", "data_volta": "2026-06-15"},
            follow_redirects=True,
        )
        with self.client.session_transaction() as browser_session:
            trip_id = browser_session["selected_trip_id"]
        self.client.post(f"/trips/{trip_id}/planning/categories", data={"categoria_nova": "Passeios"})
        self.client.post(f"/trips/{trip_id}/people", data={"nome": "Ana"})
        self.client.post(f"/trips/{trip_id}/people", data={"nome": "Bia"})
        people = db_service.storage_manager.get_viagem(trip_id)["pessoas"]

        response = self.client.post(
            f"/trips/{trip_id}/expenses/new",
            data={
                "data_gasto": "2026-06-12",
                "descricao": "Hospedagem compartilhada",
                "categoria": "Passeios",
                "moeda": "BRL",
                "valor_original": "500,00",
                "pago": "0",
                "pagador_id": [str(people[0]["id"]), str(people[1]["id"])],
                "valor_pago": ["150,00", "100,00"],
                "forma_pagamento_pagador": ["Pix", "Cartão"],
            },
            follow_redirects=True,
        )
        trip = db_service.storage_manager.get_viagem(trip_id)
        expense = next(item for item in trip["gastos"] if item["descricao"] == "Hospedagem compartilhada")
        totals = main.calcular_totais(trip)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(expense["pago"])
        self.assertEqual(len(expense["pagamentos"]), 2)
        self.assertEqual(totals["total_pago"], 250.0)
        self.assertEqual(totals["total_em_aberto"], 250.0)

        invalid_response = self.client.post(
            f"/trips/{trip_id}/expenses/new",
            data={
                "data_gasto": "2026-06-13",
                "descricao": "Excesso de pagamento",
                "categoria": "Passeios",
                "moeda": "BRL",
                "valor_original": "100,00",
                "pago": "0",
                "pagador_id": [str(people[0]["id"]), str(people[1]["id"])],
                "valor_pago": ["80,00", "50,00"],
                "forma_pagamento_pagador": ["Pix", "Cartão"],
            },
        )
        invalid_page = invalid_response.get_data(as_text=True)
        self.assertIn("não pode ultrapassar", invalid_page)
        self.assertIn('value="80,00"', invalid_page)
        self.assertIn('value="50,00"', invalid_page)

        delete_response = self.client.post(
            f"/trips/{trip_id}/people/{people[0]['id']}/delete",
            follow_redirects=True,
        )
        self.assertIn("associada a pagamentos", delete_response.get_data(as_text=True))
        self.assertEqual(len(db_service.storage_manager.get_viagem(trip_id)["pessoas"]), 2)
        db_service.storage_manager.delete_viagem(trip_id)

    def test_bandeira_manual_e_upload_de_capa(self):
        response = self.client.post(
            "/trips/new",
            data={
                "destino": "Rio de Janeiro",
                "bandeira": "BR",
                "data_ida": "2026-06-10",
                "data_volta": "2026-06-15",
            },
            follow_redirects=True,
        )
        with self.client.session_transaction() as browser_session:
            trip_id = browser_session["selected_trip_id"]
        html = response.get_data(as_text=True)
        self.assertIn('class="trip-nav-flag" src="/static/flags/br.svg"', html)
        self.assertIn("Rio de Janeiro", html)
        self.assertIn('class="trip-actions-menu"', html)
        self.assertIn('data-cover-upload', html)
        self.assertIn("data-cover-preview", html)
        self.assertIn('id="cover-preview-status" role="status" aria-live="polite"', html)
        self.assertIn('class="cover-control cover-save" type="submit" hidden', html)
        cover_start = html.index('<section class="trip-cover"')
        cover_end = html.index("</section>", cover_start)
        self.assertNotIn("Excluir viagem", html[cover_start:cover_end])
        self.assertIn("Excluir viagem", html[:cover_start])
        image_data = bytes.fromhex("89504e470d0a1a0a") + b"capa de teste"
        try:
            cover_response = self.client.post(
                f"/trips/{trip_id}/cover",
                data={"capa": (BytesIO(image_data), "rio.png")},
                content_type="multipart/form-data",
                follow_redirects=True,
            )
            self.assertEqual(cover_response.status_code, 200)
            trip = db_service.storage_manager.get_viagem(trip_id)
            covers = [attachment for attachment in trip["anexos"] if attachment.get("is_capa")]
            self.assertEqual(len(covers), 1)
            self.assertEqual(trip["bandeira"], "BR")
            image_response = self.client.get(
                f"/trips/{trip_id}/cover/{covers[0]['id']}"
            )
            self.assertEqual(image_response.status_code, 200)
            self.assertEqual(image_response.data, image_data)
            image_response.close()

            export_response = self.client.get(f"/trips/{trip_id}/backup/export")
            exported_trips, archive_files = parse_backup_archive(export_response.data)
            exported_cover = next(item for item in exported_trips[0]["anexos"] if item["is_capa"])
            self.assertEqual(exported_trips[0]["bandeira"], "BR")
            self.assertEqual(archive_files[exported_cover["archive_path"]], image_data)
            preview_response = self.client.post(
                "/backups/restore",
                data={"backup_file": (BytesIO(export_response.data), "rio.zip")},
                content_type="multipart/form-data",
            )
            token = re.search(
                r'name="restore_token" value="([a-f0-9]{32})"',
                preview_response.get_data(as_text=True),
            ).group(1)
            self.client.post(
                "/backups/restore",
                data={"restore_token": token, "action": "confirm"},
                follow_redirects=True,
            )
            restored_trip = next(
                candidate for candidate in db_service.storage_manager.list_viagens()
                if candidate["id"] != trip_id and candidate["destino"] == "Rio de Janeiro"
            )
            restored_cover = next(item for item in restored_trip["anexos"] if item["is_capa"])
            self.assertEqual(restored_trip["bandeira"], "BR")
            self.assertEqual(attachment_service.read_attachment(restored_cover["nome_armazenado"]), image_data)
        finally:
            for candidate in db_service.storage_manager.list_viagens():
                if candidate.get("destino") == "Rio de Janeiro":
                    for attachment in candidate.get("anexos", []):
                        attachment_service.delete_attachment(attachment["nome_armazenado"])
                    db_service.storage_manager.delete_viagem(candidate["id"])

    def test_exibe_bandeira_svg_para_viagem_legada_com_codigo_iso(self):
        db_service.storage_manager.save_viagem({
            "destino": "Lisboa",
            "bandeira": "🇧🇷",
            "data_ida": "23/10/2026",
            "data_volta": "25/10/2026",
            "gastos": [],
            "atividades": [],
            "planejamento": [],
        })
        trip = db_service.storage_manager.list_viagens()[0]

        response = self.client.get(f"/trips/{trip['id']}")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('class="trip-nav-flag" src="/static/flags/br.svg"', html)
        self.assertIn('class="trip-cover-flag" src="/static/flags/br.svg"', html)
        self.assertIn("Lisboa, Brasil", html)
        self.assertEqual(trip["bandeira"], "BR")
        flag_response = self.client.get("/static/flags/br.svg")
        self.assertEqual(flag_response.status_code, 200)
        self.assertIn(b"<svg", flag_response.data)
        flag_response.close()

        report_html = self.client.get(f"/trips/{trip['id']}/report").get_data(as_text=True)
        self.assertIn('class="report-trip-flag" src="/static/flags/br.svg"', report_html)
        self.assertIn("Lisboa, Brasil", report_html)
        itinerary_html = self.client.get(f"/trips/{trip['id']}/activities/print").get_data(as_text=True)
        self.assertIn('class="itinerary-country-flag" src="/static/flags/br.svg"', itinerary_html)
        self.assertIn("Lisboa, Brasil", itinerary_html)
    def test_formulario_permite_buscar_e_selecionar_pais(self):
        form_html = self.client.get("/trips/new").get_data(as_text=True)
        self.assertIn('data-country-picker', form_html)
        self.assertIn('id="country-list"', form_html)
        self.assertIn('Pesquisar país...', form_html)
        self.assertIn('country-picker.js', form_html)

        response = self.client.post(
            "/trips/new",
            data={
                "destino": "Islândia",
                "bandeira": "IS",
                "data_ida": "2026-06-10",
                "data_volta": "2026-06-15",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('src="/static/flags/is.svg"', response.get_data(as_text=True))

    def test_rejeita_codigo_de_pais_inexistente(self):
        response = self.client.post(
            "/trips/new",
            data={
                "destino": "Destino inválido",
                "bandeira": "ZZ",
                "data_ida": "2026-06-10",
                "data_volta": "2026-06-15",
            },
            follow_redirects=True,
        )

        self.assertIn("Selecione um país válido da lista.", response.get_data(as_text=True))

    def test_exporta_e_restaurar_cria_copia_sem_substituir_original(self):
        original = {
            "destino": "Lisboa",
            "data_ida": "10/06/2026",
            "data_volta": "15/06/2026",
            "gastos": [],
            "atividades": [],
            "planejamento": [{"categoria": "Passeios", "valor_previsto": 400.0}],
        }
        db_service.storage_manager.save_viagem(original)
        original_id = original["id"]

        try:
            export_response = self.client.get(f"/trips/{original_id}/backup/export")
            self.assertEqual(export_response.status_code, 200)
            self.assertIn("attachment;", export_response.headers["Content-Disposition"])
            exported_trips, _ = parse_backup_archive(export_response.data)
            self.assertEqual(exported_trips[0]["destino"], "Lisboa")

            preview_response = self.client.post(
                "/backups/restore",
                data={"backup_file": (BytesIO(export_response.data), "lisboa.zip")},
                content_type="multipart/form-data",
            )
            preview_page = preview_response.get_data(as_text=True)
            self.assertEqual(preview_response.status_code, 200)
            self.assertIn("Viagens encontradas", preview_page)
            self.assertIn("As originais não serão substituídas", preview_page)
            token_match = re.search(r'name="restore_token" value="([a-f0-9]{32})"', preview_page)
            self.assertIsNotNone(token_match)

            restored_response = self.client.post(
                "/backups/restore",
                data={"restore_token": token_match.group(1), "action": "confirm"},
                follow_redirects=True,
            )
            self.assertEqual(restored_response.status_code, 200)
            self.assertIn("restaurada(s) como cópia(s)", restored_response.get_data(as_text=True))
            matches = [trip for trip in db_service.storage_manager.list_viagens() if trip["destino"] == "Lisboa"]
            self.assertEqual(len(matches), 2)
            self.assertEqual(len({trip["id"] for trip in matches}), 2)
        finally:
            for trip in db_service.storage_manager.list_viagens():
                if trip.get("destino") == "Lisboa":
                    db_service.storage_manager.delete_viagem(trip["id"])

    def test_zip_preserva_anexo_e_reassocia_ao_gasto_restaurado(self):
        trip = {
            "destino": "Anexo ZIP teste",
            "data_ida": "10/06/2026",
            "data_volta": "15/06/2026",
            "gastos": [],
            "atividades": [],
            "planejamento": [{"categoria": "Passeios", "valor_previsto": 200.0}],
            "pessoas": [],
            "anexos": [],
        }
        db_service.storage_manager.save_viagem(trip)
        original_id = trip["id"]
        attachment_bytes = b"%PDF-1.7\nrecibo de teste"
        upload_response = self.client.post(
            f"/trips/{original_id}/expenses/new",
            data={
                "data_gasto": "2026-06-12",
                "descricao": "Museu",
                "categoria": "Passeios",
                "moeda": "BRL",
                "valor_original": "50,00",
                "pago": "0",
                "observacao": "",
                "anexos": (BytesIO(attachment_bytes), "recibo.pdf"),
            },
            follow_redirects=True,
        )
        self.assertEqual(upload_response.status_code, 200)
        trip = db_service.storage_manager.get_viagem(original_id)
        attachment = trip["anexos"][0]
        expense_id = trip["gastos"][0]["id"]
        self.assertEqual(attachment["gasto_id"], expense_id)

        activity_bytes = b"\x89PNG\r\n\x1a\n ingresso"
        activity_response = self.client.post(
            f"/trips/{original_id}/activities/new",
            data={
                "nome": "Museu",
                "data": "2026-06-13",
                "horario": "10:00",
                "situacao": "reservada",
                "local": "Museu Nacional",
                "custo_estimado": "",
                "observacao": "",
                "anexos": (BytesIO(activity_bytes), "ingresso.png"),
            },
            follow_redirects=True,
        )
        self.assertEqual(activity_response.status_code, 200)
        trip = db_service.storage_manager.get_viagem(original_id)
        activity = trip["atividades"][0]
        activity_attachment = next(item for item in trip["anexos"] if item.get("atividade_id") == activity["id"])

        try:
            download_response = self.client.get(
                f"/trips/{original_id}/attachments/{attachment['id']}"
            )
            self.assertEqual(download_response.data, attachment_bytes)
            download_response.close()
            export_response = self.client.get(f"/trips/{original_id}/backup/export")
            self.assertEqual(export_response.status_code, 200)
            exported_trips, exported_files = parse_backup_archive(export_response.data)
            self.assertEqual(len(exported_trips[0]["anexos"]), 2)
            self.assertIn(attachment_bytes, exported_files.values())
            self.assertIn(activity_bytes, exported_files.values())

            preview_response = self.client.post(
                "/backups/restore",
                data={"backup_file": (BytesIO(export_response.data), "trip-backup.zip")},
                content_type="multipart/form-data",
            )
            preview_page = preview_response.get_data(as_text=True)
            token = re.search(r'name="restore_token" value="([a-f0-9]{32})"', preview_page).group(1)
            restored_response = self.client.post(
                "/backups/restore",
                data={"restore_token": token, "action": "confirm"},
                follow_redirects=True,
            )
            matching = [item for item in db_service.storage_manager.list_viagens() if item["destino"] == "Anexo ZIP teste"]
            self.assertEqual(restored_response.status_code, 200)
            self.assertEqual(len(matching), 2)
            restored = next(item for item in matching if item["id"] != original_id)
            restored_attachment = restored["anexos"][0]
            restored_expense_attachment = next(item for item in restored["anexos"] if item.get("gasto_id"))
            restored_activity_attachment = next(item for item in restored["anexos"] if item.get("atividade_id"))
            self.assertEqual(restored_expense_attachment["gasto_id"], restored["gastos"][0]["id"])
            self.assertEqual(restored_activity_attachment["atividade_id"], restored["atividades"][0]["id"])
            self.assertNotEqual(restored_attachment["nome_armazenado"], attachment["nome_armazenado"])
            self.assertEqual(attachment_service.read_attachment(restored_expense_attachment["nome_armazenado"]), attachment_bytes)
            self.assertEqual(attachment_service.read_attachment(restored_activity_attachment["nome_armazenado"]), activity_bytes)
        finally:
            for item in db_service.storage_manager.list_viagens():
                if item.get("destino") == "Anexo ZIP teste":
                    for attachment in item.get("anexos", []):
                        attachment_service.delete_attachment(attachment["nome_armazenado"])
                    db_service.storage_manager.delete_viagem(item["id"])


if __name__ == "__main__":
    unittest.main()