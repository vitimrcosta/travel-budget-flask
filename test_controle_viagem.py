import io
import json
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import backup_service
import db_service
import main


class ControleViagemTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.data_file = Path(self.temp_dir.name) / "viagem_data.json"
        self.original_data_file = db_service.DATA_FILE
        self.original_backup_dir = backup_service.BACKUP_DIR
        self.original_mysql_enabled = main.storage_manager.mysql_enabled
        db_service.DATA_FILE = self.data_file
        backup_service.BACKUP_DIR = Path(self.temp_dir.name) / "backups"
        main.storage_manager.mysql_enabled = False
        main.selected_trip_id = None

    def tearDown(self):
        db_service.DATA_FILE = self.original_data_file
        backup_service.BACKUP_DIR = self.original_backup_dir
        main.storage_manager.mysql_enabled = self.original_mysql_enabled
        main.selected_trip_id = None
        self.temp_dir.cleanup()

    def test_fluxo_completo_da_viagem(self):
        entradas_viagem = [
            "Rio de Janeiro",
            "10/05/2026",
            "15/05/2026",
        ]
        entradas_gasto = [
            "11/05/2026",
            "Hospedagem",
            "Hotel",
            "BRL",
            "200",
            "s",
            "Pix",
            "Pago na hora",
        ]
        entradas_atividade = [
            "Passeio no Cristo",
            "12/05/2026",
            "",
        ]

        with patch("builtins.input", side_effect=entradas_viagem):
            main.cadastrar_viagem()
        viagem = main.obter_viagem_atual()
        viagem["planejamento"] = [{"categoria": "Hospedagem", "valor_previsto": 250.0}]
        main.salvar_viagem(viagem)

        with patch("builtins.input", side_effect=entradas_gasto):
            main.adicionar_gasto()
        with patch("builtins.input", side_effect=entradas_atividade):
            main.adicionar_atividade()

        viagem = main.obter_viagem_atual()
        self.assertEqual(viagem["destino"], "Rio de Janeiro")
        self.assertEqual(len(viagem["gastos"]), 1)
        self.assertEqual(len(viagem["atividades"]), 1)

        resumo = main.calcular_totais(viagem)
        self.assertEqual(resumo["total_previsto"], 250.0)
        self.assertEqual(resumo["total_gasto"], 200.0)
        self.assertEqual(resumo["total_pago"], 200.0)
        self.assertEqual(resumo["total_faltante"], 50.0)

        with patch("sys.stdout", new_callable=io.StringIO) as saida:
            main.gerar_relatorio()

        texto = saida.getvalue()
        self.assertIn("Rio de Janeiro", texto)
        self.assertIn("Total previsto: R$ 250.00", texto)
        self.assertIn("Gasto registrado: R$ 200.00", texto)
        self.assertIn("Total pago: R$ 200.00", texto)
        self.assertIn("Saldo do planejamento: R$ 50.00", texto)

    def test_cadastro_gasto_usd_usa_cotacao_historica(self):
        with patch("builtins.input", side_effect=["Lisboa", "10/06/2026", "15/06/2026", "800"]):
            main.cadastrar_viagem()
        viagem = main.obter_viagem_atual()
        viagem["planejamento"] = [{"categoria": "Passeios", "valor_previsto": 1000.0}]
        main.salvar_viagem(viagem)

        with patch(
            "main.get_historical_rate",
            return_value={"currency": "USD", "rate": Decimal("5.42"), "date": "2026-06-12"},
        ) as mocked_rate, patch(
            "builtins.input",
            side_effect=["12/06/2026", "Passeios", "Almoço", "USD", "100", "n", "", ""],
        ):
            main.adicionar_gasto()

        expense = main.obter_viagem_atual()["gastos"][0]
        self.assertEqual(expense["moeda"], "USD")
        self.assertEqual(expense["cotacao"], 5.42)
        self.assertEqual(expense["valor_em_brl"], 542.0)
        mocked_rate.assert_called_once_with("USD", date(2026, 6, 12))

    def test_calcular_totais_considera_pagamentos_parciais_e_legados(self):
        totals = main.calcular_totais({
            "planejamento": [{"categoria": "Hospedagem", "valor_previsto": 600.0}],
            "gastos": [
                {
                    "categoria": "Hospedagem",
                    "moeda": "USD",
                    "valor_original": 100.0,
                    "cotacao": 5.0,
                    "pago": False,
                    "pagamentos": [{"valor_brl": 200.0}, {"valor_brl": 50.0}],
                },
                {"categoria": "Hospedagem", "moeda": "BRL", "valor_original": 50.0, "pago": True},
                {"categoria": "Hospedagem", "moeda": "BRL", "valor_original": 20.0, "pago": False},
            ],
            "atividades": [],
        })

        self.assertEqual(totals["total_gasto"], 570.0)
        self.assertEqual(totals["total_pago"], 300.0)
        self.assertEqual(totals["total_em_aberto"], 270.0)
        self.assertEqual(totals["alerta_orcamento"], "atencao")
        self.assertEqual(totals["categorias"][0]["alerta_orcamento"], "atencao")

    def test_alertas_de_orcamento_usam_80_porcento_e_diferenciam_excesso(self):
        totals = main.calcular_totais({
            "planejamento": [
                {"categoria": "Hospedagem", "valor_previsto": 100.0},
                {"categoria": "Passeios", "valor_previsto": 100.0},
            ],
            "gastos": [
                {"categoria": "Hospedagem", "moeda": "BRL", "valor_original": 80.0},
                {"categoria": "Passeios", "moeda": "BRL", "valor_original": 101.0},
            ],
            "atividades": [],
        })

        self.assertEqual(totals["categorias"][0]["alerta_orcamento"], "atencao")
        self.assertEqual(totals["categorias"][1]["alerta_orcamento"], "excedido")
        self.assertEqual(totals["alerta_orcamento"], "atencao")

        self.assertIsNone(main.nivel_alerta_orcamento(79.9))
        self.assertEqual(main.nivel_alerta_orcamento(80.0), "atencao")
        self.assertEqual(main.nivel_alerta_orcamento(100.0), "atencao")
        self.assertEqual(main.nivel_alerta_orcamento(100.1), "excedido")
        self.assertIsNone(main.nivel_alerta_orcamento(None))

    def test_destino_e_datas_sao_obrigatorios(self):
        entradas_viagem = [
            "",
            "Rio de Janeiro",
            "",
            "10/05/2026",
            "",
            "15/05/2026",
            "500",
        ]

        with patch("builtins.input", side_effect=entradas_viagem):
            main.cadastrar_viagem()

        viagem = main.obter_viagem_atual()
        self.assertEqual(viagem["destino"], "Rio de Janeiro")
        self.assertEqual(viagem["data_ida"], "10/05/2026")
        self.assertEqual(viagem["data_volta"], "15/05/2026")

    def test_voltar_no_custo_cancela_atividade_sem_salvar(self):
        with patch("builtins.input", side_effect=["Lisboa", "10/06/2026", "15/06/2026", "800"]):
            main.cadastrar_viagem()

        with patch("builtins.input", side_effect=["Museu", "12/06/2026", "voltar"]):
            main.adicionar_atividade()

        self.assertEqual(main.obter_viagem_atual()["atividades"], [])

    def test_data_da_atividade_deve_ficar_no_periodo_da_viagem(self):
        with patch("builtins.input", side_effect=["Lisboa", "10/06/2026", "15/06/2026", "800"]):
            main.cadastrar_viagem()

        with patch("builtins.input", side_effect=["Museu", "09/06/2026", "15/06/2026", "50"]):
            main.adicionar_atividade()

        atividades = main.obter_viagem_atual()["atividades"]
        self.assertEqual(len(atividades), 1)
        self.assertEqual(atividades[0]["data"], "15/06/2026")

    def test_editar_viagem_preserva_campos_vazios_e_rejeita_periodo_invalido(self):
        with patch("builtins.input", side_effect=["Lisboa", "10/06/2026", "15/06/2026", "800"]):
            main.cadastrar_viagem()
        with patch("builtins.input", side_effect=["Museu", "12/06/2026", "50"]):
            main.adicionar_atividade()

        with patch("builtins.input", side_effect=["", "", "11/06/2026", "1000"]):
            main.editar_dados_viagem()
        viagem = main.obter_viagem_atual()
        self.assertEqual(viagem["data_volta"], "15/06/2026")

        with patch("builtins.input", side_effect=["Lisboa atualizada", "", "", "1000"]):
            main.editar_dados_viagem()
        viagem = main.obter_viagem_atual()
        self.assertEqual(viagem["destino"], "Lisboa atualizada")
        self.assertEqual(viagem["data_ida"], "10/06/2026")
        self.assertEqual(viagem["data_volta"], "15/06/2026")

    def test_cadastro_oculto_enquanto_viagem_selecionada(self):
        with patch("builtins.input", side_effect=["Lisboa", "10/06/2026", "15/06/2026", "800"]):
            main.cadastrar_viagem()
        total_viagens = len(main.storage_manager.list_viagens())

        with patch("sys.stdout", new_callable=io.StringIO) as saida:
            main.exibir_menu()
        self.assertNotIn("1. Cadastrar viagem", saida.getvalue())
        self.assertIn("9. Desselecionar viagem", saida.getvalue())

        with patch("builtins.input") as entrada, patch("sys.stdout", new_callable=io.StringIO):
            main.cadastrar_viagem()
        entrada.assert_not_called()
        self.assertEqual(len(main.storage_manager.list_viagens()), total_viagens)

        main.desselecionar_viagem()
        with patch("sys.stdout", new_callable=io.StringIO) as saida:
            main.exibir_menu()
        self.assertIn("1. Cadastrar viagem", saida.getvalue())

    def test_multiplas_viagens_edicao_e_exclusao_de_gasto(self):
        with patch("builtins.input", side_effect=["Lisboa", "10/06/2026", "15/06/2026", "800"]):
            main.cadastrar_viagem()
        primeira = main.obter_viagem_atual()
        primeira["planejamento"] = [
            {"categoria": "Hospedagem", "valor_previsto": 800.0},
            {"categoria": "Transporte", "valor_previsto": 200.0},
        ]
        main.salvar_viagem(primeira)

        with patch("builtins.input", side_effect=["10/06/2026", "Hospedagem", "Hotel", "BRL", "200", "s", "Pix", "Pago"]):
            main.adicionar_gasto()
        with patch("builtins.input", side_effect=["11/06/2026", "Transporte", "Táxi", "BRL", "50", "n", "", "Pendente"]):
            main.adicionar_gasto()

        main.desselecionar_viagem()
        with patch("builtins.input", side_effect=["Roma", "01/07/2026", "05/07/2026", "1200"]):
            main.cadastrar_viagem()
        segunda = main.obter_viagem_atual()

        self.assertNotEqual(primeira["id"], segunda["id"])
        self.assertEqual(len(main.storage_manager.list_viagens()), 2)

        viagem_primeira = main.storage_manager.get_viagem(primeira["id"])
        gasto_id = viagem_primeira["gastos"][0]["id"]
        main.selected_trip_id = primeira["id"]
        with patch("builtins.input", side_effect=["1", "12/06/2026", "Hospedagem", "Hotel editado", "BRL", "220", "s", "Cartão", "Editado"]):
            main.editar_gasto()
        gasto_editado = main.storage_manager.get_viagem(primeira["id"])["gastos"][0]
        self.assertEqual(gasto_editado["descricao"], "Hotel editado")
        self.assertEqual(gasto_editado["valor_original"], 220.0)
        self.assertTrue(gasto_editado["pago"])
        self.assertEqual(
            gasto_editado["id"],
            gasto_id,
        )

        with patch("builtins.input", side_effect=["1", "s"]):
            main.remover_item("gastos", "GASTOS DA VIAGEM", lambda gasto: gasto["descricao"])

        gastos_restantes = main.storage_manager.get_viagem(primeira["id"])["gastos"]
        self.assertEqual(len(gastos_restantes), 1)
        self.assertEqual(gastos_restantes[0]["descricao"], "Táxi")
        self.assertEqual(main.storage_manager.get_viagem(segunda["id"])["destino"], "Roma")

        with patch("builtins.input", side_effect=["13/06/2026", "Transporte", "Estacionamento", "BRL", "30", "n", "", ""]):
            main.adicionar_gasto()
        novo_gasto = main.storage_manager.get_viagem(primeira["id"])["gastos"][-1]
        self.assertNotEqual(novo_gasto["id"], gastos_restantes[0]["id"])


if __name__ == "__main__":
    unittest.main()
