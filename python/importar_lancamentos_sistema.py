from pathlib import Path
import csv
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation

import psycopg
from dotenv import load_dotenv


load_dotenv()

PASTA_DADOS = Path(r"C:\ConciliaFinanceira\dados")
ARQUIVO_PADRAO = PASTA_DADOS / "lancamentos_sistema.csv"

CAMPOS = [
    "empresa_id",
    "data_lancamento",
    "data_vencimento",
    "data_pagamento",
    "tipo_movimento",
    "valor",
    "fornecedor_cliente",
    "documento",
    "cnpj_cpf",
    "descricao",
    "categoria",
    "centro_custo",
    "sistema_origem",
    "identificador_externo",
    "status",
]


def conectar_banco():
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def limpar_texto(valor):
    if valor is None:
        return None

    valor = str(valor).strip()
    return valor or None


def converter_data(valor):
    valor = limpar_texto(valor)

    if not valor:
        return None

    formatos = (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
    )

    for formato in formatos:
        try:
            return datetime.strptime(valor, formato).date()
        except ValueError:
            continue

    raise ValueError(f"Data invalida: {valor}")


def converter_valor(valor):
    valor = limpar_texto(valor)

    if not valor:
        raise ValueError("Valor obrigatorio ausente.")

    normalizado = (
        valor
        .replace("R$", "")
        .replace(".", "")
        .replace(",", ".")
        .strip()
    )

    try:
        return abs(Decimal(normalizado))
    except InvalidOperation as erro:
        raise ValueError(f"Valor invalido: {valor}") from erro


def normalizar_tipo(valor):
    valor = limpar_texto(valor)

    if not valor:
        raise ValueError("tipo_movimento obrigatorio ausente.")

    tipo = valor.upper()

    if tipo in ("ENTRADA", "RECEITA", "CREDITO", "CREDIT"):
        return "ENTRADA"

    if tipo in ("SAIDA", "DESPESA", "DEBITO", "DEBIT"):
        return "SAIDA"

    raise ValueError(f"tipo_movimento invalido: {valor}")


def normalizar_status(valor):
    status = (limpar_texto(valor) or "ABERTO").upper()

    if status not in ("ABERTO", "CONCILIADO", "PENDENTE", "CANCELADO"):
        raise ValueError(f"status invalido: {valor}")

    return status


def detectar_dialeto(caminho):
    amostra = caminho.read_text(encoding="utf-8-sig")[:4096]

    try:
        return csv.Sniffer().sniff(amostra, delimiters=",;")
    except csv.Error:
        return csv.excel


def ler_lancamentos(caminho):
    dialeto = detectar_dialeto(caminho)

    with caminho.open("r", encoding="utf-8-sig", newline="") as arquivo:
        leitor = csv.DictReader(arquivo, dialect=dialeto)

        if not leitor.fieldnames:
            raise ValueError("CSV sem cabecalho.")

        campos_arquivo = {campo.strip() for campo in leitor.fieldnames}
        obrigatorios = {"empresa_id", "tipo_movimento", "valor"}
        ausentes = obrigatorios - campos_arquivo

        if ausentes:
            raise ValueError(
                "Campos obrigatorios ausentes: "
                + ", ".join(sorted(ausentes))
            )

        for linha_numero, linha in enumerate(leitor, start=2):
            if not any(limpar_texto(valor) for valor in linha.values()):
                continue

            yield linha_numero, normalizar_linha(linha)


def normalizar_linha(linha):
    empresa_id = limpar_texto(linha.get("empresa_id"))

    if not empresa_id:
        raise ValueError("empresa_id obrigatorio ausente.")

    lancamento = {
        "empresa_id": int(empresa_id),
        "data_lancamento": converter_data(linha.get("data_lancamento")),
        "data_vencimento": converter_data(linha.get("data_vencimento")),
        "data_pagamento": converter_data(linha.get("data_pagamento")),
        "tipo_movimento": normalizar_tipo(linha.get("tipo_movimento")),
        "valor": converter_valor(linha.get("valor")),
        "fornecedor_cliente": limpar_texto(linha.get("fornecedor_cliente")),
        "documento": limpar_texto(linha.get("documento")),
        "cnpj_cpf": limpar_texto(linha.get("cnpj_cpf")),
        "descricao": limpar_texto(linha.get("descricao")),
        "categoria": limpar_texto(linha.get("categoria")),
        "centro_custo": limpar_texto(linha.get("centro_custo")),
        "sistema_origem": limpar_texto(linha.get("sistema_origem")),
        "identificador_externo": limpar_texto(linha.get("identificador_externo")),
        "status": normalizar_status(linha.get("status")),
    }

    if not lancamento["data_lancamento"] and not lancamento["data_pagamento"]:
        raise ValueError(
            "Informe data_lancamento ou data_pagamento."
        )

    return lancamento


def lancamento_existe(cursor, lancamento):
    if lancamento["identificador_externo"]:
        cursor.execute(
            """
                SELECT id
                FROM lancamentos_sistema
                WHERE empresa_id = %s
                  AND identificador_externo = %s
                LIMIT 1;
            """,
            (
                lancamento["empresa_id"],
                lancamento["identificador_externo"],
            ),
        )

        return cursor.fetchone() is not None

    cursor.execute(
        """
            SELECT id
            FROM lancamentos_sistema
            WHERE empresa_id = %s
              AND tipo_movimento = %s
              AND valor = %s
              AND COALESCE(documento, '') = COALESCE(%s, '')
              AND COALESCE(data_pagamento, data_lancamento) = COALESCE(%s, %s)
            LIMIT 1;
        """,
        (
            lancamento["empresa_id"],
            lancamento["tipo_movimento"],
            lancamento["valor"],
            lancamento["documento"],
            lancamento["data_pagamento"],
            lancamento["data_lancamento"],
        ),
    )

    return cursor.fetchone() is not None


def inserir_lancamento(cursor, lancamento):
    cursor.execute(
        """
            INSERT INTO lancamentos_sistema (
                empresa_id,
                data_lancamento,
                data_vencimento,
                data_pagamento,
                tipo_movimento,
                valor,
                fornecedor_cliente,
                documento,
                cnpj_cpf,
                descricao,
                categoria,
                centro_custo,
                sistema_origem,
                identificador_externo,
                status
            )
            VALUES (
                %(empresa_id)s,
                %(data_lancamento)s,
                %(data_vencimento)s,
                %(data_pagamento)s,
                %(tipo_movimento)s,
                %(valor)s,
                %(fornecedor_cliente)s,
                %(documento)s,
                %(cnpj_cpf)s,
                %(descricao)s,
                %(categoria)s,
                %(centro_custo)s,
                %(sistema_origem)s,
                %(identificador_externo)s,
                %(status)s
            );
        """,
        lancamento,
    )


def importar(caminho):
    inseridos = 0
    existentes = 0
    erros = 0

    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            for linha_numero, lancamento in ler_lancamentos(caminho):
                try:
                    if lancamento_existe(cursor, lancamento):
                        existentes += 1
                        continue

                    inserir_lancamento(cursor, lancamento)
                    inseridos += 1

                except Exception as erro:
                    conexao.rollback()
                    erros += 1
                    print(f"Linha {linha_numero}: erro: {erro}")
                else:
                    conexao.commit()

    return inseridos, existentes, erros


def main():
    caminho = ARQUIVO_PADRAO

    print("Importando lancamentos do sistema...")
    print(f"Arquivo esperado: {caminho}")

    if not caminho.exists():
        print()
        print("Arquivo nao encontrado.")
        print(
            "Preencha o modelo em "
            r"C:\ConciliaFinanceira\dados\modelo_lancamentos_sistema.csv"
        )
        print(
            "Depois salve uma copia como "
            r"C:\ConciliaFinanceira\dados\lancamentos_sistema.csv"
        )
        return

    inseridos, existentes, erros = importar(caminho)

    print()
    print("=" * 55)
    print("RESULTADO DA IMPORTACAO")
    print("=" * 55)
    print(f"Inseridos: {inseridos}")
    print(f"Ja existentes: {existentes}")
    print(f"Com erro: {erros}")
    print("=" * 55)


if __name__ == "__main__":
    main()
