from pathlib import Path
import os

import psycopg
from dotenv import load_dotenv


BASE_DIR = Path(r"C:\ConciliaFinanceira")
SQL_MIGRACAO = BASE_DIR / "sql" / "historico_permanente.sql"


def conectar_banco():
    load_dotenv(BASE_DIR / ".env")
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def main():
    sql = SQL_MIGRACAO.read_text(encoding="utf-8")

    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(sql)
        conexao.commit()

    print("Migracao da base historica aplicada com sucesso.")


if __name__ == "__main__":
    main()
