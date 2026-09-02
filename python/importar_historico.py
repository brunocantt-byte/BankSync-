from __future__ import annotations

from argparse import ArgumentParser
import csv
import hashlib
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys

from base_historica import (
    BANCO_ENTRADA_DIR,
    EXTRACOES_DIR,
    SISTEMA_ENTRADA_DIR,
    arquivar_arquivo,
    calcular_hash,
    conectar_banco,
    detectar_periodo,
    garantir_pastas,
    registrar_arquivo_historico,
)
import importar_banco_pdf
import importar_ofx
import importar_sistema_xls


BUNDLED_PYTHON = Path(os.getenv("BANKSYNC_PYTHON_EXE", sys.executable))
EXTRATOR_PDF = Path(r"C:\ConciliaFinanceira\python\extrair_banco_pdf_csv.py")


def extrair_pdf_para_csv(caminho_pdf: Path, hash_arquivo: str) -> Path:
    saida = EXTRACOES_DIR / f"{hash_arquivo[:16]}_{caminho_pdf.stem}.csv"
    if saida.exists():
        return saida

    try:
        import pdfplumber  # noqa: F401
        from extrair_banco_pdf_csv import escrever_csv
        from leitores_pdf_banco import extrair_pdf_bancario

        extracao = extrair_pdf_bancario(caminho_pdf)
        escrever_csv(
            extracao.transacoes,
            saida,
            {
                "banco_nome": extracao.banco_nome,
                "banco_codigo": extracao.banco_codigo or "",
                "layout": extracao.layout,
                "empresa_nome": extracao.empresa_nome or "",
                "empresa_cnpj": extracao.empresa_cnpj or "",
                "agencia": extracao.agencia or "",
                "conta": extracao.conta or "",
                "digito": extracao.digito or "",
            },
        )
        return saida
    except ModuleNotFoundError:
        if not BUNDLED_PYTHON.exists():
            raise RuntimeError(
                "pdfplumber nao esta instalado no ambiente do projeto e "
                "o Python auxiliar nao foi encontrado."
            )

        subprocess.run(
            [
                str(BUNDLED_PYTHON),
                str(EXTRATOR_PDF),
                "--entrada",
                str(caminho_pdf),
                "--saida",
                str(saida),
            ],
            check=True,
        )
        return saida


def ler_transacoes_banco_csv(caminho: Path):
    transacoes = []
    metadados = {}
    caminho_metadados = caminho.with_suffix(".json")

    if caminho_metadados.exists():
        with caminho_metadados.open("r", encoding="utf-8") as arquivo:
            metadados = json.load(arquivo).get("metadados", {})

    with caminho.open("r", encoding="utf-8", newline="") as arquivo:
        leitor = csv.DictReader(arquivo, delimiter=";")

        for linha in leitor:
            if not metadados:
                metadados = {
                    "banco_nome": linha.get("banco_nome") or importar_banco_pdf.BANCO_NOME,
                    "banco_codigo": linha.get("banco_codigo") or None,
                    "layout": linha.get("layout") or "CSV_LEGADO",
                    "empresa_nome": linha.get("empresa_nome") or importar_banco_pdf.RAZAO_SOCIAL,
                    "empresa_cnpj": linha.get("empresa_cnpj") or importar_banco_pdf.CNPJ_EMPRESA,
                    "agencia": linha.get("agencia") or importar_banco_pdf.AGENCIA,
                    "conta": linha.get("conta") or importar_banco_pdf.CONTA,
                    "digito": linha.get("digito") or importar_banco_pdf.DIGITO,
                }

            transacoes.append(
                {
                    "data": linha["data"],
                    "tipo_movimento": linha["tipo_movimento"],
                    "valor": Decimal(linha["valor"]),
                    "descricao": linha["descricao"] or None,
                    "documento": linha["documento"] or None,
                    "pagina": int(linha["pagina"]),
                }
            )

    if not metadados:
        metadados = {
            "banco_nome": importar_banco_pdf.BANCO_NOME,
            "banco_codigo": None,
            "layout": "CSV_LEGADO",
            "empresa_nome": importar_banco_pdf.RAZAO_SOCIAL,
            "empresa_cnpj": importar_banco_pdf.CNPJ_EMPRESA,
            "agencia": importar_banco_pdf.AGENCIA,
            "conta": importar_banco_pdf.CONTA,
            "digito": importar_banco_pdf.DIGITO,
        }

    return transacoes, metadados


def cnpj_para_db(cnpj, empresa_nome, banco_nome, conta):
    digitos = "".join(caractere for caractere in (cnpj or "") if caractere.isdigit())
    if len(digitos) == 14:
        return (
            f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/"
            f"{digitos[8:12]}-{digitos[12:]}"
        )

    chave = "|".join(
        parte
        for parte in (empresa_nome, banco_nome, conta)
        if parte
    )
    digest = hashlib.sha1(chave.encode("utf-8")).hexdigest()[:11]
    return f"SEM-CNPJ:{digest}"


def garantir_empresa_bancaria(cursor, metadados):
    empresa_nome = metadados.get("empresa_nome") or importar_banco_pdf.RAZAO_SOCIAL
    cnpj = cnpj_para_db(
        metadados.get("empresa_cnpj"),
        empresa_nome,
        metadados.get("banco_nome"),
        metadados.get("conta"),
    )

    cursor.execute(
        """
            INSERT INTO empresas (
                razao_social,
                nome_fantasia,
                cnpj
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (cnpj) DO UPDATE
            SET razao_social = EXCLUDED.razao_social
            RETURNING id;
        """,
        (
            empresa_nome,
            empresa_nome,
            cnpj,
        ),
    )

    return cursor.fetchone()[0]


def garantir_banco_generico(cursor, metadados):
    banco_nome = metadados.get("banco_nome") or importar_banco_pdf.BANCO_NOME
    cursor.execute(
        """
            INSERT INTO bancos (
                codigo_banco,
                nome
            )
            VALUES (%s, %s)
            ON CONFLICT (nome) DO UPDATE
            SET codigo_banco = COALESCE(EXCLUDED.codigo_banco, bancos.codigo_banco)
            RETURNING id;
        """,
        (
            metadados.get("banco_codigo"),
            banco_nome,
        ),
    )

    return cursor.fetchone()[0]


def garantir_conta_generica(cursor, empresa_id, banco_id, metadados, hash_arquivo):
    conta = metadados.get("conta") or f"SEM-CONTA-{hash_arquivo[:12]}"
    agencia = metadados.get("agencia") or ""
    digito = metadados.get("digito") or ""

    cursor.execute(
        """
            SELECT id
            FROM contas_bancarias
            WHERE empresa_id = %s
              AND banco_id = %s
              AND agencia = %s
              AND conta = %s
              AND digito = %s;
        """,
        (
            empresa_id,
            banco_id,
            agencia,
            conta,
            digito,
        ),
    )
    conta_existente = cursor.fetchone()
    if conta_existente:
        return conta_existente[0]

    cursor.execute(
        """
            INSERT INTO contas_bancarias (
                empresa_id,
                banco_id,
                agencia,
                conta,
                digito,
                descricao
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id;
        """,
        (
            empresa_id,
            banco_id,
            agencia,
            conta,
            digito,
            f"Conta importada de PDF/CSV - {metadados.get('layout') or 'layout nao identificado'}",
        ),
    )

    return cursor.fetchone()[0]


def importar_banco(caminho: Path):
    hash_arquivo = calcular_hash(caminho)

    if caminho.suffix.lower() == ".pdf":
        csv_extraido = extrair_pdf_para_csv(caminho, hash_arquivo)
        transacoes, metadados_banco = ler_transacoes_banco_csv(csv_extraido)
        tipo_arquivo = "PDF"
    elif caminho.suffix.lower() == ".csv":
        transacoes, metadados_banco = ler_transacoes_banco_csv(caminho)
        tipo_arquivo = "CSV"
    elif caminho.suffix.lower() == ".ofx":
        return importar_banco_ofx(caminho)
    else:
        raise ValueError(f"Formato de banco ainda nao suportado: {caminho.suffix}")

    periodo_inicio, periodo_fim = detectar_periodo(transacoes, "data")

    if metadados_banco.get("layout") == "CLINUX_EXTRATO_BANCO":
        return {
            "arquivo": str(caminho),
            "origem": "BANCO",
            "arquivo_id": None,
            "periodo_inicio": periodo_inicio,
            "periodo_fim": periodo_fim,
            "registros": 0,
            "inseridos": 0,
            "existentes": 0,
            "ignorados": 1,
            "motivo": (
                "PDF identificado como relatorio do Clinux/Genesis, "
                "nao como extrato oficial do banco."
            ),
        }

    if not transacoes:
        return {
            "arquivo": str(caminho),
            "origem": "BANCO",
            "arquivo_id": None,
            "periodo_inicio": periodo_inicio,
            "periodo_fim": periodo_fim,
            "registros": 0,
            "inseridos": 0,
            "existentes": 0,
            "ignorados": 1,
            "motivo": (
                "Nenhuma transacao bancaria foi extraida. "
                f"Layout: {metadados_banco.get('layout')}"
            ),
        }

    caminho_arquivado = arquivar_arquivo(caminho, "banco", hash_arquivo, periodo_inicio)

    inseridas = 0
    existentes = 0

    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            empresa_id = garantir_empresa_bancaria(cursor, metadados_banco)
            banco_id = garantir_banco_generico(cursor, metadados_banco)
            conta_bancaria_id = garantir_conta_generica(
                cursor,
                empresa_id,
                banco_id,
                metadados_banco,
                hash_arquivo,
            )
            arquivo_id = registrar_arquivo_historico(
                cursor,
                caminho=caminho,
                tipo_arquivo=tipo_arquivo,
                origem="BANCO",
                hash_arquivo=hash_arquivo,
                quantidade=len(transacoes),
                empresa_id=empresa_id,
                conta_bancaria_id=conta_bancaria_id,
                periodo_inicio=periodo_inicio,
                periodo_fim=periodo_fim,
                caminho_arquivado=caminho_arquivado,
                metadados={
                    "banco": metadados_banco.get("banco_nome"),
                    "codigo_banco": metadados_banco.get("banco_codigo"),
                    "layout": metadados_banco.get("layout"),
                    "empresa_nome": metadados_banco.get("empresa_nome"),
                    "empresa_cnpj": metadados_banco.get("empresa_cnpj"),
                    "agencia": metadados_banco.get("agencia"),
                    "conta": metadados_banco.get("conta"),
                    "digito": metadados_banco.get("digito"),
                },
            )

            for indice, transacao in enumerate(transacoes, start=1):
                identificador = f"BANCO-{tipo_arquivo}:{hash_arquivo[:16]}:{indice:04d}"

                if importar_banco_pdf.transacao_existe(
                    cursor,
                    conta_bancaria_id,
                    identificador,
                ):
                    existentes += 1
                    continue

                importar_banco_pdf.inserir_transacao(
                    cursor,
                    transacao,
                    arquivo_id,
                    conta_bancaria_id,
                    identificador,
                )
                inseridas += 1

        conexao.commit()

    return {
        "arquivo": str(caminho),
        "origem": "BANCO",
        "arquivo_id": arquivo_id,
        "periodo_inicio": periodo_inicio,
        "periodo_fim": periodo_fim,
        "registros": len(transacoes),
        "inseridos": inseridas,
        "existentes": existentes,
    }


def buscar_empresa_da_conta(cursor, conta_bancaria_id):
    cursor.execute(
        """
            SELECT empresa_id
            FROM contas_bancarias
            WHERE id = %s;
        """,
        (conta_bancaria_id,),
    )
    conta = cursor.fetchone()

    if not conta:
        raise ValueError(f"Conta bancaria nao encontrada: {conta_bancaria_id}")

    return conta[0]


def transacao_ofx_existe(cursor, conta_bancaria_id, identificador):
    cursor.execute(
        """
            SELECT id
            FROM transacoes_bancarias
            WHERE conta_bancaria_id = %s
              AND identificador_transacao = %s
            LIMIT 1;
        """,
        (conta_bancaria_id, identificador),
    )

    return cursor.fetchone() is not None


def inserir_transacao_ofx(cursor, transacao, arquivo_id, conta_bancaria_id):
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
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
        """,
        (
            arquivo_id,
            conta_bancaria_id,
            transacao["data"],
            transacao["tipo_movimento"],
            transacao["valor"],
            transacao["descricao"],
            transacao["documento"],
            transacao["fitid"],
        ),
    )


def importar_banco_ofx(caminho: Path):
    hash_arquivo = calcular_hash(caminho)
    conteudo = importar_ofx.ler_arquivo(caminho)
    blocos = importar_ofx.extrair_transacoes(conteudo)
    transacoes = []
    erros = 0

    for bloco in blocos:
        transacao = importar_ofx.processar_transacao(bloco)

        if transacao["tipo_registro"] != "MOVIMENTACAO":
            continue

        if (
            not transacao["fitid"]
            or transacao["tipo_movimento"] not in ("ENTRADA", "SAIDA")
            or transacao["data"] is None
        ):
            erros += 1
            continue

        transacoes.append(transacao)

    periodo_inicio, periodo_fim = detectar_periodo(transacoes, "data")
    caminho_arquivado = arquivar_arquivo(caminho, "banco", hash_arquivo, periodo_inicio)
    conta_bancaria_id = importar_ofx.CONTA_BANCARIA_ID
    inseridas = 0
    existentes = 0

    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            empresa_id = buscar_empresa_da_conta(cursor, conta_bancaria_id)
            arquivo_id = registrar_arquivo_historico(
                cursor,
                caminho=caminho,
                tipo_arquivo="OFX",
                origem="BANCO",
                hash_arquivo=hash_arquivo,
                quantidade=len(transacoes),
                empresa_id=empresa_id,
                conta_bancaria_id=conta_bancaria_id,
                periodo_inicio=periodo_inicio,
                periodo_fim=periodo_fim,
                caminho_arquivado=caminho_arquivado,
                metadados={
                    "layout": "OFX",
                    "conta_bancaria_id": conta_bancaria_id,
                    "registros_ignorados": erros,
                },
            )

            for transacao in transacoes:
                if transacao_ofx_existe(
                    cursor,
                    conta_bancaria_id,
                    transacao["fitid"],
                ):
                    existentes += 1
                    continue

                inserir_transacao_ofx(
                    cursor,
                    transacao,
                    arquivo_id,
                    conta_bancaria_id,
                )
                inseridas += 1

        conexao.commit()

    return {
        "arquivo": str(caminho),
        "origem": "BANCO",
        "arquivo_id": arquivo_id,
        "periodo_inicio": periodo_inicio,
        "periodo_fim": periodo_fim,
        "registros": len(transacoes),
        "inseridos": inseridas,
        "existentes": existentes,
        "ignorados": erros,
    }


def importar_sistema(caminho: Path):
    hash_arquivo = calcular_hash(caminho)
    importar_sistema_xls.SISTEMA_ORIGEM = caminho.name
    lancamentos = list(importar_sistema_xls.ler_lancamentos(caminho, hash_arquivo))
    periodo_inicio, periodo_fim = detectar_periodo(lancamentos, "data_pagamento")
    caminho_arquivado = arquivar_arquivo(caminho, "sistema", hash_arquivo, periodo_inicio)

    inseridos = 0
    existentes = 0

    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            empresa_id = importar_sistema_xls.buscar_empresa_id(cursor)
            arquivo_id = registrar_arquivo_historico(
                cursor,
                caminho=caminho,
                tipo_arquivo=caminho.suffix.upper().lstrip("."),
                origem="SISTEMA",
                hash_arquivo=hash_arquivo,
                quantidade=len(lancamentos),
                empresa_id=empresa_id,
                periodo_inicio=periodo_inicio,
                periodo_fim=periodo_fim,
                caminho_arquivado=caminho_arquivado,
                metadados={
                    "sistema_origem": caminho.name,
                },
            )

            for lancamento in lancamentos:
                if importar_sistema_xls.lancamento_existe(
                    cursor,
                    empresa_id,
                    lancamento["identificador_externo"],
                ):
                    existentes += 1
                    continue

                importar_sistema_xls.inserir_lancamento(
                    cursor,
                    empresa_id,
                    lancamento,
                )
                inseridos += 1

        conexao.commit()

    return {
        "arquivo": str(caminho),
        "origem": "SISTEMA",
        "arquivo_id": arquivo_id,
        "periodo_inicio": periodo_inicio,
        "periodo_fim": periodo_fim,
        "registros": len(lancamentos),
        "inseridos": inseridos,
        "existentes": existentes,
    }


def arquivos_da_pasta(pasta: Path, extensoes: tuple[str, ...]):
    if not pasta.exists():
        return []

    return sorted(
        caminho
        for caminho in pasta.iterdir()
        if caminho.is_file() and caminho.suffix.lower() in extensoes
    )


def imprimir_resultado(resultado):
    print(
        f"{resultado['origem']}: {resultado['arquivo']} | "
        f"periodo {resultado['periodo_inicio']} a {resultado['periodo_fim']} | "
        f"registros {resultado['registros']} | "
        f"inseridos {resultado['inseridos']} | "
        f"ja existentes {resultado['existentes']}"
    )
    if resultado.get("motivo"):
        print(f"  motivo: {resultado['motivo']}")


def main():
    parser = ArgumentParser(
        description="Importa arquivos para a base historica permanente."
    )
    parser.add_argument("--banco", action="append", default=[])
    parser.add_argument("--sistema", action="append", default=[])
    parser.add_argument("--todos", action="store_true")
    args = parser.parse_args()

    garantir_pastas()

    bancos = [Path(item) for item in args.banco]
    sistemas = [Path(item) for item in args.sistema]

    if args.todos or (not bancos and not sistemas):
        bancos.extend(arquivos_da_pasta(BANCO_ENTRADA_DIR, (".pdf", ".csv", ".ofx")))
        sistemas.extend(arquivos_da_pasta(SISTEMA_ENTRADA_DIR, (".xls", ".xlsx")))

    if not bancos and not sistemas:
        print("Nenhum arquivo encontrado para importar.")
        print(f"Banco: {BANCO_ENTRADA_DIR}")
        print(f"Sistema: {SISTEMA_ENTRADA_DIR}")
        return

    for caminho in bancos:
        imprimir_resultado(importar_banco(caminho))

    for caminho in sistemas:
        imprimir_resultado(importar_sistema(caminho))


if __name__ == "__main__":
    try:
        main()
    except Exception as erro:
        print(f"Erro na importacao historica: {erro}")
        sys.exit(1)


