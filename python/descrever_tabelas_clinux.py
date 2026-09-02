from diagnosticar_clinux_db import carregar_config, conectar


TABELAS = (
    "lancamentos",
    "pagamentos",
    "fornecedores",
    "contas",
    "bancos",
    "centro_custos",
    "lancamentos_formas",
    "lancamentos_extratos",
    "bancos_transfere",
)


def main():
    config = carregar_config()
    label, conexao = conectar(config)
    print(f"Conexao OK: {label}")

    with conexao:
        with conexao.cursor() as cursor:
            for tabela in TABELAS:
                cursor.execute(
                    """
                        SELECT column_name, data_type, is_nullable
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = %s
                        ORDER BY ordinal_position;
                    """,
                    (tabela,),
                )
                colunas = cursor.fetchall()

                print()
                print(f"public.{tabela}")
                for nome, tipo, nulo in colunas:
                    print(f"- {nome}: {tipo} | null={nulo}")


if __name__ == "__main__":
    main()
