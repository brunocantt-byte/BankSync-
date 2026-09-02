from __future__ import annotations

from argparse import ArgumentParser
import csv
from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import sys

from leitores_pdf_banco import extrair_pdf_bancario


PASTA_PADRAO = Path(os.getenv("BANKSYNC_PASTA_BANCO", r"\\SERVIDOR\compartilhamento\BANCOS\EXTRATOS"))
SAIDA_PADRAO = Path(r"C:\ConciliaFinanceira\dados\extracoes\inventario_pdfs_bancos_extratos.csv")
PADRAO_ANO = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def detectar_ano(caminho: Path) -> int | None:
    for parte in caminho.parts:
        if PADRAO_ANO.fullmatch(parte):
            return int(parte)

    resultado = PADRAO_ANO.search(str(caminho))
    if resultado:
        return int(resultado.group(1))

    return None


def arquivos_pdf(pasta: Path, ano_minimo: int | None, ano_maximo: int | None):
    for caminho in pasta.rglob("*.pdf"):
        if not caminho.is_file():
            continue

        ano = detectar_ano(caminho)
        if ano_minimo is not None and (ano is None or ano < ano_minimo):
            continue
        if ano_maximo is not None and (ano is None or ano > ano_maximo):
            continue

        yield caminho


def banco_pasta(caminho: Path, raiz: Path) -> str:
    try:
        relativo = caminho.relative_to(raiz)
    except ValueError:
        return ""
    return relativo.parts[0] if relativo.parts else ""


def status_extracao(extracao) -> str:
    if extracao.layout == "CLINUX_EXTRATO_BANCO":
        return "RELATORIO_CLINUX_NAO_IMPORTAR"
    if extracao.transacoes:
        return "IMPORTAVEL"
    if extracao.layout == "PDF_SEM_TEXTO_EXTRAIVEL":
        return "PRECISA_OCR"
    if extracao.layout in (
        "DEMONSTRATIVO_SEM_MOVIMENTO_TRANSACIONAL",
        "BNB_CONSOLIDADO_INVESTIMENTO",
        "UNICRED_RENTABILIDADE",
        "ITAU_DEMONSTRATIVO_APLICACAO",
        "CAIXA_DEMONSTRATIVO_APLICACAO",
    ):
        return "SEM_MOVIMENTO_CONCILIAVEL"
    if extracao.layout != "NAO_SUPORTADO":
        return "SEM_MOVIMENTO_CONCILIAVEL"
    return "NAO_SUPORTADO"


def inventariar_um(caminho: Path, raiz: Path):
    try:
        extracao = extrair_pdf_bancario(caminho)
        return {
            "status": status_extracao(extracao),
            "ano_detectado": detectar_ano(caminho) or "",
            "pasta_banco": banco_pasta(caminho, raiz),
            "layout": extracao.layout,
            "banco_nome": extracao.banco_nome,
            "banco_codigo": extracao.banco_codigo or "",
            "empresa_nome": extracao.empresa_nome or "",
            "empresa_cnpj": extracao.empresa_cnpj or "",
            "agencia": extracao.agencia or "",
            "conta": extracao.conta or "",
            "digito": extracao.digito or "",
            "quantidade_transacoes": len(extracao.transacoes),
            "avisos": " | ".join(extracao.avisos),
            "arquivo": str(caminho),
        }
    except Exception as erro:
        return {
            "status": "ERRO_LEITURA",
            "ano_detectado": detectar_ano(caminho) or "",
            "pasta_banco": banco_pasta(caminho, raiz),
            "layout": "",
            "banco_nome": "",
            "banco_codigo": "",
            "empresa_nome": "",
            "empresa_cnpj": "",
            "agencia": "",
            "conta": "",
            "digito": "",
            "quantidade_transacoes": 0,
            "avisos": str(erro),
            "arquivo": str(caminho),
        }


def erro_de_rede(resultado: dict) -> bool:
    if resultado["status"] != "ERRO_LEITURA":
        return False
    aviso = resultado.get("avisos", "").lower()
    return (
        "arquivo nao encontrado" in aviso
        or "no such file or directory" in aviso
        or "cannot find path" in aviso
        or "network" in aviso
    )


def main() -> int:
    parser = ArgumentParser(description="Inventaria todos os PDFs da pasta oficial BANCOS\\EXTRATOS.")
    parser.add_argument("--pasta", default=str(PASTA_PADRAO))
    parser.add_argument("--saida", default=str(SAIDA_PADRAO))
    parser.add_argument("--ano-minimo", type=int)
    parser.add_argument("--ano-maximo", type=int)
    parser.add_argument("--somente-ano", type=int)
    parser.add_argument("--limite", type=int)
    parser.add_argument("--limite-erros-rede", type=int, default=50)
    parser.add_argument("--forcar-substituicao", action="store_true")
    args = parser.parse_args()

    pasta = Path(args.pasta)
    if not pasta.exists():
        raise FileNotFoundError(f"Pasta inacessivel: {pasta}")

    ano_minimo = args.somente_ano or args.ano_minimo
    ano_maximo = args.somente_ano or args.ano_maximo
    saida = Path(args.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida_execucao = saida.with_name(f"{saida.stem}.em_execucao{saida.suffix}")
    saida_falha = saida.with_name(f"{saida.stem}.falha_{datetime.now():%Y%m%d_%H%M%S}{saida.suffix}")

    campos = [
        "status",
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
        "quantidade_transacoes",
        "avisos",
        "arquivo",
    ]
    totais = {}
    total_lidos = 0

    with saida_execucao.open("w", encoding="utf-8", newline="") as arquivo_saida:
        escritor = csv.DictWriter(arquivo_saida, fieldnames=campos, delimiter=";")
        escritor.writeheader()
        arquivo_saida.flush()

        for caminho in arquivos_pdf(pasta, ano_minimo, ano_maximo):
            if args.limite and total_lidos >= args.limite:
                break
            total_lidos += 1
            resultado = inventariar_um(caminho, pasta)
            escritor.writerow(resultado)
            totais[resultado["status"]] = totais.get(resultado["status"], 0) + 1
            if total_lidos % 10 == 0:
                arquivo_saida.flush()
            if total_lidos % 50 == 0:
                print(f"Processados {total_lidos} PDFs", flush=True)

    erros_rede = 0
    with saida_execucao.open("r", encoding="utf-8", newline="") as arquivo_saida:
        leitor = csv.DictReader(arquivo_saida, delimiter=";")
        erros_rede = sum(1 for linha in leitor if erro_de_rede(linha))

    if erros_rede > args.limite_erros_rede and not args.forcar_substituicao:
        shutil.move(saida_execucao, saida_falha)
        print(f"PDFs lidos: {total_lidos}")
        for status, total in sorted(totais.items()):
            print(f"{status}: {total}")
        print(f"Inventario oficial nao substituido por possivel oscilacao de rede: {erros_rede} erro(s).")
        print(f"Arquivo da execucao com falha: {saida_falha}")
        return 2

    shutil.move(saida_execucao, saida)
    print(f"PDFs lidos: {total_lidos}")
    for status, total in sorted(totais.items()):
        print(f"{status}: {total}")
    print(f"Inventario gerado: {saida}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:
        print(f"Erro no inventario de PDFs bancarios oficiais: {erro}")
        sys.exit(1)
