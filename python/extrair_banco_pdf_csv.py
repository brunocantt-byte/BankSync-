from pathlib import Path
import argparse
import csv
import json
import os

from leitores_pdf_banco import extrair_pdf_bancario


ARQUIVO_PDF = Path(os.getenv("BANKSYNC_ARQUIVO_BANCO", r"C:\ConciliaFinanceira\entrada\banco\BANCO.pdf"))
ARQUIVO_CSV = Path(r"C:\ConciliaFinanceira\dados\banco_pdf_extraido.csv")


def extrair_transacoes_pdf(caminho):
    return extrair_pdf_bancario(caminho).transacoes


def escrever_csv(transacoes, caminho_saida, metadados=None):
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    metadados = metadados or {}

    with caminho_saida.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(
            arquivo,
            fieldnames=[
                "banco_nome",
                "banco_codigo",
                "layout",
                "empresa_nome",
                "empresa_cnpj",
                "agencia",
                "conta",
                "digito",
                "data",
                "tipo_movimento",
                "valor",
                "descricao",
                "documento",
                "pagina",
            ],
            delimiter=";",
        )

        escritor.writeheader()
        for transacao in transacoes:
            escritor.writerow({**metadados, **transacao})

    caminho_metadados = caminho_saida.with_suffix(".json")
    with caminho_metadados.open("w", encoding="utf-8") as arquivo:
        json.dump(
            {
                "metadados": metadados,
                "quantidade_transacoes": len(transacoes),
            },
            arquivo,
            ensure_ascii=False,
            indent=2,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--entrada", default=str(ARQUIVO_PDF))
    parser.add_argument("--saida", default=str(ARQUIVO_CSV))
    args = parser.parse_args()

    arquivo_pdf = Path(args.entrada)
    arquivo_csv = Path(args.saida)

    if not arquivo_pdf.exists():
        print(f"Arquivo nao encontrado: {arquivo_pdf}")
        return

    extracao = extrair_pdf_bancario(arquivo_pdf)
    metadados = {
        "banco_nome": extracao.banco_nome,
        "banco_codigo": extracao.banco_codigo or "",
        "layout": extracao.layout,
        "empresa_nome": extracao.empresa_nome or "",
        "empresa_cnpj": extracao.empresa_cnpj or "",
        "agencia": extracao.agencia or "",
        "conta": extracao.conta or "",
        "digito": extracao.digito or "",
    }
    escrever_csv(extracao.transacoes, arquivo_csv, metadados)

    print(f"Layout: {extracao.layout}")
    print(f"Banco: {extracao.banco_nome}")
    print(f"Transacoes extraidas: {len(extracao.transacoes)}")
    for aviso in extracao.avisos:
        print(f"Aviso: {aviso}")
    print(f"CSV gerado: {arquivo_csv}")


if __name__ == "__main__":
    main()
