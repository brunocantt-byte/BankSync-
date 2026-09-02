from configparser import ConfigParser
from pathlib import Path
import sys

import psycopg
from dotenv import load_dotenv

from clinux_tunel import abrir_tunel_proprio


INI_PATH = Path(r"C:\CLINUX CTR INTERNET\clinux.ini")
ENV_PATH = Path(r"C:\ConciliaFinanceira\.env")
SECAO_CONEXAO = "CTR - EXTERNO"


def carregar_config():
    load_dotenv(ENV_PATH)
    parser = ConfigParser(interpolation=None)
    parser.optionxform = str.upper
    parser.read(INI_PATH, encoding="utf-8")

    if not parser.has_section(SECAO_CONEXAO):
        raise ValueError(f"Secao nao encontrada no INI: {SECAO_CONEXAO}")

    secao = parser[SECAO_CONEXAO]
    def valor(nome_env, valor_ini=""):
        import os

        return (os.getenv(nome_env) or valor_ini or "").strip()

    return {
        "host": valor("CLINUX_DB_HOST", secao.get("HOSTNAME")),
        "port": valor("CLINUX_DB_PORT", secao.get("PORT", "5432")),
        "dbname": valor("CLINUX_DB_NAME", secao.get("DATABASE")),
        "user": valor("CLINUX_DB_USER", secao.get("USER")),
        "password": valor("CLINUX_DB_PASSWORD", secao.get("PASSWORD")),
        "password_alt": valor("CLINUX_DB_PASSWORD_ALT", secao.get("PASSWORDX")),
        "tunnel_port": valor("CLINUX_TUNNEL_PORT", secao.get("SSHTUNN")),
        "ssh_host": valor("CLINUX_SSH_HOST", secao.get("SSHHOST")),
        "ssh_port": valor("CLINUX_SSH_PORT", secao.get("SSHPORT", "22")),
        "ssh_user": valor("CLINUX_SSH_USER", secao.get("SSHUSER")),
        "ssh_password": valor("CLINUX_SSH_PASSWORD", secao.get("SSHPASS")),
        "ssh_password_alt": valor("CLINUX_SSH_PASSWORD_ALT", secao.get("SSHPASSX")),
        "ssh_key_path": valor("CLINUX_SSH_KEY_PATH"),
    }


def tentar_conectar(config, password):
    return psycopg.connect(
        host=config["host"],
        port=config["port"],
        dbname=config["dbname"],
        user=config["user"],
        password=password,
        connect_timeout=8,
    )


def conectar(config):
    erros = []
    alvos = [
        ("direto", config["host"], config["port"]),
    ]

    if config["tunnel_port"]:
        alvos.append(("tunel", "127.0.0.1", config["tunnel_port"]))

    for alvo_label, host, port in alvos:
        config_alvo = {**config, "host": host, "port": port}

        for password_label, password in (
            ("PASSWORD", config["password"]),
            ("PASSWORDX", config["password_alt"]),
        ):
            if not password:
                continue

            try:
                conexao = tentar_conectar(config_alvo, password)
                return f"{alvo_label}/{password_label}", conexao
            except Exception as erro:
                erros.append(f"{alvo_label}/{password_label}: {type(erro).__name__}")

    if config.get("ssh_host") and config.get("ssh_user"):
        try:
            ssh_label, tunel = abrir_tunel_proprio(config)
            config_alvo = {
                **config,
                "host": tunel.local_host,
                "port": str(tunel.local_port),
            }

            for password_label, password in (
                ("PASSWORD", config["password"]),
                ("PASSWORDX", config["password_alt"]),
            ):
                if not password:
                    continue

                try:
                    conexao = tentar_conectar(config_alvo, password)
                    return f"tunel_proprio/{ssh_label}/{password_label}", conexao
                except Exception as erro:
                    erros.append(
                        f"tunel_proprio/{ssh_label}/{password_label}: "
                        f"{type(erro).__name__}"
                    )
        except Exception as erro:
            erros.append(f"tunel_proprio: {type(erro).__name__}")

    raise ConnectionError("Nao foi possivel conectar. Tentativas: " + ", ".join(erros))


def listar_tabelas(conexao):
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
                LIMIT 120;
            """
        )
        tabelas = cursor.fetchall()

    return banco, usuario, tabelas


def main():
    if not INI_PATH.exists():
        raise FileNotFoundError(f"INI nao encontrado: {INI_PATH}")

    config = carregar_config()
    print(
        "Config encontrada: "
        f"host={config['host']} porta={config['port']} banco={config['dbname']}"
    )

    label, conexao = conectar(config)
    with conexao:
        banco, usuario, tabelas = listar_tabelas(conexao)

    print(f"Conexao OK usando {label}. Banco={banco}. Usuario={usuario}.")
    print("Tabelas encontradas:")

    for schema, tabela in tabelas:
        print(f"- {schema}.{tabela}")


if __name__ == "__main__":
    try:
        main()
    except Exception as erro:
        print(f"Falha no diagnostico Clinux: {erro}")
        sys.exit(1)
