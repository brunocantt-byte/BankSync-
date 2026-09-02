from diagnosticar_clinux_db import carregar_config, conectar as conectar_clinux
from base_historica import conectar_banco


INICIO = "2024-01-01"
FIM = "2026-12-31"


def moeda(valor):
    return f"R$ {float(valor or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def auditar_clinux():
    config = carregar_config()
    label, conexao = conectar_clinux(config)
    print(f"Conexao Clinux OK: {label}")

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                    SELECT
                        COUNT(*) AS qtd,
                        SUM(p.nr_realizado) AS total_realizado,
                        MIN(p.dt_realizacao) AS inicio,
                        MAX(p.dt_realizacao) AS fim
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    WHERE p.dt_realizacao BETWEEN %s AND %s
                      AND COALESCE(p.nr_realizado, 0) <> 0;
                """,
                (INICIO, FIM),
            )
            qtd, total, inicio, fim = cursor.fetchone()
            print()
            print("CLINUX - Relatorios > Financeiro > Lancamentos Detalhados")
            print("Filtro: todas as empresas | data=REALIZACAO | valor=REALIZADO")
            print(f"qtd={qtd} | total={moeda(total)} | periodo_real={inicio} a {fim}")

            cursor.execute(
                """
                    SELECT
                        CASE
                            WHEN COALESCE(cg.sn_despesa, false) = false THEN 'ENTRADA'
                            ELSE 'SAIDA'
                        END AS tipo_movimento,
                        COUNT(*) AS qtd,
                        SUM(p.nr_realizado) AS total
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    LEFT JOIN contas c ON c.cd_conta = l.cd_conta
                    LEFT JOIN contas_grupos cg ON cg.cd_grupo = c.cd_grupo
                    WHERE p.dt_realizacao BETWEEN %s AND %s
                      AND COALESCE(p.nr_realizado, 0) <> 0
                    GROUP BY 1
                    ORDER BY 1;
                """,
                (INICIO, FIM),
            )
            print()
            print("CLINUX por entrada/saida usando grupo de conta:")
            for tipo, qtd, total in cursor.fetchall():
                print(f"{tipo} | qtd={qtd} | total={moeda(total)}")

            cursor.execute(
                """
                    SELECT
                        e.cd_empresa,
                        e.ds_empresa,
                        COUNT(*) AS qtd,
                        SUM(p.nr_realizado) AS total_realizado,
                        SUM(p.nr_realizado) FILTER (
                            WHERE COALESCE(cg.ds_grupo, '') = 'RECEITAS'
                              AND COALESCE(cg.sn_despesa, false) = false
                        ) AS faturamento_bruto
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    LEFT JOIN empresas e ON e.cd_empresa = l.cd_empresa
                    LEFT JOIN contas c ON c.cd_conta = l.cd_conta
                    LEFT JOIN contas_grupos cg ON cg.cd_grupo = c.cd_grupo
                    WHERE p.dt_realizacao BETWEEN %s AND %s
                      AND COALESCE(p.nr_realizado, 0) <> 0
                    GROUP BY e.cd_empresa, e.ds_empresa
                    ORDER BY faturamento_bruto DESC NULLS LAST, total_realizado DESC;
                """,
                (INICIO, FIM),
            )
            print()
            print("CLINUX por unidade:")
            for empresa, unidade, qtd, total, faturamento in cursor.fetchall():
                print(
                    f"{empresa} - {unidade} | qtd={qtd} | "
                    f"total_realizado={moeda(total)} | "
                    f"faturamento_bruto={moeda(faturamento)}"
                )

            cursor.execute(
                """
                    SELECT
                        COUNT(*) AS qtd,
                        SUM(COALESCE(p.nr_pagamento, p.nr_previsto, 0)) AS total_fallback
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    WHERE p.dt_realizacao BETWEEN %s AND %s
                      AND COALESCE(p.nr_realizado, 0) = 0
                      AND COALESCE(p.nr_pagamento, p.nr_previsto, 0) <> 0;
                """,
                (INICIO, FIM),
            )
            qtd, total = cursor.fetchone()
            print()
            print("Registros que entrariam por fallback, mas nao por valor realizado:")
            print(f"qtd={qtd} | total={moeda(total)}")


def auditar_local():
    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                    SELECT
                        sistema_origem,
                        tipo_movimento,
                        COUNT(*),
                        SUM(valor)
                    FROM lancamentos_sistema
                    WHERE sistema_origem IN ('CLINUX', 'CLINUX_TRANSFERENCIA')
                    GROUP BY sistema_origem, tipo_movimento
                    ORDER BY sistema_origem, tipo_movimento;
                """
            )
            print()
            print("BASE LOCAL atual:")
            for origem, tipo, qtd, total in cursor.fetchall():
                print(f"{origem} | {tipo} | qtd={qtd} | total={moeda(total)}")


def main():
    auditar_clinux()
    auditar_local()


if __name__ == "__main__":
    main()
