from __future__ import annotations

from argparse import ArgumentParser
import csv
from datetime import datetime
from pathlib import Path
import sys

from importar_historico import importar_banco


INVENTARIO_PADRAO = Path(r"C:\ConciliaFinanceira\dados\extracoes\inventario_pdfs_bancos_extratos.csv")
LOG_PADRAO = Path(r"C:\ConciliaFinanceira\dados\extracoes\importacao_pdfs_inventario_log.csv")


def ler_importaveis(caminho: Path):
    with caminho.open("r", encoding="utf-8", newline="") as arquivo:
        leitor = csv.DictReader(arquivo, delimiter=";")
        for linha in leitor:
            if linha.get("status") != "IMPORTAVEL":
                continue
            arquivo_pdf = Path(linha["arquivo"])
            yield linha, arquivo_pdf


def carregar_processados(log: Path) -> set[str]:
    if not log.exists():
        return set()

    processados = set()
    with log.open("r", encoding="utf-8", newline="") as arquivo:
        leitor = csv.DictReader(arquivo, delimiter=";")
        for linha in leitor:
            if linha.get("status_importacao") == "OK":
                processados.add(linha.get("arquivo", "").lower())
    return processados


def abrir_log(log: Path):
    log.parent.mkdir(parents=True, exist_ok=True)
    novo = not log.exists() or log.stat().st_size == 0
    arquivo = log.open("a", encoding="utf-8", newline="")
    campos = [
        "executado_em",
        "status_importacao",
        "arquivo",
        "layout",
        "banco_nome",
        "ano_fechamento",
        "registros",
        "inseridos",
        "existentes",
        "ignorados",
        "periodo_inicio",
        "periodo_fim",
        "erro",
    ]
    escritor = csv.DictWriter(arquivo, fieldnames=campos, delimiter=";")
    if novo:
        escritor.writeheader()
        arquivo.flush()
    return arquivo, escritor


def main() -> int:
    parser = ArgumentParser(description="Importa PDFs bancarios a partir do inventario oficial.")
    parser.add_argument("--inventario", default=str(INVENTARIO_PADRAO))
    parser.add_argument("--log", default=str(LOG_PADRAO))
    parser.add_argument("--limite", type=int)
    parser.add_argument("--reprocessar", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    inventario = Path(args.inventario)
    log = Path(args.log)

    if not inventario.exists():
        print(f"Inventario nao encontrado: {inventario}")
        return 1

    itens = list(ler_importaveis(inventario))
    if args.limite:
        itens = itens[: args.limite]

    processados = set() if args.reprocessar else carregar_processados(log)
    pendentes = [(linha, arquivo) for linha, arquivo in itens if str(arquivo).lower() not in processados]

    print(f"Inventario: {inventario}")
    print(f"PDFs importaveis no escopo: {len(itens)}")
    print(f"Ja processados no log: {len(itens) - len(pendentes)}")
    print(f"Pendentes para importar: {len(pendentes)}")

    if args.dry_run:
        for _, arquivo in pendentes[:20]:
            print(arquivo)
        if len(pendentes) > 20:
            print(f"... mais {len(pendentes) - 20} arquivo(s)")
        return 0

    ok = 0
    falhas = 0
    total_inseridos = 0
    total_existentes = 0
    total_registros = 0

    arquivo_log, escritor = abrir_log(log)
    with arquivo_log:
        for indice, (linha, arquivo_pdf) in enumerate(pendentes, start=1):
            agora = datetime.now().isoformat(timespec="seconds")
            try:
                resultado = importar_banco(arquivo_pdf)
                ok += 1
                total_registros += int(resultado.get("registros") or 0)
                total_inseridos += int(resultado.get("inseridos") or 0)
                total_existentes += int(resultado.get("existentes") or 0)
                escritor.writerow(
                    {
                        "executado_em": agora,
                        "status_importacao": "OK",
                        "arquivo": str(arquivo_pdf),
                        "layout": linha.get("layout", ""),
                        "banco_nome": linha.get("banco_nome", ""),
                        "ano_fechamento": linha.get("ano_fechamento", ""),
                        "registros": resultado.get("registros", 0),
                        "inseridos": resultado.get("inseridos", 0),
                        "existentes": resultado.get("existentes", 0),
                        "ignorados": resultado.get("ignorados", 0),
                        "periodo_inicio": resultado.get("periodo_inicio"),
                        "periodo_fim": resultado.get("periodo_fim"),
                        "erro": "",
                    }
                )
            except Exception as erro:
                falhas += 1
                escritor.writerow(
                    {
                        "executado_em": agora,
                        "status_importacao": "ERRO",
                        "arquivo": str(arquivo_pdf),
                        "layout": linha.get("layout", ""),
                        "banco_nome": linha.get("banco_nome", ""),
                        "ano_fechamento": linha.get("ano_fechamento", ""),
                        "registros": 0,
                        "inseridos": 0,
                        "existentes": 0,
                        "ignorados": 0,
                        "periodo_inicio": "",
                        "periodo_fim": "",
                        "erro": str(erro),
                    }
                )
            arquivo_log.flush()

            if indice % 10 == 0 or indice == len(pendentes):
                print(
                    f"Processados {indice}/{len(pendentes)} | "
                    f"OK={ok} ERRO={falhas} inseridos={total_inseridos} existentes={total_existentes}",
                    flush=True,
                )

    print("Resumo da importacao:")
    print(f"OK: {ok}")
    print(f"Falhas: {falhas}")
    print(f"Registros lidos: {total_registros}")
    print(f"Inseridos: {total_inseridos}")
    print(f"Ja existentes: {total_existentes}")
    print(f"Log: {log}")
    return 0 if falhas == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
