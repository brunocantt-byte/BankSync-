from pathlib import Path
import hashlib
import os
from decimal import Decimal

import pandas as pd
import psycopg
from dotenv import load_dotenv


load_dotenv()

ARQUIVO_XLS = Path(os.getenv("BANKSYNC_ARQUIVO_SISTEMA", r"C:\ConciliaFinanceira\entrada\sistema\SISTEMA.xls"))
CNPJ_EMPRESA = os.getenv("BANKSYNC_EMPRESA_CNPJ", "")
SISTEMA_ORIGEM = "SISTEMA.xls"


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


def limpar(valor):
    if pd.isna(valor):
        return None

    texto = str(valor).strip()
    return texto or None


def buscar_empresa_id(cursor):
    cursor.execute(
        """
            SELECT id
            FROM empresas
            WHERE cnpj = %s;
        """,
        (CNPJ_EMPRESA,),
    )

    empresa = cursor.fetchone()

    if not empresa:
        raise ValueError(
            "Empresa do arquivo bancario ainda nao foi importada."
        )

    return empresa[0]


def ler_lancamentos(caminho, hash_arquivo):
    df = pd.read_excel(caminho, sheet_name="SISTEMA")

    df = df.rename(
        columns={
            df.columns[0]: "data_realizacao",
            df.columns[1]: "valor_realizado",
            df.columns[2]: "nf_bruto",
            df.columns[3]: "banco",
            df.columns[4]: "forma_pagamento",
            df.columns[5]: "empresa_unidade",
            df.columns[6]: "centro_custo",
            df.columns[7]: "conta",
            df.columns[8]: "grupo",
            df.columns[9]: "favorecido",
            df.columns[10]: "descricao",
            df.columns[11]: "razao_social",
            df.columns[12]: "cnpj_cpf",
        }
    )

    for indice, linha in df.iterrows():
        valor_original = Decimal(str(linha["valor_realizado"]))

        if valor_original == 0:
            continue

        tipo_movimento = (
            "ENTRADA" if valor_original > 0 else "SAIDA"
        )

        yield {
            "data_lancamento": linha["data_realizacao"].date(),
            "data_pagamento": linha["data_realizacao"].date(),
            "tipo_movimento": tipo_movimento,
            "valor": abs(valor_original),
            "fornecedor_cliente": limpar(linha["favorecido"]),
            "documento": None,
            "cnpj_cpf": limpar(linha["cnpj_cpf"]),
            "descricao": limpar(linha["descricao"]),
            "categoria": limpar(linha["conta"]),
            "centro_custo": limpar(linha["centro_custo"]),
            "sistema_origem": SISTEMA_ORIGEM,
            "identificador_externo": (
                f"SISTEMA-XLS:{hash_arquivo[:16]}:{indice + 2:04d}"
            ),
            "status": "ABERTO",
        }


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
            VALUES (%s, %s, 'XLS', %s, %s, %s, 'PROCESSADO', CURRENT_TIMESTAMP)
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


def lancamento_existe(cursor, empresa_id, identificador):
    cursor.execute(
        """
            SELECT id
            FROM lancamentos_sistema
            WHERE empresa_id = %s
              AND identificador_externo = %s
            LIMIT 1;
        """,
        (
            empresa_id,
            identificador,
        ),
    )

    return cursor.fetchone() is not None


def inserir_lancamento(cursor, empresa_id, lancamento):
    dados = dict(lancamento)
    dados["empresa_id"] = empresa_id

    cursor.execute(
        """
            INSERT INTO lancamentos_sistema (
                empresa_id,
                data_lancamento,
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
        dados,
    )


def main():
    print("Importando XLS do sistema...")
    print(f"Arquivo: {ARQUIVO_XLS}")

    if not ARQUIVO_XLS.exists():
        print("Arquivo nao encontrado.")
        return

    hash_arquivo = calcular_hash(ARQUIVO_XLS)
    lancamentos = list(ler_lancamentos(ARQUIVO_XLS, hash_arquivo))

    total = sum(item["valor"] for item in lancamentos)

    print(f"Linhas validas: {len(lancamentos)}")
    print(f"Total: {total}")

    inseridos = 0
    existentes = 0

    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            empresa_id = buscar_empresa_id(cursor)
            arquivo_id = registrar_arquivo(
                cursor,
                ARQUIVO_XLS,
                hash_arquivo,
                len(lancamentos),
            )

            for lancamento in lancamentos:
                if lancamento_existe(
                    cursor,
                    empresa_id,
                    lancamento["identificador_externo"],
                ):
                    existentes += 1
                    continue

                inserir_lancamento(
                    cursor,
                    empresa_id,
                    lancamento,
                )
                inseridos += 1

        conexao.commit()

    print()
    print("=" * 55)
    print("RESULTADO DA IMPORTACAO")
    print("=" * 55)
    print(f"Empresa ID: {empresa_id}")
    print(f"Arquivo ID: {arquivo_id}")
    print(f"Inseridos: {inseridos}")
    print(f"Ja existentes: {existentes}")
    print("=" * 55)


if __name__ == "__main__":
    main()
