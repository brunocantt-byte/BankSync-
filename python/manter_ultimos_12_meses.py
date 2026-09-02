from __future__ import annotations

from argparse import ArgumentParser
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import csv
import json
import os

import psycopg
from dotenv import load_dotenv


BASE_DIR = Path(r"C:\ConciliaFinanceira")
BACKUP_DIR = BASE_DIR / "dados" / "backups"
CUTOFF = date(2025, 9, 1)


def conectar():
    load_dotenv(BASE_DIR / ".env")
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def serializar(valor):
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    if isinstance(valor, (dict, list)):
        return json.dumps(valor, ensure_ascii=False)
    return valor


def exportar(cur, caminho: Path, sql: str, params: tuple):
    cur.execute(sql, params)
    colunas = [desc.name for desc in cur.description]
    with caminho.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp, delimiter=";")
        writer.writerow(colunas)
        for row in cur.fetchall():
            writer.writerow([serializar(value) for value in row])


def contar(cur):
    cur.execute(
        """
        SELECT COUNT(*), MIN(data_movimento), MAX(data_movimento),
               COALESCE(SUM(CASE WHEN tipo_movimento = 'ENTRADA' THEN valor ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN tipo_movimento = 'SAIDA' THEN valor ELSE 0 END), 0)
        FROM transacoes_bancarias
        WHERE data_movimento < %s
        """,
        (CUTOFF,),
    )
    banco_remover = cur.fetchone()

    cur.execute(
        """
        SELECT COUNT(*), MIN(COALESCE(data_pagamento, data_lancamento)),
               MAX(COALESCE(data_pagamento, data_lancamento)),
               COALESCE(SUM(CASE WHEN tipo_movimento = 'ENTRADA' THEN valor ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN tipo_movimento = 'SAIDA' THEN valor ELSE 0 END), 0)
        FROM lancamentos_sistema
        WHERE COALESCE(data_pagamento, data_lancamento) < %s
        """,
        (CUTOFF,),
    )
    sistema_remover = cur.fetchone()

    cur.execute(
        """
        SELECT COUNT(*), MIN(data_movimento), MAX(data_movimento),
               COALESCE(SUM(CASE WHEN tipo_movimento = 'ENTRADA' THEN valor ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN tipo_movimento = 'SAIDA' THEN valor ELSE 0 END), 0)
        FROM transacoes_bancarias
        WHERE data_movimento >= %s
        """,
        (CUTOFF,),
    )
    banco_manter = cur.fetchone()

    cur.execute(
        """
        SELECT COUNT(*), MIN(COALESCE(data_pagamento, data_lancamento)),
               MAX(COALESCE(data_pagamento, data_lancamento)),
               COALESCE(SUM(CASE WHEN tipo_movimento = 'ENTRADA' THEN valor ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN tipo_movimento = 'SAIDA' THEN valor ELSE 0 END), 0)
        FROM lancamentos_sistema
        WHERE COALESCE(data_pagamento, data_lancamento) >= %s
        """,
        (CUTOFF,),
    )
    sistema_manter = cur.fetchone()

    cur.execute(
        """
        SELECT COUNT(*)
        FROM conciliacao_vinculos cv
        WHERE EXISTS (
            SELECT 1 FROM transacoes_bancarias tb
            WHERE tb.id = cv.transacao_bancaria_id
              AND tb.data_movimento < %s
        )
        OR EXISTS (
            SELECT 1 FROM lancamentos_sistema ls
            WHERE ls.id = cv.lancamento_sistema_id
              AND COALESCE(ls.data_pagamento, ls.data_lancamento) < %s
        )
        """,
        (CUTOFF, CUTOFF),
    )
    vinculos_remover = cur.fetchone()[0]

    return {
        "corte": CUTOFF.isoformat(),
        "remover": {
            "banco": banco_remover,
            "sistema": sistema_remover,
            "vinculos_conciliacao": vinculos_remover,
        },
        "manter": {
            "banco": banco_manter,
            "sistema": sistema_manter,
        },
    }


def backup(cur):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    arquivos = {
        "vinculos": BACKUP_DIR / f"retencao_12m_conciliacao_vinculos_antes_{CUTOFF}_{stamp}.csv",
        "banco": BACKUP_DIR / f"retencao_12m_transacoes_bancarias_antes_{CUTOFF}_{stamp}.csv",
        "sistema": BACKUP_DIR / f"retencao_12m_lancamentos_sistema_antes_{CUTOFF}_{stamp}.csv",
        "conciliacoes": BACKUP_DIR / f"retencao_12m_conciliacoes_relacionadas_antes_{CUTOFF}_{stamp}.csv",
    }

    exportar(
        cur,
        arquivos["vinculos"],
        """
        SELECT cv.*
        FROM conciliacao_vinculos cv
        WHERE EXISTS (
            SELECT 1 FROM transacoes_bancarias tb
            WHERE tb.id = cv.transacao_bancaria_id
              AND tb.data_movimento < %s
        )
        OR EXISTS (
            SELECT 1 FROM lancamentos_sistema ls
            WHERE ls.id = cv.lancamento_sistema_id
              AND COALESCE(ls.data_pagamento, ls.data_lancamento) < %s
        )
        ORDER BY cv.id
        """,
        (CUTOFF, CUTOFF),
    )
    exportar(
        cur,
        arquivos["conciliacoes"],
        """
        SELECT DISTINCT c.*
        FROM conciliacoes c
        JOIN conciliacao_vinculos cv ON cv.conciliacao_id = c.id
        WHERE EXISTS (
            SELECT 1 FROM transacoes_bancarias tb
            WHERE tb.id = cv.transacao_bancaria_id
              AND tb.data_movimento < %s
        )
        OR EXISTS (
            SELECT 1 FROM lancamentos_sistema ls
            WHERE ls.id = cv.lancamento_sistema_id
              AND COALESCE(ls.data_pagamento, ls.data_lancamento) < %s
        )
        ORDER BY c.id
        """,
        (CUTOFF, CUTOFF),
    )
    exportar(
        cur,
        arquivos["banco"],
        """
        SELECT *
        FROM transacoes_bancarias
        WHERE data_movimento < %s
        ORDER BY id
        """,
        (CUTOFF,),
    )
    exportar(
        cur,
        arquivos["sistema"],
        """
        SELECT *
        FROM lancamentos_sistema
        WHERE COALESCE(data_pagamento, data_lancamento) < %s
        ORDER BY id
        """,
        (CUTOFF,),
    )
    return {nome: str(caminho) for nome, caminho in arquivos.items()}


def excluir(cur):
    cur.execute(
        """
        DELETE FROM conciliacao_vinculos cv
        WHERE EXISTS (
            SELECT 1 FROM transacoes_bancarias tb
            WHERE tb.id = cv.transacao_bancaria_id
              AND tb.data_movimento < %s
        )
        OR EXISTS (
            SELECT 1 FROM lancamentos_sistema ls
            WHERE ls.id = cv.lancamento_sistema_id
              AND COALESCE(ls.data_pagamento, ls.data_lancamento) < %s
        )
        """,
        (CUTOFF, CUTOFF),
    )
    vinculos = cur.rowcount

    cur.execute(
        """
        DELETE FROM transacoes_bancarias
        WHERE data_movimento < %s
        """,
        (CUTOFF,),
    )
    banco = cur.rowcount

    cur.execute(
        """
        DELETE FROM lancamentos_sistema
        WHERE COALESCE(data_pagamento, data_lancamento) < %s
        """,
        (CUTOFF,),
    )
    sistema = cur.rowcount

    cur.execute(
        """
        DELETE FROM conciliacoes c
        WHERE NOT EXISTS (
            SELECT 1 FROM conciliacao_vinculos cv
            WHERE cv.conciliacao_id = c.id
        )
        """,
    )
    conciliacoes_orfas = cur.rowcount

    return {
        "vinculos_conciliacao": vinculos,
        "banco": banco,
        "sistema": sistema,
        "conciliacoes_sem_vinculo": conciliacoes_orfas,
    }


def main():
    parser = ArgumentParser()
    parser.add_argument("--executar", action="store_true")
    args = parser.parse_args()

    with conectar() as conn:
        with conn.cursor() as cur:
            resultado = {"antes": contar(cur)}
            if args.executar:
                resultado["backup"] = backup(cur)
                resultado["excluidos"] = excluir(cur)
                resultado["depois"] = contar(cur)
                conn.commit()
            else:
                conn.rollback()

    print(json.dumps(resultado, ensure_ascii=False, default=serializar, indent=2))


if __name__ == "__main__":
    main()
