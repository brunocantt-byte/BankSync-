from collections import defaultdict
from decimal import Decimal

from base_historica import conectar_banco
from diagnosticar_clinux_db import carregar_config, conectar as conectar_clinux


INICIO = "2024-01-01"
FIM = "2026-12-31"


def moeda(valor):
    valor = Decimal(str(valor or 0))
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def imprimir_linha(*itens):
    print(" | ".join(str(item) for item in itens))


def auditar_local():
    print("BASE LOCAL - lancamentos_sistema origem CLINUX")
    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                    SELECT
                        tipo_movimento,
                        COUNT(*),
                        SUM(valor),
                        MIN(COALESCE(data_pagamento, data_lancamento)),
                        MAX(COALESCE(data_pagamento, data_lancamento))
                    FROM lancamentos_sistema
                    WHERE sistema_origem = 'CLINUX'
                    GROUP BY tipo_movimento
                    ORDER BY tipo_movimento;
                """
            )
            for tipo, qtd, total, inicio, fim in cursor.fetchall():
                imprimir_linha(tipo, qtd, moeda(total), inicio, fim)

            cursor.execute(
                """
                    SELECT
                        DATE_TRUNC('year', COALESCE(data_pagamento, data_lancamento))::date,
                        tipo_movimento,
                        COUNT(*),
                        SUM(valor)
                    FROM lancamentos_sistema
                    WHERE sistema_origem = 'CLINUX'
                    GROUP BY 1, 2
                    ORDER BY 1, 2;
                """
            )
            print()
            print("BASE LOCAL POR ANO")
            for ano, tipo, qtd, total in cursor.fetchall():
                imprimir_linha(ano.year, tipo, qtd, moeda(total))


def auditar_clinux():
    print()
    print("BANCO CLINUX - mesmo filtro da importacao")
    config = carregar_config()
    label, conexao = conectar_clinux(config)
    print(f"Conexao: {label}")

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                    SELECT
                        CASE
                            WHEN COALESCE(l.ds_tipo, '') IN ('F', 'U') THEN 'ENTRADA'
                            ELSE 'SAIDA'
                        END AS tipo_movimento,
                        COUNT(*),
                        SUM(COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0)),
                        MIN(p.dt_realizacao),
                        MAX(p.dt_realizacao)
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    WHERE l.cd_empresa = 1
                      AND p.dt_realizacao BETWEEN %s AND %s
                      AND COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0) <> 0
                    GROUP BY 1
                    ORDER BY 1;
                """,
                (INICIO, FIM),
            )
            for tipo, qtd, total, inicio, fim in cursor.fetchall():
                imprimir_linha(tipo, qtd, moeda(total), inicio, fim)

            cursor.execute(
                """
                    SELECT
                        DATE_TRUNC('year', p.dt_realizacao)::date,
                        CASE
                            WHEN COALESCE(l.ds_tipo, '') IN ('F', 'U') THEN 'ENTRADA'
                            ELSE 'SAIDA'
                        END AS tipo_movimento,
                        COUNT(*),
                        SUM(COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0))
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    WHERE l.cd_empresa = 1
                      AND p.dt_realizacao BETWEEN %s AND %s
                      AND COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0) <> 0
                    GROUP BY 1, 2
                    ORDER BY 1, 2;
                """,
                (INICIO, FIM),
            )
            print()
            print("CLINUX POR ANO - empresa 1")
            for ano, tipo, qtd, total in cursor.fetchall():
                imprimir_linha(ano.year, tipo, qtd, moeda(total))

            cursor.execute(
                """
                    SELECT
                        COALESCE(l.ds_tipo, '') AS tipo_clinux,
                        COUNT(*),
                        SUM(COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0)) AS total
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    WHERE l.cd_empresa = 1
                      AND p.dt_realizacao BETWEEN %s AND %s
                      AND COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0) <> 0
                    GROUP BY l.ds_tipo
                    ORDER BY total DESC NULLS LAST;
                """,
                (INICIO, FIM),
            )
            print()
            print("CLINUX POR TIPO ORIGINAL - empresa 1")
            for tipo, qtd, total in cursor.fetchall():
                movimento = "ENTRADA" if tipo in ("F", "U") else "SAIDA"
                imprimir_linha(tipo or "<vazio>", movimento, qtd, moeda(total))

            cursor.execute(
                """
                    SELECT
                        l.cd_empresa,
                        COUNT(*),
                        SUM(COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0)) AS total,
                        MIN(p.dt_realizacao),
                        MAX(p.dt_realizacao)
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    WHERE p.dt_realizacao BETWEEN %s AND %s
                      AND COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0) <> 0
                    GROUP BY l.cd_empresa
                    ORDER BY total DESC NULLS LAST;
                """,
                (INICIO, FIM),
            )
            print()
            print("CLINUX POR EMPRESA - todas as empresas")
            for empresa, qtd, total, inicio, fim in cursor.fetchall():
                imprimir_linha(f"empresa={empresa}", qtd, moeda(total), inicio, fim)


def main():
    auditar_local()
    auditar_clinux()


if __name__ == "__main__":
    main()
