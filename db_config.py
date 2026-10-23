import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "controle_viagem"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "controle_viagem"),
    "autocommit": True,
    "charset": "utf8mb4",
}

if os.getenv("DB_SSL_REQUIRED", "").strip().lower() in {"1", "true", "yes"}:
    DB_CONFIG["ssl_disabled"] = False
    ca_file = os.getenv("DB_SSL_CA", "").strip()
    if ca_file:
        if not Path(ca_file).is_file():
            raise RuntimeError("O arquivo indicado em DB_SSL_CA não existe.")
        DB_CONFIG["ssl_ca"] = ca_file
        DB_CONFIG["ssl_verify_cert"] = True
        DB_CONFIG["ssl_verify_identity"] = True
