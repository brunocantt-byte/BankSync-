from __future__ import annotations

from argparse import ArgumentParser
from collections import OrderedDict
import os
from pathlib import Path
import re

from leitores_pdf_banco import extrair_pdf_bancario, normalizar_texto


PASTA_PADRAO = Path(os.getenv("BANKSYNC_PASTA_BANCO", r"\\SERVIDOR\compartilhamento\BANCOS\EXTRATOS"))
PADRAO_ANO = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def banco_do_caminho(caminho: Path) -> str:
    for parte in caminho.parts:
        normalizado = normalizar_texto(parte)
        if normalizado.startswith("BANCO"):
            return normalizado.replace(" OK", "")

    nome = normalizar_texto(caminho.name)
    for candidato in (
        "BRADESCO",
        "BANCO DO BRASIL",
        "BB",
        "CAIXA",
        "BASA",
        "BANCO DA AMAZONIA",
        "CORA",
        "SICOOB",
        "STONE",
        "SAFRA",
        "UNICRED",
        "UNIPRIME",
        "ITAU",
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


def arquivos_extrato(pasta: Path, ano_minimo: int, incluir_clinux: bool):
    for caminho in sorted(pasta.rglob("*.pdf")):
        ano = ano_do_caminho(caminho)
        if ano is not None and ano < ano_minimo:
            continue

        nome = normalizar_texto(caminho.name)
        caminho_norm = normalizar_texto(str(caminho))

        if "EXTRATO" not in nome:
            continue
        if "LIVRO CAIXA" in caminho_norm:
            continue
        if not incluir_clinux and "CLINUX" in nome:
            continue

        yield caminho


def main():
    parser = ArgumentParser(description="Valida leitores de PDFs bancarios.")
    parser.add_argument("--pasta", default=str(PASTA_PADRAO))
    parser.add_argument("--ano-minimo", type=int, default=2024)
    parser.add_argument("--incluir-clinux", action="store_true")
    parser.add_argument("--max-bancos", type=int, default=20)
    args = parser.parse_args()

    amostras = OrderedDict()
    for caminho in arquivos_extrato(Path(args.pasta), args.ano_minimo, args.incluir_clinux):
        banco = banco_do_caminho(caminho)
        if banco not in amostras:
            amostras[banco] = caminho
        if len(amostras) >= args.max_bancos:
            break

    print(f"Amostras: {len(amostras)}")
    for banco, caminho in amostras.items():
        try:
            extracao = extrair_pdf_bancario(caminho)
            print(
                f"{banco} | layout={extracao.layout} | "
                f"banco={extracao.banco_nome} | "
                f"conta={extracao.agencia or ''}/{extracao.conta or ''}-{extracao.digito or ''} | "
                f"transacoes={len(extracao.transacoes)} | arquivo={caminho}"
            )
            for aviso in extracao.avisos:
                print(f"  aviso: {aviso}")
            for transacao in extracao.transacoes[:2]:
                print(
                    "  exemplo: "
                    f"{transacao['data']} {transacao['tipo_movimento']} "
                    f"{transacao['valor']} {transacao['descricao'][:90]}"
                )
        except Exception as erro:
            print(f"{banco} | ERRO: {erro} | arquivo={caminho}")


if __name__ == "__main__":
    main()
