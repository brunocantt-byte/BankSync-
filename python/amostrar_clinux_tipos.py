from diagnosticar_clinux_db import carregar_config, conectar


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
                        COALESCE(c.ds_tipo, '') AS tipo_conta,
                        COALESCE(c.ds_conta, 'SEM CONTA') AS conta,
                        COUNT(*) AS quantidade,
                        SUM(COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0)) AS total
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    LEFT JOIN contas c ON c.cd_conta = l.cd_conta
                    WHERE l.cd_empresa = 1
                      AND p.dt_realizacao BETWEEN DATE '2024-01-01' AND DATE '2026-12-31'
                    GROUP BY l.ds_tipo, c.ds_tipo, c.ds_conta
                    ORDER BY tipo_lancamento, total DESC NULLS LAST
                    LIMIT 80;
                """
            )
            print("Resumo por tipo/conta:")
            for linha in cursor.fetchall():
                print(" | ".join("" if item is None else str(item) for item in linha))

            cursor.execute(
                """
                    SELECT DISTINCT COALESCE(l.ds_tipo, '') AS tipo_lancamento
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    WHERE l.cd_empresa = 1
                      AND p.dt_realizacao BETWEEN DATE '2024-01-01' AND DATE '2026-12-31'
                    ORDER BY tipo_lancamento;
                """
            )
            tipos = [linha[0] for linha in cursor.fetchall()]

            print()
            print("Amostras por tipo:")
            for tipo in tipos:
                cursor.execute(
                    """
                        SELECT
                            p.cd_pagamento,
                            l.ds_tipo,
                            c.ds_tipo,
                            p.dt_realizacao,
                            COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0),
                            COALESCE(f.ds_fornecedor, ''),
                            COALESCE(f.ds_cnpj, ''),
                            COALESCE(l.ds_historico, ''),
                            COALESCE(c.ds_conta, ''),
                            COALESCE(b.ds_banco, '')
                        FROM pagamentos p
                        JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                        LEFT JOIN fornecedores f ON f.cd_fornecedor = l.cd_fornecedor
                        LEFT JOIN contas c ON c.cd_conta = l.cd_conta
                        LEFT JOIN bancos b ON b.cd_banco = p.cd_banco
                        WHERE l.cd_empresa = 1
                          AND p.dt_realizacao BETWEEN DATE '2024-01-01' AND DATE '2026-12-31'
                          AND COALESCE(l.ds_tipo, '') = %s
                        ORDER BY p.dt_realizacao DESC, p.cd_pagamento DESC
                        LIMIT 5;
                    """,
                    (tipo,),
                )
                print(f"Tipo {tipo or '<vazio>'}:")
                for linha in cursor.fetchall():
                    print("  " + " | ".join(str(item) for item in linha))


if __name__ == "__main__":
    main()
