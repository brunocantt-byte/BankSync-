from diagnosticar_clinux_db import carregar_config, conectar as conectar_clinux


INICIO = "2024-01-01"
FIM = "2026-12-31"


def moeda(valor):
    return f"R$ {float(valor or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main():
    config = carregar_config()
    label, conexao = conectar_clinux(config)
    print(f"Conexao Clinux OK: {label}")

    with conexao:
        with conexao.cursor() as cursor:
            consultas = [
                (
                    "pagamentos_importaveis",
                    """
                        SELECT COUNT(*), SUM(COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0))
                        FROM pagamentos p
                        JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                        WHERE p.dt_realizacao BETWEEN %s AND %s
                          AND COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0) <> 0;
                    """,
                    (INICIO, FIM),
                ),
                (
                    "pagamentos_no_periodo_com_valor_zero",
                    """
                        SELECT COUNT(*), SUM(COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0))
                        FROM pagamentos p
                        JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                        WHERE p.dt_realizacao BETWEEN %s AND %s
                          AND COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0) = 0;
                    """,
                    (INICIO, FIM),
                ),
                (
                    "pagamentos_sem_data_realizada_com_vencimento_no_periodo",
                    """
                        SELECT COUNT(*), SUM(COALESCE(p.nr_pagamento, p.nr_previsto, 0))
                        FROM pagamentos p
                        JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                        WHERE p.dt_realizacao IS NULL
                          AND p.dt_vencimento BETWEEN %s AND %s
                          AND COALESCE(p.nr_pagamento, p.nr_previsto, 0) <> 0;
                    """,
                    (INICIO, FIM),
                ),
                (
                    "lancamentos_sem_pagamento_com_emissao_no_periodo",
                    """
                        SELECT COUNT(*), SUM(COALESCE(l.nr_nota_liquido, l.nr_nota_bruto, 0))
                        FROM lancamentos l
                        LEFT JOIN pagamentos p ON p.cd_lancamento = l.cd_lancamento
                        WHERE p.cd_pagamento IS NULL
                          AND l.dt_emissao BETWEEN %s AND %s
                          AND COALESCE(l.nr_nota_liquido, l.nr_nota_bruto, 0) <> 0;
                    """,
                    (INICIO, FIM),
                ),
                (
                    "transferencias_importaveis_geram_duas_pontas",
                    """
                        SELECT COUNT(*), SUM(COALESCE(bt.nr_valor, 0))
                        FROM bancos_transfere bt
                        WHERE COALESCE(bt.dt_conciliacao, bt.dt_lancamento, bt.dt_emissao, bt.dt_previsao) BETWEEN %s AND %s
                          AND COALESCE(bt.nr_valor, 0) <> 0;
                    """,
                    (INICIO, FIM),
                ),
                (
                    "transferencias_no_periodo_com_valor_zero",
                    """
                        SELECT COUNT(*), SUM(COALESCE(bt.nr_valor, 0))
                        FROM bancos_transfere bt
                        WHERE COALESCE(bt.dt_conciliacao, bt.dt_lancamento, bt.dt_emissao, bt.dt_previsao) BETWEEN %s AND %s
                          AND COALESCE(bt.nr_valor, 0) = 0;
                    """,
                    (INICIO, FIM),
                ),
            ]

            for nome, sql, params in consultas:
                cursor.execute(sql, params)
                quantidade, total = cursor.fetchone()
                print(f"{nome} | qtd={quantidade} | total={moeda(total)}")


if __name__ == "__main__":
    main()
