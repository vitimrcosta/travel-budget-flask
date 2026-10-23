import json
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from db_config import DB_CONFIG
import attachment_service
import backup_service
from trip_flags import normalize_country_code

DATA_FILE = Path(__file__).with_name("viagem_data.json")


class StorageManager:
    def __init__(self):
        self.mysql_error = None
        self.backup_error = None
        self._backup_suspended = False
        self.conn = None
        self.mysql_enabled = False

        try:
            import mysql.connector

            self.conn = mysql.connector.connect(**DB_CONFIG)
            self.mysql_enabled = True
            self._create_tables()
        except Exception as exc:  # pragma: no cover - depende do ambiente local
            self.mysql_error = exc
            self.mysql_enabled = False
            self.conn = None
        self._ensure_daily_backup()

    def _ensure_daily_backup(self):
        if self._backup_suspended:
            return
        try:
            backup_service.write_daily_backup(self.list_viagens())
            self.backup_error = None
        except Exception as exc:  # pragma: no cover - depende do ambiente local
            self.backup_error = exc

    def _create_tables(self):
        if not self.conn:
            return

        cursor = self.conn.cursor()
        cursor.execute("CREATE DATABASE IF NOT EXISTS controle_viagem CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cursor.execute("USE controle_viagem")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS viagem (
                id INT NOT NULL AUTO_INCREMENT,
                destino VARCHAR(150) NOT NULL,
                bandeira VARCHAR(12) NULL,
                data_ida DATE NOT NULL,
                data_volta DATE NOT NULL,
                criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute("SHOW COLUMNS FROM viagem LIKE 'bandeira'")
        if cursor.fetchone() is None:
            cursor.execute("ALTER TABLE viagem ADD COLUMN bandeira VARCHAR(12) NULL AFTER destino")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS gasto (
                id INT NOT NULL AUTO_INCREMENT,
                viagem_id INT NOT NULL,
                data_gasto DATE NOT NULL,
                descricao VARCHAR(255) NOT NULL,
                categoria VARCHAR(100) NOT NULL,
                moeda VARCHAR(3) NOT NULL DEFAULT 'BRL',
                valor_original DECIMAL(14,2) NOT NULL,
                cotacao DECIMAL(18,8) NOT NULL DEFAULT 1.00000000,
                forma_pagamento VARCHAR(30) NULL,
                observacao TEXT NULL,
                pago BOOLEAN NOT NULL DEFAULT FALSE,
                PRIMARY KEY (id),
                KEY idx_viagem_id (viagem_id),
                KEY idx_gasto_categoria (viagem_id, categoria),
                CONSTRAINT chk_gasto_cotacao
                    CHECK ((moeda = 'BRL' AND cotacao = 1.00000000) OR (moeda <> 'BRL' AND cotacao > 0)),
                CONSTRAINT fk_gasto_viagem
                    FOREIGN KEY (viagem_id) REFERENCES viagem(id)
                    ON DELETE CASCADE
                    ON UPDATE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute("SHOW COLUMNS FROM gasto LIKE 'moeda'")
        currency_column = cursor.fetchone()
        currency_is_enum = currency_column and currency_column[1].lower().startswith("enum(")
        cursor.execute(
            """
            SELECT CHECK_CLAUSE
            FROM information_schema.CHECK_CONSTRAINTS
            WHERE CONSTRAINT_SCHEMA = DATABASE()
              AND CONSTRAINT_NAME = 'chk_gasto_cotacao'
            """
        )
        check_row = cursor.fetchone()
        check_clause = (check_row[0] or "").lower() if check_row else ""
        check_needs_update = not check_row or (
            "clp" in check_clause and "usd" not in check_clause and "eur" not in check_clause
        )
        if currency_is_enum or check_needs_update:
            if check_row:
                cursor.execute("ALTER TABLE gasto DROP CONSTRAINT chk_gasto_cotacao")
            if currency_is_enum:
                cursor.execute("ALTER TABLE gasto MODIFY COLUMN moeda VARCHAR(3) NOT NULL DEFAULT 'BRL'")
            cursor.execute(
                """
                ALTER TABLE gasto
                    ADD CONSTRAINT chk_gasto_cotacao
                    CHECK ((moeda = 'BRL' AND cotacao = 1.00000000) OR (moeda <> 'BRL' AND cotacao > 0))
                """
            )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS planejamento_categoria (
                id INT NOT NULL AUTO_INCREMENT,
                viagem_id INT NOT NULL,
                categoria VARCHAR(100) NOT NULL,
                valor_previsto DECIMAL(14,2) NOT NULL DEFAULT 0.00,
                PRIMARY KEY (id),
                UNIQUE KEY uq_planejamento_viagem_categoria (viagem_id, categoria),
                CONSTRAINT fk_planejamento_viagem
                    FOREIGN KEY (viagem_id) REFERENCES viagem(id)
                    ON DELETE CASCADE
                    ON UPDATE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS atividade (
                id INT NOT NULL AUTO_INCREMENT,
                viagem_id INT NOT NULL,
                nome VARCHAR(150) NOT NULL,
                data_atividade DATE NOT NULL,
                horario TIME NULL,
                local VARCHAR(255) NULL,
                custo_estimado DECIMAL(10,2) NULL DEFAULT NULL,
                observacao TEXT NULL,
                situacao VARCHAR(20) NOT NULL DEFAULT 'planejada',
                PRIMARY KEY (id),
                KEY idx_viagem_id (viagem_id),
                CONSTRAINT fk_atividade_viagem
                    FOREIGN KEY (viagem_id) REFERENCES viagem(id)
                    ON DELETE CASCADE
                    ON UPDATE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS reserva (
                id INT NOT NULL AUTO_INCREMENT,
                viagem_id INT NOT NULL,
                tipo VARCHAR(30) NOT NULL,
                fornecedor VARCHAR(150) NOT NULL,
                codigo_confirmacao VARCHAR(150) NULL,
                data_inicio DATE NOT NULL,
                horario_checkin TIME NULL,
                data_fim DATE NOT NULL,
                horario_checkout TIME NULL,
                local VARCHAR(255) NULL,
                prazo_cancelamento DATE NULL,
                situacao VARCHAR(20) NOT NULL DEFAULT 'pendente',
                observacao TEXT NULL,
                PRIMARY KEY (id),
                KEY idx_reserva_viagem_data (viagem_id, data_inicio),
                CONSTRAINT fk_reserva_viagem FOREIGN KEY (viagem_id) REFERENCES viagem(id)
                    ON DELETE CASCADE ON UPDATE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        for column, definition in (
            ("horario_checkin", "TIME NULL AFTER data_inicio"),
            ("horario_checkout", "TIME NULL AFTER data_fim"),
        ):
            cursor.execute("SHOW COLUMNS FROM reserva LIKE %s", (column,))
            if cursor.fetchone() is None:
                cursor.execute(f"ALTER TABLE reserva ADD COLUMN {column} {definition}")
        for table, index in (
            ("gasto", "uq_gasto_id_viagem"),
            ("atividade", "uq_atividade_id_viagem"),
            ("reserva", "uq_reserva_id_viagem"),
        ):
            cursor.execute(f"SHOW INDEX FROM {table} WHERE Key_name = %s", (index,))
            if not cursor.fetchall():
                cursor.execute(f"ALTER TABLE {table} ADD UNIQUE KEY {index} (id, viagem_id)")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS participante (
                id INT NOT NULL AUTO_INCREMENT,
                viagem_id INT NOT NULL,
                nome VARCHAR(150) NOT NULL,
                PRIMARY KEY (id),
                UNIQUE KEY uq_participante_viagem_nome (viagem_id, nome),
                UNIQUE KEY uq_participante_id_viagem (id, viagem_id),
                CONSTRAINT fk_participante_viagem FOREIGN KEY (viagem_id) REFERENCES viagem(id)
                    ON DELETE CASCADE ON UPDATE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS pagamento_gasto (
                id INT NOT NULL AUTO_INCREMENT,
                viagem_id INT NOT NULL,
                gasto_id INT NOT NULL,
                participante_id INT NULL,
                valor_brl DECIMAL(14,2) NOT NULL,
                forma_pagamento VARCHAR(30) NULL,
                PRIMARY KEY (id),
                KEY idx_pagamento_gasto (gasto_id, viagem_id),
                KEY idx_pagamento_participante (participante_id, viagem_id),
                CONSTRAINT chk_pagamento_gasto_valor CHECK (valor_brl > 0),
                CONSTRAINT fk_pagamento_gasto FOREIGN KEY (gasto_id, viagem_id) REFERENCES gasto(id, viagem_id)
                    ON DELETE CASCADE ON UPDATE CASCADE,
                CONSTRAINT fk_pagamento_participante FOREIGN KEY (participante_id, viagem_id) REFERENCES participante(id, viagem_id)
                    ON DELETE RESTRICT ON UPDATE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS anexo (
                id INT NOT NULL AUTO_INCREMENT,
                viagem_id INT NOT NULL,
                gasto_id INT NULL,
                atividade_id INT NULL,
                nome_original VARCHAR(255) NOT NULL,
                nome_armazenado VARCHAR(80) NOT NULL,
                mime_type VARCHAR(80) NOT NULL,
                tamanho_bytes INT UNSIGNED NOT NULL,
                is_capa BOOLEAN NOT NULL DEFAULT FALSE,
                criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                UNIQUE KEY uq_anexo_nome_armazenado (nome_armazenado),
                KEY idx_anexo_viagem (viagem_id),
                KEY idx_anexo_gasto (gasto_id, viagem_id),
                KEY idx_anexo_atividade (atividade_id, viagem_id),
                CONSTRAINT fk_anexo_viagem FOREIGN KEY (viagem_id) REFERENCES viagem(id)
                    ON DELETE CASCADE ON UPDATE CASCADE,
                CONSTRAINT fk_anexo_gasto FOREIGN KEY (gasto_id, viagem_id) REFERENCES gasto(id, viagem_id)
                    ON DELETE CASCADE ON UPDATE CASCADE,
                CONSTRAINT fk_anexo_atividade FOREIGN KEY (atividade_id, viagem_id) REFERENCES atividade(id, viagem_id)
                    ON DELETE CASCADE ON UPDATE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        for constraint, column, referenced_table, index in (
            ("fk_anexo_gasto", "gasto_id", "gasto", "idx_anexo_gasto"),
            ("fk_anexo_atividade", "atividade_id", "atividade", "idx_anexo_atividade"),
        ):
            cursor.execute("SHOW INDEX FROM anexo WHERE Key_name = %s", (index,))
            if not cursor.fetchall():
                cursor.execute(f"ALTER TABLE anexo ADD KEY {index} ({column}, viagem_id)")
            cursor.execute(
                """
                SELECT COLUMN_NAME
                FROM information_schema.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'anexo'
                  AND CONSTRAINT_NAME = %s
                ORDER BY ORDINAL_POSITION
                """,
                (constraint,),
            )
            foreign_key_columns = [row[0] for row in cursor.fetchall()]
            if foreign_key_columns == [column]:
                cursor.execute(f"ALTER TABLE anexo DROP FOREIGN KEY {constraint}")
                foreign_key_columns = []
            if not foreign_key_columns:
                cursor.execute(
                    f"ALTER TABLE anexo ADD CONSTRAINT {constraint} "
                    f"FOREIGN KEY ({column}, viagem_id) REFERENCES {referenced_table}(id, viagem_id) "
                    "ON DELETE CASCADE ON UPDATE CASCADE"
                )
        cursor.execute("SHOW COLUMNS FROM anexo LIKE 'is_capa'")
        if cursor.fetchone() is None:
            cursor.execute("ALTER TABLE anexo ADD COLUMN is_capa BOOLEAN NOT NULL DEFAULT FALSE AFTER tamanho_bytes")
        cursor.execute("SHOW COLUMNS FROM atividade LIKE 'observacao'")
        if cursor.fetchone() is None:
            cursor.execute("ALTER TABLE atividade ADD COLUMN observacao TEXT NULL AFTER custo_estimado")
        for column, definition in (
            ("horario", "TIME NULL"),
            ("local", "VARCHAR(255) NULL"),
            ("situacao", "VARCHAR(20) NOT NULL DEFAULT 'planejada'"),
        ):
            cursor.execute(f"SHOW COLUMNS FROM atividade LIKE '{column}'")
            if cursor.fetchone() is None:
                cursor.execute(f"ALTER TABLE atividade ADD COLUMN {column} {definition}")
        self.conn.commit()
        cursor.close()

    def _read_json(self):
        if not DATA_FILE.exists():
            return {"viagem": None}

        try:
            with DATA_FILE.open("r", encoding="utf-8") as arquivo:
                dados = json.load(arquivo)
        except (json.JSONDecodeError, OSError):
            return {"viagem": None}

        if not isinstance(dados, dict):
            return {"viagem": None}

        return dados

    def _write_json(self, dados):
        try:
            with DATA_FILE.open("w", encoding="utf-8") as arquivo:
                json.dump(dados, arquivo, ensure_ascii=False, indent=2)
        except OSError:
            print("Não foi possível salvar os dados no arquivo.")

    def _format_date_to_db(self, value):
        if not value or value == "Não informada":
            return None

        from datetime import datetime

        try:
            return datetime.strptime(value, "%d/%m/%Y").date().isoformat()
        except ValueError:
            return value

    def _parse_date_from_db(self, value):
        if not value:
            return "Não informada"

        from datetime import datetime

        try:
            return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return str(value)

    def load_data(self):
        if self.mysql_enabled:
            return {"viagens": self.list_viagens()}
        return self._read_json()

    def save_data(self, dados):
        if self.mysql_enabled:
            viagens = dados.get("viagens")
            if viagens is None and dados.get("viagem"):
                viagens = [dados["viagem"]]
            for viagem in viagens or []:
                self.save_viagem(viagem)
            return

        self._ensure_daily_backup()
        self._write_json(dados)
        self._ensure_daily_backup()

    def _json_viagens(self):
        dados = self._read_json()
        viagens = dados.get("viagens")
        if not isinstance(viagens, list):
            viagem = dados.get("viagem")
            viagens = [viagem] if isinstance(viagem, dict) else []

        for viagem_index, viagem in enumerate(viagens, start=1):
            viagem.setdefault("id", viagem_index)
            viagem.setdefault("bandeira", "")
            viagem["bandeira"] = normalize_country_code(viagem["bandeira"], strict=False)
            viagem.setdefault("planejamento", [])
            viagem.setdefault("pessoas", [])
            viagem.setdefault("anexos", [])
            viagem.setdefault("reservas", [])
            people_names = {
                person.get("id"): person.get("nome", "")
                for person in viagem.get("pessoas", [])
            }
            for gasto in viagem.get("gastos", []):
                old_actual = float(gasto.get("valor_real") or 0.0)
                gasto.setdefault("data_gasto", viagem.get("data_ida", "01/01/2000"))
                gasto.setdefault("moeda", "BRL")
                gasto.setdefault("pago", old_actual > 0)
                gasto.setdefault("valor_original", old_actual)
                gasto.setdefault("cotacao", 1.0)
                gasto.setdefault("forma_pagamento", None)
                gasto.setdefault("observacao", "")
                gasto.setdefault("pagamentos", [])
                for payment in gasto["pagamentos"]:
                    payment.setdefault("participante_nome", people_names.get(payment.get("participante_id"), ""))
                    payment.setdefault("forma_pagamento", "")
                    payment["valor_brl"] = float(payment.get("valor_brl", 0))
                gasto["valor_em_brl"] = self._convert_to_brl(gasto["valor_original"], gasto["cotacao"])
            for atividade in viagem.get("atividades", []):
                atividade.setdefault("observacao", "")
                atividade.setdefault("horario", "")
                atividade.setdefault("local", "")
                atividade.setdefault("situacao", "planejada")
            for reserva in viagem.get("reservas", []):
                reserva.setdefault("codigo_confirmacao", "")
                reserva.setdefault("horario_checkin", "")
                reserva.setdefault("horario_checkout", "")
                reserva.setdefault("local", "")
                reserva.setdefault("prazo_cancelamento", "")
                reserva.setdefault("situacao", "pendente")
                reserva.setdefault("observacao", "")
            for attachment in viagem.get("anexos", []):
                attachment.setdefault("is_capa", False)
            viagem.get("atividades", []).sort(
                key=lambda atividade: (
                    datetime.strptime(atividade["data"], "%d/%m/%Y"),
                    atividade.get("horario") or "99:99",
                    atividade.get("nome", "").casefold(),
                )
            )
            for collection in ("gastos", "atividades", "pessoas", "anexos", "reservas"):
                items = viagem.get(collection, [])
                next_item_id = max((int(item.get("id", 0)) for item in items), default=0)
                for item in items:
                    if item.get("id") is None:
                        next_item_id += 1
                        item["id"] = next_item_id
        return viagens

    def list_viagens(self):
        if not self.mysql_enabled or not self.conn:
            return self._json_viagens()

        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM viagem ORDER BY data_ida DESC, id DESC")
        viagem_ids = [row[0] for row in cursor.fetchall()]
        cursor.close()
        return [self.get_viagem(viagem_id) for viagem_id in viagem_ids]

    def get_viagem(self, viagem_id=None):
        if not self.mysql_enabled or not self.conn:
            viagens = self._json_viagens()
            if viagem_id is not None:
                return next((v for v in viagens if v.get("id") == viagem_id), None)
            return viagens[-1] if viagens else None

        cursor = self.conn.cursor(dictionary=True)
        if viagem_id is None:
            cursor.execute("SELECT * FROM viagem ORDER BY id DESC LIMIT 1")
        else:
            cursor.execute("SELECT * FROM viagem WHERE id = %s", (viagem_id,))
        viagem = cursor.fetchone()

        if not viagem:
            cursor.close()
            return None

        viagem_id = viagem["id"]
        cursor.execute(
            "SELECT * FROM gasto WHERE viagem_id = %s ORDER BY id",
            (viagem_id,),
        )
        gastos = cursor.fetchall() or []

        cursor.execute(
            "SELECT * FROM atividade WHERE viagem_id = %s ORDER BY data_atividade, (horario IS NULL), horario, id",
            (viagem_id,),
        )
        atividades = cursor.fetchall() or []

        cursor.execute(
            "SELECT * FROM reserva WHERE viagem_id = %s ORDER BY data_inicio, id",
            (viagem_id,),
        )
        reservas = cursor.fetchall() or []

        cursor.execute(
            "SELECT id, nome FROM participante WHERE viagem_id = %s ORDER BY nome, id",
            (viagem_id,),
        )
        pessoas = cursor.fetchall() or []
        nomes_por_pessoa = {person["id"]: person["nome"] for person in pessoas}

        cursor.execute(
            """
            SELECT id, gasto_id, participante_id, valor_brl, forma_pagamento
            FROM pagamento_gasto
            WHERE viagem_id = %s
            ORDER BY id
            """,
            (viagem_id,),
        )
        pagamentos_por_gasto = {}
        for payment in cursor.fetchall() or []:
            pagamentos_por_gasto.setdefault(payment["gasto_id"], []).append({
                "id": payment["id"],
                "participante_id": payment["participante_id"],
                "participante_nome": nomes_por_pessoa.get(payment["participante_id"], ""),
                "valor_brl": float(payment["valor_brl"]),
                "forma_pagamento": payment["forma_pagamento"] or "",
            })

        cursor.execute(
            """
            SELECT id, gasto_id, atividade_id, nome_original, nome_armazenado, mime_type, tamanho_bytes, is_capa
            FROM anexo
            WHERE viagem_id = %s
            ORDER BY id
            """,
            (viagem_id,),
        )
        anexos = cursor.fetchall() or []

        cursor.execute(
            "SELECT * FROM planejamento_categoria WHERE viagem_id = %s ORDER BY categoria",
            (viagem_id,),
        )
        planejamento = cursor.fetchall() or []

        cursor.close()

        return {
            "id": viagem_id,
            "destino": viagem["destino"],
            "bandeira": normalize_country_code(viagem.get("bandeira"), strict=False),
            "data_ida": self._parse_date_from_db(viagem["data_ida"]),
            "data_volta": self._parse_date_from_db(viagem["data_volta"]),
            "gastos": [
                {
                    "id": gasto["id"],
                    "data_gasto": self._parse_date_from_db(gasto["data_gasto"]),
                    "descricao": gasto["descricao"],
                    "categoria": gasto["categoria"],
                    "moeda": gasto["moeda"],
                    "valor_original": float(gasto["valor_original"]),
                    "cotacao": float(gasto["cotacao"]),
                    "valor_em_brl": self._convert_to_brl(gasto["valor_original"], gasto["cotacao"]),
                    "forma_pagamento": gasto.get("forma_pagamento"),
                    "observacao": gasto.get("observacao") or "",
                    "pago": bool(gasto.get("pago")),
                    "pagamentos": pagamentos_por_gasto.get(gasto["id"], []),
                }
                for gasto in gastos
            ],
            "atividades": [
                {
                    "id": atividade["id"],
                    "nome": atividade["nome"],
                    "data": self._parse_date_from_db(atividade["data_atividade"]),
                    "horario": str(atividade.get("horario") or "")[:5],
                    "local": atividade.get("local") or "",
                    "custo_estimado": float(atividade["custo_estimado"]) if atividade["custo_estimado"] is not None else None,
                    "observacao": atividade.get("observacao") or "",
                    "situacao": atividade.get("situacao") or "planejada",
                }
                for atividade in atividades
            ],
            "reservas": [
                {
                    "id": reserva["id"],
                    "tipo": reserva["tipo"],
                    "fornecedor": reserva["fornecedor"],
                    "codigo_confirmacao": reserva.get("codigo_confirmacao") or "",
                    "data_inicio": self._parse_date_from_db(reserva["data_inicio"]),
                    "horario_checkin": str(reserva.get("horario_checkin") or "")[:5],
                    "data_fim": self._parse_date_from_db(reserva["data_fim"]),
                    "horario_checkout": str(reserva.get("horario_checkout") or "")[:5],
                    "local": reserva.get("local") or "",
                    "prazo_cancelamento": self._parse_date_from_db(reserva["prazo_cancelamento"]) if reserva.get("prazo_cancelamento") else "",
                    "situacao": reserva.get("situacao") or "pendente",
                    "observacao": reserva.get("observacao") or "",
                }
                for reserva in reservas
            ],
            "planejamento": [
                {
                    "id": row["id"],
                    "categoria": row["categoria"],
                    "valor_previsto": float(row["valor_previsto"]),
                }
                for row in planejamento
            ],
            "pessoas": [
                {"id": pessoa["id"], "nome": pessoa["nome"]}
                for pessoa in pessoas
            ],
            "anexos": [dict(anexo) for anexo in anexos],
        }

    def _convert_to_brl(self, valor_original, cotacao):
        converted = Decimal(str(valor_original)) * Decimal(str(cotacao))
        return float(converted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def save_viagem(self, viagem):
        if not self.mysql_enabled or not self.conn:
            dados = self._read_json()
            viagens = self._json_viagens()
            self._ensure_daily_backup()
            if viagem.get("id") is None:
                viagem["id"] = max((v["id"] for v in viagens), default=0) + 1
                viagens.append(viagem)
            else:
                for index, existente in enumerate(viagens):
                    if existente.get("id") == viagem["id"]:
                        viagens[index] = viagem
                        break
                else:
                    viagens.append(viagem)
            for collection in ("gastos", "atividades", "pessoas", "anexos", "reservas"):
                items = viagem.setdefault(collection, [])
                next_item_id = max((int(item.get("id", 0)) for item in items), default=0)
                for item in items:
                    if item.get("id") is None:
                        next_item_id += 1
                        item["id"] = next_item_id
            dados.pop("viagem", None)
            dados["viagens"] = viagens
            self._write_json(dados)
            self._ensure_daily_backup()
            return

        self._ensure_daily_backup()
        cursor = self.conn.cursor()
        viagem_id = viagem.get("id")

        if viagem_id is None:
            cursor.execute(
                """
                INSERT INTO viagem (destino, bandeira, data_ida, data_volta)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    viagem["destino"],
                    viagem.get("bandeira") or None,
                    self._format_date_to_db(viagem["data_ida"]),
                    self._format_date_to_db(viagem["data_volta"]),
                ),
            )
            viagem_id = cursor.lastrowid
        else:
            cursor.execute(
                """
                UPDATE viagem
                SET destino = %s,
                    bandeira = %s,
                    data_ida = %s,
                    data_volta = %s
                WHERE id = %s
                """,
                (
                    viagem["destino"],
                    viagem.get("bandeira") or None,
                    self._format_date_to_db(viagem["data_ida"]),
                    self._format_date_to_db(viagem["data_volta"]),
                    viagem_id,
                ),
            )

        self._sync_items(cursor, "gasto", viagem_id, viagem.get("gastos", []))
        self._sync_items(cursor, "atividade", viagem_id, viagem.get("atividades", []))
        self._sync_items(cursor, "reserva", viagem_id, viagem.get("reservas", []))
        self._sync_planning(cursor, viagem_id, viagem.get("planejamento", []))
        self._sync_people(cursor, viagem_id, viagem.get("pessoas", []))
        self._sync_expense_payments(cursor, viagem_id, viagem.get("gastos", []))
        self._sync_attachments(cursor, viagem_id, viagem.get("anexos", []))

        cursor.close()
        viagem["id"] = viagem_id
        self._ensure_daily_backup()

    def _sync_people(self, cursor, viagem_id, people):
        cursor.execute("SELECT id FROM participante WHERE viagem_id = %s", (viagem_id,))
        existing_ids = {row[0] for row in cursor.fetchall()}
        retained_ids = set()
        for person in people:
            person_id = person.get("id")
            if person_id in existing_ids:
                cursor.execute(
                    "UPDATE participante SET nome = %s WHERE id = %s AND viagem_id = %s",
                    (person["nome"], person_id, viagem_id),
                )
            else:
                cursor.execute(
                    "INSERT INTO participante (viagem_id, nome) VALUES (%s, %s)",
                    (viagem_id, person["nome"]),
                )
                person_id = cursor.lastrowid
                person["id"] = person_id
            retained_ids.add(person_id)

        deleted_ids = existing_ids - retained_ids
        if deleted_ids:
            placeholders = ", ".join(["%s"] * len(deleted_ids))
            cursor.execute(
                f"DELETE FROM participante WHERE viagem_id = %s AND id IN ({placeholders})",
                (viagem_id, *deleted_ids),
            )

    def _sync_expense_payments(self, cursor, viagem_id, expenses):
        cursor.execute("DELETE FROM pagamento_gasto WHERE viagem_id = %s", (viagem_id,))
        cursor.execute("SELECT id, nome FROM participante WHERE viagem_id = %s", (viagem_id,))
        ids_por_nome = {name.casefold(): person_id for person_id, name in cursor.fetchall()}
        for expense in expenses:
            expense_id = expense.get("id")
            if expense_id is None:
                continue
            for payment in expense.get("pagamentos", []):
                participant_id = payment.get("participante_id")
                participant_name = (payment.get("participante_nome") or "").strip()
                if participant_id is None and participant_name:
                    participant_id = ids_por_nome.get(participant_name.casefold())
                    if participant_id is None:
                        raise ValueError(f"O pagador {participant_name} não pertence a esta viagem.")
                cursor.execute(
                    """
                    INSERT INTO pagamento_gasto
                        (viagem_id, gasto_id, participante_id, valor_brl, forma_pagamento)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        viagem_id,
                        expense_id,
                        participant_id,
                        float(payment["valor_brl"]),
                        payment.get("forma_pagamento") or None,
                    ),
                )

    def _sync_attachments(self, cursor, viagem_id, attachments):
        cursor.execute("SELECT id FROM anexo WHERE viagem_id = %s", (viagem_id,))
        existing_ids = {row[0] for row in cursor.fetchall()}
        retained_ids = set()
        columns = (
            "gasto_id",
            "atividade_id",
            "nome_original",
            "nome_armazenado",
            "mime_type",
            "tamanho_bytes",
            "is_capa",
        )
        for attachment in attachments:
            values = tuple(attachment.get(column) for column in columns)
            attachment_id = attachment.get("id")
            if attachment_id in existing_ids:
                assignments = ", ".join(f"{column} = %s" for column in columns)
                cursor.execute(
                    f"UPDATE anexo SET {assignments} WHERE id = %s AND viagem_id = %s",
                    (*values, attachment_id, viagem_id),
                )
                retained_ids.add(attachment_id)
            else:
                column_sql = ", ".join(("viagem_id", *columns))
                placeholders = ", ".join(["%s"] * (len(columns) + 1))
                cursor.execute(
                    f"INSERT INTO anexo ({column_sql}) VALUES ({placeholders})",
                    (viagem_id, *values),
                )
                attachment_id = cursor.lastrowid
                attachment["id"] = attachment_id
                retained_ids.add(attachment_id)

        deleted_ids = existing_ids - retained_ids
        if deleted_ids:
            placeholders = ", ".join(["%s"] * len(deleted_ids))
            cursor.execute(
                f"DELETE FROM anexo WHERE viagem_id = %s AND id IN ({placeholders})",
                (viagem_id, *deleted_ids),
            )

    def restore_viagens(self, trips, create_backup=True):
        restored = deepcopy(trips)
        for trip in restored:
            trip.pop("id", None)
            for collection in ("gastos", "atividades", "planejamento", "pessoas", "anexos", "reservas"):
                for item in trip.get(collection, []):
                    item.pop("id", None)

        if create_backup:
            self._ensure_daily_backup()
        previous_backup_state = self._backup_suspended
        self._backup_suspended = True
        if self.mysql_enabled and self.conn:
            original_autocommit = self.conn.autocommit
            try:
                self.conn.autocommit = False
                for trip in restored:
                    self.save_viagem(trip)
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
            finally:
                self.conn.autocommit = original_autocommit
                self._backup_suspended = previous_backup_state
        else:
            previous_data = self._read_json()
            try:
                for trip in restored:
                    self.save_viagem(trip)
            except Exception:
                self._write_json(previous_data)
                raise
            finally:
                self._backup_suspended = previous_backup_state

        if create_backup:
            self._ensure_daily_backup()
        return restored

    def _sync_items(self, cursor, table, viagem_id, items):
        if table == "gasto":
            columns = (
                "data_gasto",
                "descricao",
                "categoria",
                "moeda",
                "valor_original",
                "cotacao",
                "forma_pagamento",
                "observacao",
                "pago",
            )
            values_for = lambda item: (
                self._format_date_to_db(item["data_gasto"]),
                item["descricao"],
                item["categoria"],
                item["moeda"],
                float(item["valor_original"]),
                float(item["cotacao"]),
                item.get("forma_pagamento"),
                item.get("observacao") or None,
                bool(item.get("pago", False)),
            )
        elif table == "atividade":
            columns = ("nome", "data_atividade", "horario", "local", "custo_estimado", "observacao", "situacao")
            values_for = lambda item: (
                item.get("nome", "Sem nome"),
                self._format_date_to_db(item.get("data", "Não informada")),
                item.get("horario") or None,
                item.get("local") or None,
                float(item["custo_estimado"]) if item.get("custo_estimado") not in (None, "") else None,
                item.get("observacao") or None,
                item.get("situacao") or "planejada",
            )
        else:
            columns = (
                "tipo", "fornecedor", "codigo_confirmacao", "data_inicio", "horario_checkin",
                "data_fim", "horario_checkout", "local", "prazo_cancelamento", "situacao", "observacao",
            )
            values_for = lambda item: (
                item["tipo"],
                item["fornecedor"],
                item.get("codigo_confirmacao") or None,
                self._format_date_to_db(item["data_inicio"]),
                item.get("horario_checkin") or None,
                self._format_date_to_db(item["data_fim"]),
                item.get("horario_checkout") or None,
                item.get("local") or None,
                self._format_date_to_db(item["prazo_cancelamento"]) if item.get("prazo_cancelamento") else None,
                item.get("situacao") or "pendente",
                item.get("observacao") or None,
            )

        cursor.execute(f"SELECT id FROM {table} WHERE viagem_id = %s", (viagem_id,))
        existing_ids = {row[0] for row in cursor.fetchall()}
        retained_ids = set()
        column_sql = ", ".join(columns)
        placeholders = ", ".join(["%s"] * len(columns))

        for item in items:
            values = values_for(item)
            item_id = item.get("id")
            if item_id in existing_ids:
                assignments = ", ".join(f"{column} = %s" for column in columns)
                cursor.execute(
                    f"UPDATE {table} SET {assignments} WHERE id = %s AND viagem_id = %s",
                    (*values, item_id, viagem_id),
                )
                retained_ids.add(item_id)
            else:
                cursor.execute(
                    f"INSERT INTO {table} (viagem_id, {column_sql}) VALUES (%s, {placeholders})",
                    (viagem_id, *values),
                )
                item["id"] = cursor.lastrowid
                retained_ids.add(item["id"])

        deleted_ids = existing_ids - retained_ids
        if deleted_ids:
            placeholders = ", ".join(["%s"] * len(deleted_ids))
            cursor.execute(
                f"DELETE FROM {table} WHERE viagem_id = %s AND id IN ({placeholders})",
                (viagem_id, *deleted_ids),
            )

    def _sync_planning(self, cursor, viagem_id, items):
        cursor.execute(
            "SELECT id, categoria FROM planejamento_categoria WHERE viagem_id = %s",
            (viagem_id,),
        )
        existing = {row[1]: row[0] for row in cursor.fetchall()}
        retained_categories = set()
        for item in items:
            category = item["categoria"]
            amount = float(item.get("valor_previsto", 0.0))
            if category in existing:
                cursor.execute(
                    "UPDATE planejamento_categoria SET valor_previsto = %s WHERE id = %s",
                    (amount, existing[category]),
                )
            else:
                cursor.execute(
                    "INSERT INTO planejamento_categoria (viagem_id, categoria, valor_previsto) VALUES (%s, %s, %s)",
                    (viagem_id, category, amount),
                )
            retained_categories.add(category)

        categories_to_delete = set(existing) - retained_categories
        if categories_to_delete:
            placeholders = ", ".join(["%s"] * len(categories_to_delete))
            cursor.execute(
                f"DELETE FROM planejamento_categoria WHERE viagem_id = %s AND categoria IN ({placeholders})",
                (viagem_id, *categories_to_delete),
            )

    def delete_viagem(self, viagem_id):
        self._ensure_daily_backup()
        viagem = self.get_viagem(viagem_id)
        if viagem is None:
            return
        attachment_names = [
            attachment["nome_armazenado"]
            for attachment in viagem.get("anexos", [])
            if attachment.get("nome_armazenado")
        ]
        if not self.mysql_enabled or not self.conn:
            dados = self._read_json()
            viagens = [v for v in self._json_viagens() if v.get("id") != viagem_id]
            dados.pop("viagem", None)
            dados["viagens"] = viagens
            self._write_json(dados)
        else:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM pagamento_gasto WHERE viagem_id = %s", (viagem_id,))
            cursor.execute("DELETE FROM participante WHERE viagem_id = %s", (viagem_id,))
            cursor.execute("DELETE FROM viagem WHERE id = %s", (viagem_id,))
            self.conn.commit()
            cursor.close()
        for stored_name in attachment_names:
            attachment_service.delete_attachment(stored_name)
        self._ensure_daily_backup()
        self._ensure_daily_backup()

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None


storage_manager = StorageManager()
