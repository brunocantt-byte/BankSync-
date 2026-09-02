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
                        p.ds_tipo,
                        COUNT(*),
                        MIN(p.dt_realizacao),
                        MAX(p.dt_realizacao),
                        SUM(COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0))
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    WHERE l.cd_empresa = 1
                      AND p.dt_realizacao IS NOT NULL
                    GROUP BY p.ds_tipo
                    ORDER BY p.ds_tipo;
                """
            )
            print("Tipos em pagamentos realizados:")
            for tipo, quantidade, inicio, fim, total in cursor.fetchall():
                print(f"- tipo={tipo} qtd={quantidade} periodo={inicio} a {fim} total={total:.2f}")

            cursor.execute(
                """
                    SELECT
                        DATE_TRUNC('month', p.dt_realizacao)::date AS mes,
                        p.ds_tipo,
                        COUNT(*),
                        SUM(COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0))
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    WHERE l.cd_empresa = 1
                      AND p.dt_realizacao >= DATE '2026-01-01'
                      AND p.dt_realizacao < DATE '2026-09-01'
                    GROUP BY mes, p.ds_tipo
                    ORDER BY mes, p.ds_tipo;
                """
            )
            print()
            print("Resumo mensal 2026:")
            for mes, tipo, quantidade, total in cursor.fetchall():
                print(f"- {mes} tipo={tipo} qtd={quantidade} total={total:.2f}")

            cursor.execute(
                """
                    SELECT
                        p.cd_pagamento,
                        p.dt_realizacao,
                        p.dt_vencimento,
                        p.ds_tipo,
                        COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0),
                        f.ds_fornecedor,
                        f.ds_cnpj,
                        l.ds_documento,
                        l.ds_historico,
                        c.ds_conta,
                        b.ds_banco
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    LEFT JOIN fornecedores f ON f.cd_fornecedor = l.cd_fornecedor
                    LEFT JOIN contas c ON c.cd_conta = l.cd_conta
                    LEFT JOIN bancos b ON b.cd_banco = p.cd_banco
                    WHERE l.cd_empresa = 1
                      AND p.dt_realizacao BETWEEN DATE '2026-06-01' AND DATE '2026-06-30'
                    ORDER BY p.dt_realizacao, p.cd_pagamento
                    LIMIT 12;
                """
            )
            print()
            print("Amostra financeira junho/2026:")
            for linha in cursor.fetchall():
                print(" | ".join("" if item is None else str(item) for item in linha))


if __name__ == "__main__":
    main()
