from __future__ import annotations

from argparse import ArgumentParser
import csv
from decimal import Decimal
from pathlib import Path
import sys

from base_historica import calcular_hash
from leitores_pdf_banco import extrair_pdf_bancario


INVENTARIO_PADRAO = Path(r"C:\ConciliaFinanceira\dados\extracoes\inventario_pdfs_bancos_extratos.csv")
SAIDA_PADRAO = Path(r"C:\ConciliaFinanceira\dados\extracoes\transacoes_pdfs_bancos_extratos_bruto.csv")
ERROS_PADRAO = Path(r"C:\ConciliaFinanceira\dados\extracoes\transacoes_pdfs_bancos_extratos_erros.csv")


def valor_csv(valor):
    if isinstance(valor, Decimal):
        return f"{valor:.2f}"
    return valor


def ler_pdf_importaveis(inventario: Path):
    with inventario.open("r", encoding="utf-8", newline="") as arquivo:
        leitor = csv.DictReader(arquivo, delimiter=";")
        for linha in leitor:
            if linha.get("status") == "IMPORTAVEL":
                yield linha


def main() -> int:
    parser = ArgumentParser(description="Extrai transacoes brutas dos PDFs marcados como IMPORTAVEL no inventario.")
    parser.add_argument("--inventario", default=str(INVENTARIO_PADRAO))
    parser.add_argument("--saida", default=str(SAIDA_PADRAO))
    parser.add_argument("--erros", default=str(ERROS_PADRAO))
    parser.add_argument("--limite", type=int)
    args = parser.parse_args()

    inventario = Path(args.inventario)
    saida = Path(args.saida)
    erros = Path(args.erros)

    if not inventario.exists():
        print(f"Inventario nao encontrado: {inventario}")
        return 1

    saida.parent.mkdir(parents=True, exist_ok=True)
    itens = list(ler_pdf_importaveis(inventario))
    if args.limite:
        itens = itens[: args.limite]

    campos_saida = [
        "arquivo_hash",
        "arquivo",
        "sequencia_no_arquivo",
        "ano_detectado",
        "pasta_banco",
        "layout",
        "banco_nome",
        "banco_codigo",
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
    ]
    campos_erros = ["arquivo", "ano_detectado", "pasta_banco", "layout", "erro"]

    total_pdfs_ok = 0
    total_pdfs_erro = 0
    total_transacoes = 0

    with saida.open("w", encoding="utf-8", newline="") as arq_saida, erros.open("w", encoding="utf-8", newline="") as arq_erros:
        escritor = csv.DictWriter(arq_saida, fieldnames=campos_saida, delimiter=";")
        escritor.writeheader()
        escritor_erros = csv.DictWriter(arq_erros, fieldnames=campos_erros, delimiter=";")
        escritor_erros.writeheader()

        for indice_pdf, linha in enumerate(itens, start=1):
            caminho = Path(linha["arquivo"])
            try:
                arquivo_hash = calcular_hash(caminho)
                extracao = extrair_pdf_bancario(caminho)
                for indice_tx, transacao in enumerate(extracao.transacoes, start=1):
                    escritor.writerow(
                        {
                            "arquivo_hash": arquivo_hash,
                            "arquivo": str(caminho),
                            "sequencia_no_arquivo": indice_tx,
                            "ano_detectado": linha.get("ano_detectado", ""),
                            "pasta_banco": linha.get("pasta_banco", ""),
                            "layout": extracao.layout,
                            "banco_nome": extracao.banco_nome,
                            "banco_codigo": extracao.banco_codigo or "",
                            "empresa_nome": extracao.empresa_nome or "",
                            "empresa_cnpj": extracao.empresa_cnpj or "",
                            "agencia": extracao.agencia or "",
                            "conta": extracao.conta or "",
                            "digito": extracao.digito or "",
                            "data": transacao.get("data", ""),
                            "tipo_movimento": transacao.get("tipo_movimento", ""),
                            "valor": valor_csv(transacao.get("valor", "")),
                            "descricao": transacao.get("descricao", "") or "",
                            "documento": transacao.get("documento", "") or "",
                            "pagina": transacao.get("pagina", ""),
                        }
                    )
                    total_transacoes += 1
                total_pdfs_ok += 1
            except Exception as erro:
                total_pdfs_erro += 1
                escritor_erros.writerow(
                    {
                        "arquivo": str(caminho),
                        "ano_detectado": linha.get("ano_detectado", ""),
                        "pasta_banco": linha.get("pasta_banco", ""),
                        "layout": linha.get("layout", ""),
                        "erro": str(erro),
                    }
                )
            if indice_pdf % 10 == 0:
                arq_saida.flush()
                arq_erros.flush()
            if indice_pdf % 50 == 0 or indice_pdf == len(itens):
                print(
                    f"PDFs {indice_pdf}/{len(itens)} | OK={total_pdfs_ok} ERRO={total_pdfs_erro} transacoes={total_transacoes}",
                    flush=True,
                )

    print("Resumo da extracao bruta:")
    print(f"PDFs importaveis no inventario: {len(itens)}")
    print(f"PDFs extraidos OK: {total_pdfs_ok}")
    print(f"PDFs com erro: {total_pdfs_erro}")
    print(f"Transacoes brutas extraidas: {total_transacoes}")
    print(f"CSV bruto: {saida}")
    print(f"CSV erros: {erros}")
    return 0 if total_pdfs_erro == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
