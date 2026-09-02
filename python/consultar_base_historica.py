from decimal import Decimal
import json

from base_historica import conectar_banco


def moeda(valor):
    if valor is None:
        return "R$ 0,00"

    numero = Decimal(str(valor))
    return f"R$ {numero:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main():
    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                    SELECT
                        COALESCE(origem, 'SEM_ORIGEM') AS origem,
                        COUNT(*) AS arquivos,
                        COALESCE(SUM(quantidade_registros), 0) AS registros,
                        MIN(periodo_inicio) AS primeiro_periodo,
                        MAX(periodo_fim) AS ultimo_periodo
                    FROM arquivos_importados
                    GROUP BY COALESCE(origem, 'SEM_ORIGEM')
                    ORDER BY origem;
                """
            )
            arquivos = cursor.fetchall()

            cursor.execute(
                """
                    SELECT
                        COUNT(*),
                        MIN(data_movimento),
                        MAX(data_movimento),
                        COALESCE(SUM(valor) FILTER (WHERE tipo_movimento = 'ENTRADA'), 0),
                        COALESCE(SUM(valor) FILTER (WHERE tipo_movimento = 'SAIDA'), 0)
                    FROM transacoes_bancarias;
                """
            )
            banco = cursor.fetchone()

            cursor.execute(
                """
                    SELECT
                        COUNT(*),
                        MIN(COALESCE(data_pagamento, data_lancamento)),
                        MAX(COALESCE(data_pagamento, data_lancamento)),
                        COALESCE(SUM(valor) FILTER (WHERE tipo_movimento = 'ENTRADA'), 0),
                        COALESCE(SUM(valor) FILTER (WHERE tipo_movimento = 'SAIDA'), 0)
                    FROM lancamentos_sistema
                    WHERE status <> 'CANCELADO';
                """
            )
            sistema = cursor.fetchone()

            cursor.execute(
                """
                    SELECT
                        id,
                        periodo_inicio,
                        periodo_fim,
                        status,
                        totais,
                        finalizado_em
                    FROM conciliacao_execucoes
                    ORDER BY id DESC
                    LIMIT 5;
                """
            )
            execucoes = cursor.fetchall()

    print("BASE HISTORICA - ARQUIVOS")
    for origem, qtd_arquivos, registros, inicio, fim in arquivos:
        print(
            f"{origem}: {qtd_arquivos} arquivos | {registros} registros | "
            f"periodo {inicio} a {fim}"
        )

    print()
    print("BASE HISTORICA - MOVIMENTOS")
    print(
        f"Banco: {banco[0]} lancamentos | periodo {banco[1]} a {banco[2]} | "
        f"entradas {moeda(banco[3])} | saidas {moeda(banco[4])}"
    )
    print(
        f"Sistema: {sistema[0]} lancamentos | periodo {sistema[1]} a {sistema[2]} | "
        f"entradas {moeda(sistema[3])} | saidas {moeda(sistema[4])}"
    )

    print()
    print("ULTIMAS CONCILIACOES")
    if not execucoes:
        print("Nenhuma conciliacao por periodo registrada ainda.")
        return

    for execucao_id, inicio, fim, status, totais, finalizado_em in execucoes:
        if isinstance(totais, str):
            totais = json.loads(totais)

        print(
            f"#{execucao_id} | {inicio} a {fim} | {status} | "
            f"conciliados {totais.get('conciliados', 0)} | "
            f"finalizada em {finalizado_em}"
        )


if __name__ == "__main__":
    main()
