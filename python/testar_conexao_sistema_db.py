import os
import sys

import psycopg
from dotenv import load_dotenv


ENV_PATH = r"C:\ConciliaFinanceira\.env"


def valor_env(nome):
    valor = os.getenv(nome)
    if valor is None or not valor.strip():
        raise ValueError(f"Variavel ausente no .env: {nome}")
    return valor.strip()


def conectar_postgres():
    return psycopg.connect(
        host=valor_env("SISTEMA_DB_HOST"),
        port=os.getenv("SISTEMA_DB_PORT", "5432"),
        dbname=valor_env("SISTEMA_DB_NAME"),
        user=valor_env("SISTEMA_DB_USER"),
        password=valor_env("SISTEMA_DB_PASSWORD"),
    )


def testar_postgres():
    with conectar_postgres() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user;")
            banco, usuario = cursor.fetchone()

            cursor.execute(
                """
                    SELECT table_schema, table_name
                    FROM information_schema.tables
                    WHERE table_type = 'BASE TABLE'
                      AND table_schema NOT IN ('pg_catalog', 'information_schema')
                    ORDER BY table_schema, table_name
                    LIMIT 80;
                """
            )
            tabelas = cursor.fetchall()

    print(f"Conexao PostgreSQL OK | banco={banco} | usuario={usuario}")
    print("Tabelas encontradas:")
    for schema, tabela in tabelas:
        print(f"- {schema}.{tabela}")


def testar_sqlserver():
    try:
        import pyodbc
    except ModuleNotFoundError:
        raise RuntimeError(
            "Para SQL Server, ainda falta instalar a biblioteca pyodbc "
            "no ambiente Python do projeto."
        )

    driver = os.getenv("SISTEMA_DB_DRIVER", "ODBC Driver 18 for SQL Server")
    servidor = valor_env("SISTEMA_DB_HOST")
    porta = os.getenv("SISTEMA_DB_PORT", "1433")
    banco = valor_env("SISTEMA_DB_NAME")
    usuario = valor_env("SISTEMA_DB_USER")
    senha = valor_env("SISTEMA_DB_PASSWORD")

    conexao_texto = (
        f"DRIVER={{{driver}}};"
        f"SERVER={servidor},{porta};"
        f"DATABASE={banco};"
        f"UID={usuario};"
        f"PWD={senha};"
        "TrustServerCertificate=yes;"
    )

    with pyodbc.connect(conexao_texto) as conexao:
        cursor = conexao.cursor()
        cursor.execute("SELECT DB_NAME(), SYSTEM_USER;")
        banco_atual, usuario_atual = cursor.fetchone()
        cursor.execute(
            """
                SELECT TOP 80 TABLE_SCHEMA, TABLE_NAME
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_TYPE = 'BASE TABLE'
                ORDER BY TABLE_SCHEMA, TABLE_NAME;
            """
        )
        tabelas = cursor.fetchall()

    print(f"Conexao SQL Server OK | banco={banco_atual} | usuario={usuario_atual}")
    print("Tabelas encontradas:")
    for schema, tabela in tabelas:
        print(f"- {schema}.{tabela}")


def main():
    load_dotenv(ENV_PATH)
    tipo = os.getenv("SISTEMA_DB_TIPO", "").strip().lower()

    if tipo in ("postgres", "postgresql"):
        testar_postgres()
        return

    if tipo in ("sqlserver", "mssql", "sql_server"):
        testar_sqlserver()
        return

    raise ValueError(
        "Informe SISTEMA_DB_TIPO no .env como postgres ou sqlserver."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as erro:
        print(f"Falha ao testar conexao do sistema: {erro}")
        sys.exit(1)
