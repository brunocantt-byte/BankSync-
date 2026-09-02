from __future__ import annotations

from argparse import ArgumentParser
from collections import Counter
from datetime import date
from decimal import Decimal
import json
import os
import sys

from dotenv import load_dotenv

from base_historica import BASE_DIR
from conciliar_cora import CONTA_BANCARIA_ID, EMPRESA_ID, conciliar, conectar_banco


def parse_data(valor: str) -> date:
    return date.fromisoformat(valor)


def para_json(valor):
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, date):
        return valor.isoformat()
    return valor


def somar_por_tipo(registros, tipo_movimento):
    return sum(
        (
            Decimal(registro[3])
            for registro in registros
            if registro[2] == tipo_movimento
        ),
        Decimal("0.00"),
    )


def registrar_execucao(
    *,
    empresa_id,
    conta_bancaria_id,
    periodo_inicio,
    periodo_fim,
    parametros,
    totais,
    status="PROCESSADO",
    observacao=None,
):
    load_dotenv(BASE_DIR / ".env")

    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                    INSERT INTO conciliacao_execucoes (
                        empresa_id,
                        conta_bancaria_id,
                        periodo_inicio,
                        periodo_fim,
                        nome,
                        status,
                        parametros,
                        totais,
                        observacao,
                        finalizado_em
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        CURRENT_TIMESTAMP
                    )
                    RETURNING id;
                """,
                (
                    empresa_id,
                    conta_bancaria_id,
                    periodo_inicio,
                    periodo_fim,
                    f"Conciliacao {periodo_inicio} a {periodo_fim}",
                    status,
                    json.dumps(parametros, default=para_json),
                    json.dumps(totais, default=para_json),
                    observacao,
                ),
            )
            execucao_id = cursor.fetchone()[0]
        conexao.commit()

    return execucao_id


def main():
    parser = ArgumentParser(
        description="Executa conciliacao usando a base historica permanente."
    )
    parser.add_argument("--inicio", required=True, help="Data inicial: YYYY-MM-DD")
    parser.add_argument("--fim", required=True, help="Data final: YYYY-MM-DD")
    parser.add_argument("--empresa-id", type=int, default=EMPRESA_ID)
    parser.add_argument("--conta-bancaria-id", type=int, default=CONTA_BANCARIA_ID)
    parser.add_argument(
        "--sistema-origem",
        default=None,
        help="Opcional. Use para restringir a um arquivo/origem especifica.",
    )
    args = parser.parse_args()

    periodo_inicio = parse_data(args.inicio)
    periodo_fim = parse_data(args.fim)

    bancos, sistemas, resultados, sistemas_usados = conciliar(
        conta_bancaria_id=args.conta_bancaria_id,
        empresa_id=args.empresa_id,
        sistema_origem=args.sistema_origem,
        periodo_inicio=periodo_inicio,
        periodo_fim=periodo_fim,
    )

    status = Counter(item["status"] for item in resultados)
    sistema_sem_banco = len(sistemas) - len(sistemas_usados)
    conciliados = status["CONCILIADO"] + status["CONCILIADO_VALOR_IGUAL"]

    totais = {
        "quantidade_banco": len(bancos),
        "quantidade_sistema": len(sistemas),
        "total_banco_entradas": somar_por_tipo(bancos, "ENTRADA"),
        "total_banco_saidas": somar_por_tipo(bancos, "SAIDA"),
        "total_sistema_entradas": somar_por_tipo(sistemas, "ENTRADA"),
        "total_sistema_saidas": somar_por_tipo(sistemas, "SAIDA"),
        "conciliados": conciliados,
        "banco_sem_sistema": status["NAO_ENCONTRADO"],
        "sistema_sem_banco": sistema_sem_banco,
        "por_status": dict(status),
    }
    parametros = {
        "empresa_id": args.empresa_id,
        "conta_bancaria_id": args.conta_bancaria_id,
        "periodo_inicio": periodo_inicio,
        "periodo_fim": periodo_fim,
        "sistema_origem": args.sistema_origem,
    }

    execucao_id = registrar_execucao(
        empresa_id=args.empresa_id,
        conta_bancaria_id=args.conta_bancaria_id,
        periodo_inicio=periodo_inicio,
        periodo_fim=periodo_fim,
        parametros=parametros,
        totais=totais,
    )

    print(f"Execucao registrada: {execucao_id}")
    print(
        f"Banco: {len(bancos)} lancamentos | "
        f"entradas R$ {totais['total_banco_entradas']:.2f} | "
        f"saidas R$ {totais['total_banco_saidas']:.2f}"
    )
    print(
        f"Sistema: {len(sistemas)} lancamentos | "
        f"entradas R$ {totais['total_sistema_entradas']:.2f} | "
        f"saidas R$ {totais['total_sistema_saidas']:.2f}"
    )
    print(f"Conciliados: {conciliados}")
    print(f"Banco sem sistema: {status['NAO_ENCONTRADO']}")
    print(f"Sistema sem banco: {sistema_sem_banco}")
    print(f"Status: {dict(status)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as erro:
        print(f"Erro na conciliacao por periodo: {erro}")
        sys.exit(1)
