import sys

import psycopg

from clinux_tunel import abrir_tunel_proprio
from diagnosticar_clinux_db import carregar_config


def main():
    config = carregar_config()
    label, tunel = abrir_tunel_proprio(config)

    conexao = psycopg.connect(
        host=tunel.local_host,
        port=tunel.local_port,
        dbname=config["dbname"],
        user=config["user"],
        password=config["password"],
        connect_timeout=8,
    )

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user;")
            banco, usuario = cursor.fetchone()

    print(
        "Tunel proprio OK | "
        f"ssh={label} | "
        f"porta_local={tunel.local_port} | "
        f"banco={banco} | "
        f"usuario={usuario}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as erro:
        print(f"Falha no teste do tunel proprio: {erro}")
        sys.exit(1)
