from __future__ import annotations

from argparse import ArgumentParser
from collections import OrderedDict
import os
from pathlib import Path
import re

import pdfplumber


PASTA_PADRAO = Path(os.getenv("BANKSYNC_PASTA_BANCO", r"\\SERVIDOR\compartilhamento\BANCOS\EXTRATOS"))
PADRAO_ANO = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def nome_banco(caminho: Path) -> str:
    for parte in caminho.parts:
        if parte.upper().startswith("BANCO"):
            return parte.upper()

    nome = caminho.name.upper()
    for candidato in (
        "BRADESCO",
        "ITAÚ",
        "ITAU",
        "BANCO DO BRASIL",
        "BB",
        "BNB",
        "BANCO DO NORDESTE",
        "BASA",
        "BANCO DA AMAZONIA",
        "UNICRED",
        "CORA",
        "STONE",
        "SICOOB",
        "UNIPRIME",
    ):
        if candidato in nome:
            return candidato

    return "SEM_BANCO_IDENTIFICADO"


def ano_do_caminho(caminho: Path) -> int | None:
    for parte in caminho.parts:
        resultado = PADRAO_ANO.search(parte)
        if resultado:
            return int(resultado.group(1))
    return None


def arquivos_extrato(pasta: Path, ano_minimo: int):
    for caminho in sorted(pasta.rglob("*.pdf")):
        ano = ano_do_caminho(caminho)
        if ano is not None and ano < ano_minimo:
            continue

        caminho_texto = str(caminho).upper()
        if "EXTRATO" not in caminho.name.upper():
            continue
        if "LIVRO CAIXA" in caminho_texto:
            continue
        yield caminho


def extrair_linhas(caminho: Path, paginas: int, limite_linhas: int):
    linhas = []
    with pdfplumber.open(caminho) as pdf:
        for pagina in pdf.pages[:paginas]:
            texto = pagina.extract_text(x_tolerance=1, y_tolerance=3) or ""
            for linha in texto.splitlines():
                linha = linha.strip()
                if linha:
                    linhas.append(linha)
                if len(linhas) >= limite_linhas:
                    return linhas
    return linhas


def main():
    parser = ArgumentParser(
        description="Mostra amostras de texto dos PDFs de extrato por banco."
    )
    parser.add_argument("--pasta", default=str(PASTA_PADRAO))
    parser.add_argument("--ano-minimo", type=int, default=2024)
    parser.add_argument("--paginas", type=int, default=1)
    parser.add_argument("--linhas", type=int, default=35)
    parser.add_argument("--max-bancos", type=int, default=20)
    parser.add_argument("--arquivo", action="append", default=[])
    args = parser.parse_args()

    if args.arquivo:
        for item in args.arquivo:
            caminho = Path(item)
            print()
            print("=" * 90)
            print(caminho)
            print("-" * 90)
            try:
                for linha in extrair_linhas(caminho, args.paginas, args.linhas):
                    print(linha)
            except Exception as erro:
                print(f"ERRO AO LER PDF: {erro}")
        return

    amostras = OrderedDict()
    for caminho in arquivos_extrato(Path(args.pasta), args.ano_minimo):
        banco = nome_banco(caminho)
        if banco not in amostras:
            amostras[banco] = caminho
        if len(amostras) >= args.max_bancos:
            break

    print(f"Bancos/layouts amostrados: {len(amostras)}")
    for banco, caminho in amostras.items():
        print()
        print("=" * 90)
        print(banco)
        print(caminho)
        print("-" * 90)
        try:
            for linha in extrair_linhas(caminho, args.paginas, args.linhas):
                print(linha)
        except Exception as erro:
            print(f"ERRO AO LER PDF: {erro}")


if __name__ == "__main__":
    main()
