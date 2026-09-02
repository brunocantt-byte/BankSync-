from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
import csv
import re


BASE_DIR = Path(r"C:\ConciliaFinanceira\conciliados\ultimos_12_meses")
BANCO_SEM = BASE_DIR / "05_banco_sem_sistema.csv"
SISTEMA_SEM = BASE_DIR / "06_sistema_sem_banco.csv"
SAIDA = BASE_DIR / "08_possiveis_divergencias_valor.csv"


def only_digits(value):
    return re.sub(r"\D", "", value or "")


def doc_key(value):
    digits = only_digits(value)
    if len(digits) == 14:
        return digits[:8]
    return digits


def to_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def to_decimal(value):
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        return Decimal("0")


def read_dicts(path):
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        yield from csv.DictReader(fp, delimiter=";")


def main():
    sistemas = []
    by_doc_type_day = defaultdict(list)
    by_doc_type_month = defaultdict(list)

    for row in read_dicts(SISTEMA_SEM):
        key = doc_key(row.get("documento", ""))
        if not key:
            continue
        row["_data"] = to_date(row["data"])
        row["_valor"] = to_decimal(row["valor"])
        row["_doc_key"] = key
        sistemas.append(row)
        by_doc_type_day[(key, row["tipo"], row["_data"])].append(row)
        by_doc_type_month[(key, row["tipo"], row["_data"].year, row["_data"].month)].append(row)

    saida = []
    sistemas_usados = set()

    for banco in read_dicts(BANCO_SEM):
        key = doc_key(banco.get("documento", ""))
        if not key:
            continue
        banco_data = to_date(banco["data"])
        banco_valor = to_decimal(banco["valor"])
        candidatos = []
        for offset in range(-3, 4):
            candidatos.extend(by_doc_type_day.get((key, banco["tipo"], banco_data + timedelta(days=offset)), []))
        if not candidatos:
            candidatos.extend(by_doc_type_month.get((key, banco["tipo"], banco_data.year, banco_data.month), [])[:20])

        candidatos = [
            item for item in candidatos
            if item["sistema_id"] not in sistemas_usados
            and item["_valor"] != banco_valor
        ]
        if not candidatos:
            continue

        escolhido = sorted(
            candidatos,
            key=lambda item: (
                abs((banco_data - item["_data"]).days),
                abs(banco_valor - item["_valor"]),
                item["sistema_id"],
            ),
        )[0]
        sistemas_usados.add(escolhido["sistema_id"])
        saida.append({
            "status": "POSSIVEL_DIVERGENCIA_VALOR",
            "banco_id": banco["banco_id"],
            "banco_data": banco["data"],
            "banco_tipo": banco["tipo"],
            "banco_valor": banco["valor"],
            "banco_documento": banco["documento"],
            "banco_banco": banco["banco"],
            "banco_conta": banco["conta"],
            "banco_empresa": banco["empresa"],
            "banco_descricao": banco["descricao"],
            "sistema_id": escolhido["sistema_id"],
            "sistema_data": escolhido["data"],
            "sistema_tipo": escolhido["tipo"],
            "sistema_valor": escolhido["valor"],
            "sistema_documento": escolhido["documento"],
            "sistema_empresa": escolhido["empresa"],
            "sistema_favorecido_descricao": f"{escolhido['favorecido']} - {escolhido['descricao']}".strip(" -"),
            "sistema_categoria": escolhido["categoria"],
            "sistema_centro_custo": escolhido["centro_custo"],
            "sistema_origem": escolhido["sistema_origem"],
            "diferenca_valor": str(banco_valor - escolhido["_valor"]),
            "observacao": "Mesmo documento/CNPJ raiz e tipo, com data próxima ou mesmo mês, mas valor diferente.",
        })

    campos = [
        "status", "banco_id", "banco_data", "banco_tipo", "banco_valor",
        "banco_documento", "banco_banco", "banco_conta", "banco_empresa",
        "banco_descricao", "sistema_id", "sistema_data", "sistema_tipo",
        "sistema_valor", "sistema_documento", "sistema_empresa",
        "sistema_favorecido_descricao", "sistema_categoria",
        "sistema_centro_custo", "sistema_origem", "diferenca_valor",
        "observacao",
    ]
    with SAIDA.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=campos, delimiter=";")
        writer.writeheader()
        writer.writerows(saida)

    print(f"{SAIDA}; linhas={len(saida)}")


if __name__ == "__main__":
    main()
