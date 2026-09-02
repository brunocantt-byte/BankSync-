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
                        COALESCE(b.ds_banco, 'SEM BANCO') AS banco,
                        COUNT(*) AS quantidade,
                        SUM(COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0)) AS total
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    LEFT JOIN bancos b ON b.cd_banco = p.cd_banco
                    WHERE l.cd_empresa = 1
                      AND p.dt_realizacao BETWEEN DATE '2026-06-01' AND DATE '2026-06-30'
                    GROUP BY COALESCE(b.ds_banco, 'SEM BANCO')
                    ORDER BY total DESC NULLS LAST;
                """
            )

            for banco, quantidade, total in cursor.fetchall():
                print(f"{banco} | qtd={quantidade} | total={total:.2f}")


if __name__ == "__main__":
    main()
