from diagnosticar_clinux_db import carregar_config, conectar


INICIO = "2024-01-01"
FIM = "2026-12-31"


def main():
    config = carregar_config()
    label, conexao = conectar(config)
    print(f"Conexao OK: {label}")

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                    SELECT
                        COALESCE(l.ds_tipo, '') AS tipo_lancamento,
                        COUNT(*) AS qtd,
                        SUM(COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0)) AS soma,
                        MIN(COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0)) AS menor,
                        MAX(COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0)) AS maior,
                        COUNT(*) FILTER (
                            WHERE COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0) < 0
                        ) AS negativos
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    WHERE p.dt_realizacao BETWEEN %s AND %s
                      AND COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0) <> 0
                    GROUP BY l.ds_tipo
                    ORDER BY soma DESC NULLS LAST;
                """,
                (INICIO, FIM),
            )
            print("Tipos originais - todas as unidades:")
            for linha in cursor.fetchall():
                print(" | ".join(str(item) for item in linha))

            for tabela in ("contas_grupos", "contas_fluxos", "contas_resultados"):
                cursor.execute(
                    """
                        SELECT column_name, data_type
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name = %s
                        ORDER BY ordinal_position;
                    """,
                    (tabela,),
                )
                print()
                print(f"Colunas {tabela}:")
                colunas = cursor.fetchall()
                print(", ".join(f"{nome}:{tipo}" for nome, tipo in colunas))

                if colunas:
                    cursor.execute(f'SELECT * FROM public."{tabela}" ORDER BY 1 LIMIT 40;')
                    print(f"Amostra {tabela}:")
                    for linha in cursor.fetchall():
                        print(" | ".join("" if item is None else str(item) for item in linha))

            cursor.execute(
                """
                    SELECT
                        COALESCE(cg.ds_grupo, 'SEM GRUPO') AS grupo,
                        COALESCE(c.ds_conta, 'SEM CONTA') AS conta,
                        COALESCE(l.ds_tipo, '') AS tipo,
                        COUNT(*) AS qtd,
                        SUM(COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0)) AS total
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    LEFT JOIN contas c ON c.cd_conta = l.cd_conta
                    LEFT JOIN contas_grupos cg ON cg.cd_grupo = c.cd_grupo
                    WHERE p.dt_realizacao BETWEEN %s AND %s
                      AND COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0) <> 0
                    GROUP BY cg.ds_grupo, c.ds_conta, l.ds_tipo
                    ORDER BY total DESC NULLS LAST
                    LIMIT 120;
                """,
                (INICIO, FIM),
            )
            print()
            print("Maiores contas/grupos - todas as unidades:")
            for linha in cursor.fetchall():
                print(" | ".join(str(item) for item in linha))


if __name__ == "__main__":
    main()
