from pathlib import Path
import csv
import hashlib
import os
from decimal import Decimal

import psycopg
from dotenv import load_dotenv


load_dotenv()

ARQUIVO_PDF = Path(os.getenv("BANKSYNC_ARQUIVO_BANCO", r"C:\ConciliaFinanceira\entrada\banco\BANCO.pdf"))
ARQUIVO_CSV = Path(r"C:\ConciliaFinanceira\dados\banco_pdf_extraido.csv")

RAZAO_SOCIAL = os.getenv("BANKSYNC_EMPRESA_NOME", "EMPRESA NAO INFORMADA")
CNPJ_EMPRESA = os.getenv("BANKSYNC_EMPRESA_CNPJ", "")
BANCO_NOME = os.getenv("BANKSYNC_BANCO_NOME", "BANCO NAO INFORMADO")
AGENCIA = os.getenv("BANKSYNC_AGENCIA", "")
CONTA = os.getenv("BANKSYNC_CONTA", "")
DIGITO = os.getenv("BANKSYNC_CONTA_DIGITO", "")


def conectar_banco():
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def calcular_hash(caminho):
    sha256 = hashlib.sha256()

    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            sha256.update(bloco)

    return sha256.hexdigest()


def ler_transacoes_csv(caminho):
    with caminho.open("r", encoding="utf-8", newline="") as arquivo:
        leitor = csv.DictReader(arquivo, delimiter=";")

        for linha in leitor:
            yield {
                "data": linha["data"],
                "tipo_movimento": linha["tipo_movimento"],
                "valor": Decimal(linha["valor"]),
                "descricao": linha["descricao"] or None,
                "documento": linha["documento"] or None,
                "pagina": int(linha["pagina"]),
            }


def garantir_empresa(cursor):
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
            RAZAO_SOCIAL,
            RAZAO_SOCIAL,
            CNPJ_EMPRESA,
        ),
    )

    return cursor.fetchone()[0]


def garantir_banco(cursor):
    cursor.execute(
        """
            INSERT INTO bancos (
                codigo_banco,
                nome
            )
            VALUES (NULL, %s)
            ON CONFLICT (nome) DO UPDATE
            SET nome = EXCLUDED.nome
            RETURNING id;
        """,
        (BANCO_NOME,),
    )

    return cursor.fetchone()[0]


def garantir_conta(cursor, empresa_id, banco_id):
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
            AGENCIA,
            CONTA,
            DIGITO,
        ),
    )

    conta = cursor.fetchone()

    if conta:
        return conta[0]

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
            AGENCIA,
            CONTA,
            DIGITO,
            "Conta importada do PDF BANCO.pdf",
        ),
    )

    return cursor.fetchone()[0]


def registrar_arquivo(cursor, caminho, hash_arquivo, quantidade):
    cursor.execute(
        """
            INSERT INTO arquivos_importados (
                nome_arquivo,
                caminho_arquivo,
                tipo_arquivo,
                tamanho_bytes,
                hash_arquivo,
                quantidade_registros,
                status,
                processado_em
            )
            VALUES (%s, %s, 'PDF', %s, %s, %s, 'PROCESSADO', CURRENT_TIMESTAMP)
            ON CONFLICT (hash_arquivo) DO UPDATE
            SET quantidade_registros = EXCLUDED.quantidade_registros,
                status = 'PROCESSADO',
                processado_em = CURRENT_TIMESTAMP
            RETURNING id;
        """,
        (
            caminho.name,
            str(caminho),
            caminho.stat().st_size,
            hash_arquivo,
            quantidade,
        ),
    )

    return cursor.fetchone()[0]


def transacao_existe(cursor, conta_bancaria_id, identificador):
    cursor.execute(
        """
            SELECT id
            FROM transacoes_bancarias
            WHERE conta_bancaria_id = %s
              AND identificador_transacao = %s
            LIMIT 1;
        """,
        (
            conta_bancaria_id,
            identificador,
        ),
    )

    return cursor.fetchone() is not None


def inserir_transacao(cursor, transacao, arquivo_id, conta_bancaria_id, identificador):
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
            VALUES (
                %s,
                %s,
                TO_DATE(%s, 'DD/MM/YYYY'),
                %s,
                %s,
                %s,
                %s,
                %s
            );
        """,
        (
            arquivo_id,
            conta_bancaria_id,
            transacao["data"],
            transacao["tipo_movimento"],
            transacao["valor"],
            transacao["descricao"],
            transacao["documento"],
            identificador,
        ),
    )


def main():
    print("Importando PDF bancario...")
    print(f"Arquivo: {ARQUIVO_PDF}")

    if not ARQUIVO_PDF.exists():
        print("Arquivo nao encontrado.")
        return

    if not ARQUIVO_CSV.exists():
        print("CSV extraido nao encontrado.")
        print(
            "Execute primeiro: "
            r"python .\python\extrair_banco_pdf_csv.py"
        )
        return

    hash_arquivo = calcular_hash(ARQUIVO_PDF)
    transacoes = list(ler_transacoes_csv(ARQUIVO_CSV))

    entradas = sum(
        item["valor"]
        for item in transacoes
        if item["tipo_movimento"] == "ENTRADA"
    )

    saidas = sum(
        item["valor"]
        for item in transacoes
        if item["tipo_movimento"] == "SAIDA"
    )

    print(f"Transacoes extraidas: {len(transacoes)}")
    print(f"Entradas: {entradas}")
    print(f"Saidas: {saidas}")

    inseridas = 0
    existentes = 0

    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            empresa_id = garantir_empresa(cursor)
            banco_id = garantir_banco(cursor)
            conta_bancaria_id = garantir_conta(cursor, empresa_id, banco_id)
            arquivo_id = registrar_arquivo(
                cursor,
                ARQUIVO_PDF,
                hash_arquivo,
                len(transacoes),
            )

            for indice, transacao in enumerate(transacoes, start=1):
                identificador = (
                    f"BANCO-PDF:{hash_arquivo[:16]}:{indice:04d}"
                )

                if transacao_existe(
                    cursor,
                    conta_bancaria_id,
                    identificador,
                ):
                    existentes += 1
                    continue

                inserir_transacao(
                    cursor,
                    transacao,
                    arquivo_id,
                    conta_bancaria_id,
                    identificador,
                )
                inseridas += 1

        conexao.commit()

    print()
    print("=" * 55)
    print("RESULTADO DA IMPORTACAO")
    print("=" * 55)
    print(f"Empresa ID: {empresa_id}")
    print(f"Conta bancaria ID: {conta_bancaria_id}")
    print(f"Arquivo ID: {arquivo_id}")
    print(f"Inseridas: {inseridas}")
    print(f"Ja existentes: {existentes}")
    print("=" * 55)


if __name__ == "__main__":
    main()
