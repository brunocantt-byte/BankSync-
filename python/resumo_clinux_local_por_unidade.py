from decimal import Decimal

from base_historica import conectar_banco


def moeda(valor):
    numero = Decimal(str(valor or 0))
    return f"R$ {numero:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main():
    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                    SELECT
                        l.metadados ->> 'cd_empresa_clinux' AS cd_empresa_clinux,
                        COALESCE(
                            l.metadados ->> 'unidade_clinux',
                            e.nome_fantasia,
                            e.razao_social
                        ) AS unidade,
                        COUNT(*) FILTER (
                            WHERE l.sistema_origem = 'CLINUX'
                        ) AS pagamentos,
                        COUNT(*) FILTER (
                            WHERE l.sistema_origem = 'CLINUX_TRANSFERENCIA'
                        ) AS transferencias,
                        COALESCE(SUM(l.valor) FILTER (
                            WHERE l.sistema_origem = 'CLINUX'
                              AND l.tipo_movimento = 'ENTRADA'
                              AND l.metadados ->> 'grupo_conta_clinux' = 'RECEITAS'
                        ), 0) AS faturamento_bruto,
                        COALESCE(SUM(l.valor) FILTER (
                            WHERE l.sistema_origem = 'CLINUX'
                              AND l.tipo_movimento = 'ENTRADA'
                        ), 0) AS entradas_sem_transferencia,
                        COALESCE(SUM(l.valor) FILTER (
                            WHERE l.sistema_origem = 'CLINUX'
                              AND l.tipo_movimento = 'SAIDA'
                        ), 0) AS saidas_sem_transferencia,
                        COALESCE(SUM(l.valor) FILTER (
                            WHERE l.sistema_origem = 'CLINUX_TRANSFERENCIA'
                              AND l.tipo_movimento = 'ENTRADA'
                        ), 0) AS transferencia_entrada,
                        COALESCE(SUM(l.valor) FILTER (
                            WHERE l.sistema_origem = 'CLINUX_TRANSFERENCIA'
                              AND l.tipo_movimento = 'SAIDA'
                        ), 0) AS transferencia_saida
                    FROM lancamentos_sistema l
                    JOIN empresas e ON e.id = l.empresa_id
                    WHERE l.sistema_origem IN ('CLINUX', 'CLINUX_TRANSFERENCIA')
                    GROUP BY 1, 2
                    ORDER BY faturamento_bruto DESC, unidade;
                """
            )

            print("UNIDADE | PAGAMENTOS | TRANSFERENCIAS | FATURAMENTO BRUTO | ENTRADAS S/ TRANSF | SAIDAS S/ TRANSF | TRANSF ENTRADA | TRANSF SAIDA")
            for linha in cursor.fetchall():
                (
                    cd_empresa,
                    unidade,
                    pagamentos,
                    transferencias,
                    faturamento_bruto,
                    entradas_sem_transferencia,
                    saidas_sem_transferencia,
                    transferencia_entrada,
                    transferencia_saida,
                ) = linha
                print(
                    f"{cd_empresa} - {unidade} | "
                    f"{pagamentos} | "
                    f"{transferencias} | "
                    f"{moeda(faturamento_bruto)} | "
                    f"{moeda(entradas_sem_transferencia)} | "
                    f"{moeda(saidas_sem_transferencia)} | "
                    f"{moeda(transferencia_entrada)} | "
                    f"{moeda(transferencia_saida)}"
                )

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
            print("RESUMO POR ORIGEM/TIPO")
            for origem, tipo, quantidade, total in cursor.fetchall():
                print(f"{origem} | {tipo} | {quantidade} | {moeda(total)}")


if __name__ == "__main__":
    main()
