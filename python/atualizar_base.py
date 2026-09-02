from __future__ import annotations

from argparse import ArgumentParser
from datetime import date
import json
import os
from pathlib import Path
import re
import sys

from base_historica import BANCO_ENTRADA_DIR, SISTEMA_ENTRADA_DIR, garantir_pastas
from importar_historico import importar_banco, importar_sistema
from importar_clinux_sistema import importar as importar_clinux


CONFIG_PASTAS = Path(r"C:\ConciliaFinanceira\config_pastas.json")
EXTENSOES_BANCO = (".pdf", ".csv", ".ofx")
EXTENSOES_SISTEMA = (".xls", ".xlsx")


def inicio_padrao_ultimos_12_meses():
    hoje = date.today()
    try:
        return hoje.replace(year=hoje.year - 1).isoformat()
    except ValueError:
        return hoje.replace(year=hoje.year - 1, day=28).isoformat()


def imprimir_resultado_arquivo(resultado):
    print(
        f"{resultado['origem']}: {resultado['arquivo']} | "
        f"registros={resultado['registros']} | "
        f"inseridos={resultado['inseridos']} | "
        f"ja_existentes={resultado['existentes']}"
    )
    if resultado.get("motivo"):
        print(f"  motivo: {resultado['motivo']}")


def ler_config_pastas():
    if not CONFIG_PASTAS.exists():
        return {"pastas_banco": [], "pastas_sistema": []}

    with CONFIG_PASTAS.open("r", encoding="utf-8") as arquivo:
        config = json.load(arquivo)

    return {
        "pastas_banco": config.get("pastas_banco", []),
        "pastas_sistema": config.get("pastas_sistema", []),
    }


def normalizar_fonte(item, extensoes_padrao):
    if isinstance(item, str):
        return {
            "caminho": Path(item),
            "ativo": True,
            "recursivo": True,
            "extensoes": extensoes_padrao,
            "padrao_subpastas": None,
            "ano_minimo": None,
            "nome_contem": [],
            "nome_nao_contem": [],
            "caminho_nao_contem": [],
            "observacao": "",
        }

    extensoes = tuple(
        extensao.lower()
        for extensao in item.get("extensoes", extensoes_padrao)
    )

    return {
        "caminho": Path(item["caminho"]),
        "ativo": bool(item.get("ativo", True)),
        "recursivo": bool(item.get("recursivo", True)),
        "extensoes": extensoes,
        "padrao_subpastas": item.get("padrao_subpastas"),
        "ano_minimo": item.get("ano_minimo"),
        "nome_contem": item.get("nome_contem", []),
        "nome_nao_contem": item.get("nome_nao_contem", []),
        "caminho_nao_contem": item.get("caminho_nao_contem", []),
        "observacao": item.get("observacao", ""),
    }


def ano_da_subpasta(nome, padrao):
    if not padrao:
        return None

    resultado = re.fullmatch(padrao, nome, flags=re.IGNORECASE)
    if not resultado:
        return None

    for grupo in resultado.groups():
        if grupo and grupo.isdigit():
            return int(grupo)

    return 0


def pastas_alvo(fonte):
    pasta = fonte["caminho"]
    padrao = fonte["padrao_subpastas"]

    if not padrao:
        return [pasta]

    ano_minimo = fonte["ano_minimo"]
    alvos = []

    for subpasta in pasta.iterdir():
        if not subpasta.is_dir():
            continue

        ano = ano_da_subpasta(subpasta.name, padrao)
        if ano is None:
            continue

        if ano_minimo is not None and ano < int(ano_minimo):
            continue

        alvos.append(subpasta)

    return sorted(alvos)


def arquivo_passa_filtros(caminho, fonte):
    nome = caminho.name.upper()
    caminho_texto = str(caminho).upper()

    nome_contem = [item.upper() for item in fonte["nome_contem"]]
    if nome_contem and not any(item in nome for item in nome_contem):
        return False

    nome_nao_contem = [item.upper() for item in fonte["nome_nao_contem"]]
    if nome_nao_contem and any(item in nome for item in nome_nao_contem):
        return False

    caminho_nao_contem = [item.upper() for item in fonte["caminho_nao_contem"]]
    if caminho_nao_contem and any(item in caminho_texto for item in caminho_nao_contem):
        return False

    return True


def arquivos_da_fonte(fonte):
    pasta = fonte["caminho"]
    extensoes = fonte["extensoes"]

    try:
        if not pasta.exists():
            return []

        alvos = pastas_alvo(fonte)

        encontrados = []
        for alvo in alvos:
            if not fonte["recursivo"]:
                candidatos = (
                    caminho
                    for caminho in alvo.iterdir()
                    if caminho.is_file()
                )
            else:
                candidatos = (
                    Path(diretorio) / nome
                    for diretorio, _, nomes in os.walk(alvo)
                    for nome in nomes
                )

            for caminho in candidatos:
                if caminho.suffix.lower() not in extensoes:
                    continue
                if not arquivo_passa_filtros(caminho, fonte):
                    continue
                encontrados.append(caminho)

        return sorted(encontrados)
    except OSError as erro:
        print(f"Nao consegui acessar {pasta}: {erro}")
        return []


def deduplicar_caminhos(caminhos):
    vistos = set()
    unicos = []

    for caminho in caminhos:
        chave = str(caminho).lower()
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(caminho)

    return unicos


def fontes_configuradas(chave, pasta_padrao, extensoes_padrao):
    config = ler_config_pastas()
    fontes = [
        {
            "caminho": pasta_padrao,
            "ativo": True,
            "recursivo": False,
            "extensoes": extensoes_padrao,
            "padrao_subpastas": None,
            "ano_minimo": None,
            "nome_contem": [],
            "nome_nao_contem": [],
            "caminho_nao_contem": [],
            "observacao": "pasta local padrao",
        }
    ]
    fontes.extend(
        normalizar_fonte(item, extensoes_padrao)
        for item in config[chave]
    )
    return fontes


def coletar_arquivos(fontes, incluir_inativas=False):
    todos = []
    resumo = []

    for fonte in fontes:
        arquivos = arquivos_da_fonte(fonte)
        resumo.append((fonte, arquivos))

        if fonte["ativo"] or incluir_inativas:
            todos.extend(arquivos)

    return deduplicar_caminhos(todos), resumo


def imprimir_resumo_fontes(titulo, resumo, amostra=8):
    print()
    print(titulo)
    for fonte, arquivos in resumo:
        status = "ativa" if fonte["ativo"] else "conectada, nao importa automaticamente"
        print(f"- {fonte['caminho']} | {status} | arquivos={len(arquivos)}")
        if fonte["observacao"]:
            print(f"  obs: {fonte['observacao']}")

        for caminho in arquivos[:amostra]:
            print(f"  {caminho}")
        if len(arquivos) > amostra:
            print(f"  ... mais {len(arquivos) - amostra} arquivo(s)")


def atualizar_arquivos(listar_arquivos=False):
    fontes_banco = fontes_configuradas(
        "pastas_banco",
        BANCO_ENTRADA_DIR,
        EXTENSOES_BANCO,
    )
    fontes_sistema = fontes_configuradas(
        "pastas_sistema",
        SISTEMA_ENTRADA_DIR,
        EXTENSOES_SISTEMA,
    )

    bancos, resumo_bancos = coletar_arquivos(
        fontes_banco,
        incluir_inativas=listar_arquivos,
    )
    sistemas, resumo_sistemas = coletar_arquivos(
        fontes_sistema,
        incluir_inativas=listar_arquivos,
    )

    print("Atualizando arquivos das pastas de entrada...")
    imprimir_resumo_fontes("Fontes de banco:", resumo_bancos)
    imprimir_resumo_fontes("Fontes de sistema:", resumo_sistemas)

    if listar_arquivos:
        print()
        print("Modo listagem: nenhum arquivo foi importado.")
        return

    if not bancos and not sistemas:
        print("Nenhum arquivo novo nas pastas de entrada.")

    for caminho in bancos:
        imprimir_resultado_arquivo(importar_banco(caminho))

    for caminho in sistemas:
        imprimir_resultado_arquivo(importar_sistema(caminho))


def atualizar_clinux(inicio, fim):
    print()
    print("Atualizando Clinux/Genesis em modo incremental...")
    resultado = importar_clinux(
        inicio=date.fromisoformat(inicio),
        fim=date.fromisoformat(fim),
        empresa_id=2,
        empresa_clinux=1,
        todas_empresas=True,
        substituir_xls=False,
        substituir_clinux=False,
        somente_novos=True,
    )

    print(f"Pagamentos novos lidos: {resultado['pagamentos_lidos']}")
    print(f"Transferencias novas geradas: {resultado['transferencias_lidas']}")
    print(f"Inseridos na base local: {resultado['inseridos']}")
    print(f"Ja existentes: {resultado['existentes']}")
    print(f"Maior pagamento anterior: {resultado['maior_pagamento_anterior']}")
    print(f"Maior transferencia anterior: {resultado['maior_transferencia_anterior']}")


def main():
    parser = ArgumentParser(
        description="Atualiza a base historica com arquivos novos e dados novos do Clinux."
    )
    parser.add_argument("--inicio", default=inicio_padrao_ultimos_12_meses())
    parser.add_argument("--fim", default=date.today().isoformat())
    parser.add_argument(
        "--sem-clinux",
        action="store_true",
        help="Atualiza somente arquivos das pastas de entrada.",
    )
    parser.add_argument(
        "--somente-clinux",
        action="store_true",
        help="Atualiza somente dados novos do Clinux/Genesis.",
    )
    parser.add_argument(
        "--listar-arquivos",
        action="store_true",
        help="Lista as fontes e arquivos encontrados, sem importar nada.",
    )
    args = parser.parse_args()

    garantir_pastas()

    if not args.somente_clinux:
        atualizar_arquivos(listar_arquivos=args.listar_arquivos)

    if not args.sem_clinux and not args.listar_arquivos:
        atualizar_clinux(args.inicio, args.fim)

    print()
    print("Atualizacao concluida.")


if __name__ == "__main__":
    try:
        main()
    except Exception as erro:
        print(f"Erro ao atualizar a base: {erro}")
        sys.exit(1)
