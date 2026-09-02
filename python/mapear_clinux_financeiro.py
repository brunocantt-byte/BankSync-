from diagnosticar_clinux_db import carregar_config, conectar


TERMOS_TABELA = (
    "conta",
    "banco",
    "boleto",
    "cheque",
    "lanc",
    "finance",
    "receb",
    "pag",
    "fornec",
    "cliente",
    "caixa",
    "centro_custo",
    "custos",
    "fluxo",
    "mov",
)

TERMOS_COLUNA = (
    "data",
    "valor",
    "cnpj",
    "cpf",
    "documento",
    "descricao",
    "historico",
    "fornecedor",
    "favorecido",
    "cliente",
    "empresa",
    "banco",
    "conta",
    "status",
    "pago",
    "pagamento",
    "vencimento",
    "baixa",
)


def buscar_tabelas(cursor):
    cursor.execute(
        """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
              AND table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY table_schema, table_name;
        """
    )
    return cursor.fetchall()


def buscar_colunas(cursor, schema, tabela):
    cursor.execute(
        """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            ORDER BY ordinal_position;
        """,
        (schema, tabela),
    )
    return cursor.fetchall()


def contar_linhas(cursor, schema, tabela):
    cursor.execute(f'SELECT COUNT(*) FROM "{schema}"."{tabela}";')
    return cursor.fetchone()[0]


def relevante(nome, termos):
    texto = nome.lower()
    return any(termo in texto for termo in termos)


def main():
    config = carregar_config()
    label, conexao = conectar(config)
    print(f"Conexao OK: {label}")
    print()

    with conexao:
        with conexao.cursor() as cursor:
            tabelas = buscar_tabelas(cursor)
            candidatas = [
                (schema, tabela)
                for schema, tabela in tabelas
                if relevante(tabela, TERMOS_TABELA)
            ]

            for schema, tabela in candidatas:
                colunas = buscar_colunas(cursor, schema, tabela)
                colunas_relevantes = [
                    f"{nome}:{tipo}"
                    for nome, tipo in colunas
                    if relevante(nome, TERMOS_COLUNA)
                ]

                if not colunas_relevantes:
                    continue

                try:
                    total = contar_linhas(cursor, schema, tabela)
                except Exception:
                    total = "erro"

                print(f"{schema}.{tabela} | linhas={total}")
                print("  " + ", ".join(colunas_relevantes[:30]))


if __name__ == "__main__":
    main()
