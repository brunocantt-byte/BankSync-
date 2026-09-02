from __future__ import annotations

from argparse import ArgumentParser
import csv
import hashlib
import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from base_historica import (
    calcular_hash,
    conectar_banco,
    detectar_periodo,
    registrar_arquivo_historico,
)
from importar_historico import cnpj_para_db


ARQUIVO_PADRAO = Path(
    r"C:\ConciliaFinanceira\dados\extracoes"
    r"\transacoes_pdfs_bancos_extratos_2024_2026_deduplicadas.csv"
)


def texto(valor):
    return (valor or "").strip()


def normalizar_conta_sem_numero(row):
    base = "|".join(
        texto(row.get(campo))
        for campo in ("pasta_banco", "layout", "banco_nome", "empresa_nome")
    )
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]
    return f"SEM-CONTA-{digest}"


def garantir_empresa(cursor, row):
    banco_nome = texto(row.get("banco_nome")) or texto(row.get("pasta_banco"))
    conta = texto(row.get("conta")) or normalizar_conta_sem_numero(row)
    empresa_nome = (
        texto(row.get("empresa_nome"))
        or f"SEM EMPRESA - {banco_nome or 'BANCO NAO IDENTIFICADO'} - {conta}"
    )
    cnpj = cnpj_para_db(
        texto(row.get("empresa_cnpj")),
        empresa_nome,
        banco_nome,
        conta,
    )
    cursor.execute(
        """
        INSERT INTO empresas (razao_social, nome_fantasia, cnpj)
        VALUES (%s, %s, %s)
        ON CONFLICT (cnpj) DO UPDATE
        SET razao_social = EXCLUDED.razao_social
        RETURNING id
        """,
        (empresa_nome, empresa_nome, cnpj),
    )
    return cursor.fetchone()[0]


def garantir_banco(cursor, row):
    banco_nome = texto(row.get("banco_nome")) or texto(row.get("pasta_banco")) or "BANCO NAO IDENTIFICADO"
    banco_codigo = texto(row.get("banco_codigo")) or None
    cursor.execute(
        """
        INSERT INTO bancos (codigo_banco, nome)
        VALUES (%s, %s)
        ON CONFLICT (nome) DO UPDATE
        SET codigo_banco = COALESCE(EXCLUDED.codigo_banco, bancos.codigo_banco)
        RETURNING id
        """,
        (banco_codigo, banco_nome),
    )
    return cursor.fetchone()[0]


def garantir_conta(cursor, empresa_id, banco_id, row):
    agencia = texto(row.get("agencia"))
    conta = texto(row.get("conta")) or normalizar_conta_sem_numero(row)
    digito = texto(row.get("digito"))
    cursor.execute(
        """
        SELECT id
        FROM contas_bancarias
        WHERE empresa_id = %s
          AND banco_id = %s
          AND agencia = %s
          AND conta = %s
          AND digito = %s
        """,
        (empresa_id, banco_id, agencia, conta, digito),
    )
    existente = cursor.fetchone()
    if existente:
        return existente[0]

    descricao = (
        "Conta importada de PDF deduplicado"
        f" - {texto(row.get('layout')) or 'layout nao identificado'}"
    )
    cursor.execute(
        """
        INSERT INTO contas_bancarias (
            empresa_id, banco_id, agencia, conta, digito, descricao
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (empresa_id, banco_id, agencia, conta, digito, descricao),
    )
    return cursor.fetchone()[0]


def transacao_existe(cursor, conta_bancaria_id, identificador):
    cursor.execute(
        """
        SELECT id
        FROM transacoes_bancarias
        WHERE conta_bancaria_id = %s
          AND identificador_transacao = %s
        LIMIT 1
        """,
        (conta_bancaria_id, identificador),
    )
    return cursor.fetchone() is not None


def importar(caminho: Path, dry_run=False):
    transacoes = []
    fora_periodo = 0
    with caminho.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp, delimiter=";")
        for row in reader:
            row.pop(None, None)
            if texto(row.get("tipo_movimento")) not in {"ENTRADA", "SAIDA"}:
                continue
            if not texto(row.get("data")):
                continue
            data = datetime.strptime(row["data"], "%d/%m/%Y").date()
            if not 2024 <= data.year <= 2026:
                fora_periodo += 1
                continue
            row["valor"] = str(Decimal(texto(row.get("valor")) or "0"))
            transacoes.append(row)

    periodo_inicio, periodo_fim = detectar_periodo(transacoes, "data")
    entradas = sum(
        Decimal(row["valor"])
        for row in transacoes
        if row["tipo_movimento"] == "ENTRADA"
    )
    saidas = sum(
        Decimal(row["valor"])
        for row in transacoes
        if row["tipo_movimento"] == "SAIDA"
    )

    if dry_run:
        return {
            "arquivo": str(caminho),
            "registros_validos": len(transacoes),
            "fora_periodo_2024_2026": fora_periodo,
            "periodo_inicio": periodo_inicio,
            "periodo_fim": periodo_fim,
            "entradas": entradas,
            "saidas": saidas,
        }

    hash_arquivo = calcular_hash(caminho)
    inseridos = 0
    existentes = 0
    cache_empresas = {}
    cache_bancos = {}
    cache_contas = {}

    with conectar_banco() as conn:
        with conn.cursor() as cursor:
            arquivo_id = registrar_arquivo_historico(
                cursor,
                caminho=caminho,
                tipo_arquivo="CSV",
                origem="BANCO",
                hash_arquivo=hash_arquivo,
                quantidade=len(transacoes),
                periodo_inicio=periodo_inicio,
                periodo_fim=periodo_fim,
                metadados={
                    "fonte": "PDFs deduplicados da pasta oficial",
                    "pasta_origem": os.getenv("BANKSYNC_PASTA_BANCO", "pasta oficial configurada localmente"),
                    "deduplicado": True,
                },
            )

            for row in transacoes:
                empresa_key = (
                    texto(row.get("empresa_cnpj")),
                    texto(row.get("empresa_nome")),
                    texto(row.get("banco_nome")),
                    texto(row.get("conta")),
                )
                if empresa_key not in cache_empresas:
                    cache_empresas[empresa_key] = garantir_empresa(cursor, row)
                empresa_id = cache_empresas[empresa_key]

                banco_key = (texto(row.get("banco_nome")), texto(row.get("banco_codigo")))
                if banco_key not in cache_bancos:
                    cache_bancos[banco_key] = garantir_banco(cursor, row)
                banco_id = cache_bancos[banco_key]

                conta_key = (
                    empresa_id,
                    banco_id,
                    texto(row.get("agencia")),
                    texto(row.get("conta")) or normalizar_conta_sem_numero(row),
                    texto(row.get("digito")),
                )
                if conta_key not in cache_contas:
                    cache_contas[conta_key] = garantir_conta(cursor, empresa_id, banco_id, row)
                conta_bancaria_id = cache_contas[conta_key]

                identificador = f"BANCO-PDF-DEDUP:{row['dedup_key'][:32]}"
                if transacao_existe(cursor, conta_bancaria_id, identificador):
                    existentes += 1
                    continue

                cursor.execute(
                    """
                    INSERT INTO transacoes_bancarias (
                        arquivo_id,
                        conta_bancaria_id,
                        data_movimento,
                        tipo_movimento,
                        valor,
                        descricao,
                        documento,
                        identificador_transacao
                    )
                    VALUES (%s, %s, TO_DATE(%s, 'DD/MM/YYYY'), %s, %s, %s, %s, %s)
                    """,
                    (
                        arquivo_id,
                        conta_bancaria_id,
                        row["data"],
                        row["tipo_movimento"],
                        Decimal(row["valor"]),
                        texto(row.get("descricao")) or None,
                        texto(row.get("documento")) or None,
                        identificador,
                    ),
                )
                inseridos += 1
        conn.commit()

    return {
        "arquivo": str(caminho),
        "arquivo_id": arquivo_id,
        "registros_validos": len(transacoes),
        "fora_periodo_2024_2026": fora_periodo,
        "inseridos": inseridos,
        "existentes": existentes,
        "periodo_inicio": periodo_inicio,
        "periodo_fim": periodo_fim,
        "entradas": entradas,
        "saidas": saidas,
    }


def main():
    parser = ArgumentParser()
    parser.add_argument("--arquivo", type=Path, default=ARQUIVO_PADRAO)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    resultado = importar(args.arquivo, dry_run=args.dry_run)
    print(json.dumps(resultado, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
