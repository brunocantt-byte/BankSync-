import os

import psycopg
from dotenv import load_dotenv


ENV_PATH = r"C:\ConciliaFinanceira\.env"


def conectar_conciliador():
    load_dotenv(ENV_PATH)
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def listar_bancos_postgres():
    with conectar_conciliador() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                    SELECT datname
                    FROM pg_database
                    WHERE datistemplate = false
                    ORDER BY datname;
                """
            )
            return [linha[0] for linha in cursor.fetchall()]


def main():
    print("PostgreSQL local acessivel com as credenciais do conciliador.")
    print("Bancos encontrados:")

    for nome in listar_bancos_postgres():
        print(f"- {nome}")


if __name__ == "__main__":
    main()
