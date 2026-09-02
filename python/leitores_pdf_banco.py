from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import logging
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unicodedata

import pdfplumber


logging.getLogger("pdfminer").setLevel(logging.ERROR)

TESSERACT_EXE = Path(os.getenv("TESSERACT_EXE", r"C:\Program Files\Tesseract-OCR\tesseract.exe"))
POPPLER_PATH = Path(os.getenv("POPPLER_PATH", ""))


@dataclass
class ExtracaoPDFBanco:
    banco_nome: str
    layout: str
    transacoes: list[dict]
    banco_codigo: str | None = None
    empresa_nome: str | None = None
    empresa_cnpj: str | None = None
    agencia: str | None = None
    conta: str | None = None
    digito: str | None = None
    avisos: list[str] = field(default_factory=list)


def normalizar_texto(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(
        caractere
        for caractere in sem_acento
        if not unicodedata.combining(caractere)
    )
    return sem_acento.upper()


def converter_valor_texto(valor: str) -> Decimal:
    valor_limpo = valor.replace("R$", "").replace(" ", "").strip()
    if "," in valor_limpo:
        valor_limpo = valor_limpo.replace(".", "").replace(",", ".")
    return Decimal(valor_limpo)


def valor_para_csv(valor: Decimal) -> str:
    return f"{valor:.2f}"


def extrair_documento(texto: str) -> str:
    padrao = (
        r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}"
        r"|"
        r"\d{3}\.\d{3}\.\d{3}-\d{2}"
        r"|"
        r"\b\d{11,14}\b"
    )

    resultado = re.search(padrao, texto)
    return resultado.group(0) if resultado else ""


def separar_conta(conta_texto: str) -> tuple[str, str | None]:
    conta_limpa = conta_texto.strip().replace(".", "")
    if "-" not in conta_limpa:
        return conta_limpa, None

    conta, digito = conta_limpa.rsplit("-", 1)
    return conta.strip(), digito.strip()


def texto_pdf(caminho: Path) -> list[tuple[int, list[str]]]:
    paginas = []
    with pdfplumber.open(caminho) as pdf:
        for pagina_numero, pagina in enumerate(pdf.pages, start=1):
            texto = pagina.extract_text(x_tolerance=1, y_tolerance=3) or ""
            linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
            paginas.append((pagina_numero, linhas))
    return paginas


def texto_pdf_ocr(caminho: Path) -> list[tuple[int, list[str]]]:
    if not TESSERACT_EXE.exists():
        return []

    try:
        from pdf2image import convert_from_path
    except ModuleNotFoundError:
        return []

    paginas = []
    poppler_path = str(POPPLER_PATH) if POPPLER_PATH.exists() else None

    with tempfile.TemporaryDirectory() as tmpdir:
        imagens = convert_from_path(
            str(caminho),
            dpi=220,
            fmt="png",
            poppler_path=poppler_path,
        )

        for pagina_numero, imagem in enumerate(imagens, start=1):
            imagem_path = Path(tmpdir) / f"pagina_{pagina_numero:04d}.png"
            imagem.save(imagem_path)
            resultado = subprocess.run(
                [
                    str(TESSERACT_EXE),
                    str(imagem_path),
                    "stdout",
                    "-l",
                    "eng",
                    "--psm",
                    "6",
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            texto = resultado.stdout if resultado.returncode == 0 else ""
            linhas = [
                linha.strip()
                for linha in texto.splitlines()
                if linha.strip()
            ]
            paginas.append((pagina_numero, linhas))

    return paginas


def todas_linhas(paginas: list[tuple[int, list[str]]]) -> list[tuple[int, str]]:
    return [
        (pagina, linha)
        for pagina, linhas in paginas
        for linha in linhas
    ]


def criar_transacao(data, tipo, valor, descricao, documento="", pagina=1):
    return {
        "data": data,
        "tipo_movimento": tipo,
        "valor": valor_para_csv(abs(valor)),
        "descricao": re.sub(r"\s+", " ", descricao).strip(),
        "documento": documento or extrair_documento(descricao),
        "pagina": pagina,
    }


def extrair_cora(caminho: Path, paginas) -> ExtracaoPDFBanco:
    linhas = todas_linhas(paginas)
    texto = "\n".join(linha for _, linha in linhas)

    empresa_nome = linhas[0][1] if linhas else None
    empresa_cnpj = None
    agencia = None
    conta = None
    digito = None

    cnpj = re.search(r"CNPJ\s+(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", texto)
    if cnpj:
        empresa_cnpj = cnpj.group(1)

    conta_match = re.search(
        r"Ag[êe]ncia:\s*(\d+)\s*-\s*Conta:\s*([\d.]+)-?(\d+)?",
        texto,
        flags=re.IGNORECASE,
    )
    if conta_match:
        agencia = conta_match.group(1)
        conta = conta_match.group(2)
        digito = conta_match.group(3)

    padrao_data = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+Saldo do dia\s+R\$")
    padrao_movimento = re.compile(
        r"(?P<descricao>.+?)\s(?P<sinal>[+-])\sR\$\s(?P<valor>[\d.]+,\d{2})$"
    )

    data_atual = None
    transacoes = []
    for pagina, linha in linhas:
        data = padrao_data.match(linha)
        if data:
            data_atual = data.group(1)
            continue

        movimento = padrao_movimento.match(linha)
        if not movimento or not data_atual:
            continue

        valor = converter_valor_texto(movimento.group("valor"))
        tipo = "ENTRADA" if movimento.group("sinal") == "+" else "SAIDA"
        transacoes.append(
            criar_transacao(
                data_atual,
                tipo,
                valor,
                movimento.group("descricao"),
                pagina=pagina,
            )
        )

    return ExtracaoPDFBanco(
        banco_nome="BANCO CORA",
        banco_codigo=None,
        layout="CORA",
        empresa_nome=empresa_nome,
        empresa_cnpj=empresa_cnpj,
        agencia=agencia,
        conta=conta,
        digito=digito,
        transacoes=transacoes,
    )


def extrair_clinux(caminho: Path, paginas) -> ExtracaoPDFBanco:
    linhas = todas_linhas(paginas)
    texto = "\n".join(linha for _, linha in linhas)
    banco_nome = "BANCO CLINUX"
    empresa_nome = linhas[0][1] if linhas else None
    empresa_cnpj = None

    cnpj = re.search(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", texto)
    if cnpj:
        empresa_cnpj = cnpj.group(0)

    banco = re.search(r"BANCO:\s*(.+?)\s+-\s+PERIODO:", texto, flags=re.IGNORECASE)
    if banco:
        banco_nome = banco.group(1).strip()

    padrao = re.compile(
        r"^(\d{2}/\d{2}/\d{4})\s+(?P<descricao>.+?)\s+(?P<valor>-?[\d.]+,\d{2})$"
    )
    transacoes = []

    for pagina, linha in linhas:
        if "SALDO INICIAL" in normalizar_texto(linha):
            continue

        resultado = padrao.match(linha)
        if not resultado:
            continue

        descricao = resultado.group("descricao").strip()
        if descricao.replace("*", "").strip() == "":
            continue

        valor = converter_valor_texto(resultado.group("valor"))
        tipo = "SAIDA" if valor < 0 else "ENTRADA"
        transacoes.append(
            criar_transacao(
                resultado.group(1),
                tipo,
                valor,
                descricao,
                pagina=pagina,
            )
        )

    return ExtracaoPDFBanco(
        banco_nome=banco_nome,
        layout="CLINUX_EXTRATO_BANCO",
        empresa_nome=empresa_nome,
        empresa_cnpj=empresa_cnpj,
        transacoes=transacoes,
        avisos=[
            "Este PDF parece ser relatorio do Clinux/Genesis, nao extrato oficial do banco."
        ],
    )


def extrair_bradesco(caminho: Path, paginas) -> ExtracaoPDFBanco:
    linhas = todas_linhas(paginas)
    texto = "\n".join(linha for _, linha in linhas)
    empresa_nome = None
    empresa_cnpj = None
    agencia = None
    conta = None
    digito = None

    empresa = re.search(r"^(.+?)\s+\|\s+CNPJ:\s*(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", texto, re.MULTILINE)
    if empresa:
        empresa_nome = empresa.group(1).strip()
        empresa_cnpj = empresa.group(2)

    conta_match = re.search(r"(\d{3,5})\s+\|\s+([\d.]+-\d)", texto)
    if conta_match:
        agencia = conta_match.group(1).lstrip("0") or conta_match.group(1)
        conta, digito = separar_conta(conta_match.group(2))

    row_data = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\S+)\s+(-?[\d.]+,\d{2})\s+(-?[\d.]+,\d{2})$")
    row_sem_data = re.compile(r"^(\S+)\s+(-?[\d.]+,\d{2})\s+(-?[\d.]+,\d{2})$")
    ignorar = ("SALDO ANTERIOR", "SALDO", "DATA LAN", "EXTRATO", "BANCO BRADESCO")

    transacoes = []
    pendentes = []
    data_atual = None
    ultima = None
    dentro_tabela = False

    for pagina, linha in linhas:
        linha_norm = normalizar_texto(linha)
        if "DATA LANCAMENTO" in linha_norm and "SALDO" in linha_norm:
            dentro_tabela = True
            pendentes = []
            continue
        if not dentro_tabela:
            continue
        if any(linha_norm.startswith(item) for item in ignorar):
            continue

        if ultima and re.match(r"^(REM|DEST|PAGADOR|FAV|BENEF):", linha_norm):
            ultima["descricao"] = f"{ultima['descricao']} {linha}"
            if not ultima["documento"]:
                ultima["documento"] = extrair_documento(ultima["descricao"])
            continue

        resultado = row_data.match(linha)
        if resultado:
            data_atual = resultado.group(1)
            documento = resultado.group(2)
            valor = converter_valor_texto(resultado.group(3))
        else:
            resultado = row_sem_data.match(linha)
            if not resultado or not data_atual:
                if not re.search(r"[\d.]+,\d{2}", linha):
                    pendentes.append(linha)
                continue
            documento = resultado.group(1)
            valor = converter_valor_texto(resultado.group(2))

        descricao = " ".join(pendentes) or documento
        pendentes = []
        tipo = "SAIDA" if valor < 0 else "ENTRADA"
        ultima = criar_transacao(data_atual, tipo, valor, descricao, documento, pagina)
        transacoes.append(ultima)

    return ExtracaoPDFBanco(
        banco_nome="BANCO BRADESCO",
        banco_codigo="237",
        layout="BRADESCO_NET_EMPRESA",
        empresa_nome=empresa_nome,
        empresa_cnpj=empresa_cnpj,
        agencia=agencia,
        conta=conta,
        digito=digito,
        transacoes=transacoes,
    )


def extrair_caixa(caminho: Path, paginas) -> ExtracaoPDFBanco:
    linhas = todas_linhas(paginas)
    texto = "\n".join(linha for _, linha in linhas)
    empresa_nome = None
    agencia = None
    conta = None
    digito = None

    empresa = re.search(r"Cliente:\s*(.+)", texto)
    if empresa:
        empresa_nome = empresa.group(1).strip()

    conta_match = re.search(r"Conta:\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([\d.]+-\d)", texto)
    if conta_match:
        agencia = conta_match.group(1)
        conta, digito = separar_conta(conta_match.group(3))
    else:
        conta_match = re.search(
            r"Ag[êe]ncia:\s*(\d+)\s*/\s*Produto:\s*\d+\s*/\s*Conta:\s*([\d.]+-\d)",
            texto,
            flags=re.IGNORECASE,
        )
        if conta_match:
            agencia = conta_match.group(1)
            conta, digito = separar_conta(conta_match.group(2))

    padrao_atual = re.compile(
        r"^(\d{2}/\d{2}/\d{4})\s+(\S+)\s+(.+?)\s+([\d.]+,\d{2})\s+([CD])\s+[\d.]+,\d{2}\s+[CD]$"
    )
    padrao_antigo = re.compile(
        r"^(\d{2}/\d{2}/\d{4})\s+\d{2}/\d{2}/\d{4}\s+(\S+)\s+(.+?)\s+(-?[\d.]+\.\d{2})\s+-?[\d.]+\.\d{2}$"
    )
    transacoes = []

    for pagina, linha in linhas:
        resultado_atual = padrao_atual.match(linha)
        if resultado_atual:
            descricao = resultado_atual.group(3)
            if normalizar_texto(descricao).startswith("SALDO"):
                continue

            valor = converter_valor_texto(resultado_atual.group(4))
            tipo = "ENTRADA" if resultado_atual.group(5) == "C" else "SAIDA"
            transacoes.append(
                criar_transacao(
                    resultado_atual.group(1),
                    tipo,
                    valor,
                    descricao,
                    resultado_atual.group(2),
                    pagina,
                )
            )
            continue

        resultado_antigo = padrao_antigo.match(linha)
        if resultado_antigo:
            descricao = resultado_antigo.group(3)
            if normalizar_texto(descricao).startswith("SALDO"):
                continue

            valor = converter_valor_texto(resultado_antigo.group(4))
            tipo = "SAIDA" if valor < 0 else "ENTRADA"
            transacoes.append(
                criar_transacao(
                    resultado_antigo.group(1),
                    tipo,
                    valor,
                    descricao,
                    resultado_antigo.group(2),
                    pagina,
                )
            )

    return ExtracaoPDFBanco(
        banco_nome="CAIXA ECONOMICA FEDERAL",
        banco_codigo="104",
        layout="CAIXA_GERENCIADOR",
        empresa_nome=empresa_nome,
        agencia=agencia,
        conta=conta,
        digito=digito,
        transacoes=transacoes,
    )


def extrair_banco_do_brasil(caminho: Path, paginas) -> ExtracaoPDFBanco:
    linhas = todas_linhas(paginas)
    texto = "\n".join(linha for _, linha in linhas)
    agencia = None
    conta = None
    digito = None
    empresa_nome = None

    agencia_match = re.search(r"Ag[êe]ncia\s+([\d-]+)", texto)
    if agencia_match:
        agencia = agencia_match.group(1)

    conta_match = re.search(r"Conta corrente\s+([\d.-]+)\s*(.*)", texto)
    if conta_match:
        conta, digito = separar_conta(conta_match.group(1))
        empresa_nome = conta_match.group(2).strip() or None

    row = re.compile(
        r"^(\d{2}/\d{2}/\d{4})\s+\d{4}\s+\d+\s+\d+\s+(.+?)\s+([\d.]+,\d{2})\s+([CD])(?:\s+[\d.]+,\d{2}\s+[CD])?$"
    )
    complemento = re.compile(r"^\d{2}/\d{2}\s+\d{2}:\d{2}\s+(.+)$")
    transacoes = []
    ultima = None

    for pagina, linha in linhas:
        resultado = row.match(linha)
        if resultado:
            descricao = resultado.group(2).strip()
            if "Saldo Anterior" in descricao:
                ultima = None
                continue

            valor = converter_valor_texto(resultado.group(3))
            tipo = "ENTRADA" if resultado.group(4) == "C" else "SAIDA"
            ultima = criar_transacao(resultado.group(1), tipo, valor, descricao, pagina=pagina)
            transacoes.append(ultima)
            continue

        extra = complemento.match(linha)
        if extra and ultima:
            ultima["descricao"] = f"{ultima['descricao']} {extra.group(1).strip()}"
            if not ultima["documento"]:
                ultima["documento"] = extrair_documento(ultima["descricao"])

    return ExtracaoPDFBanco(
        banco_nome="BANCO DO BRASIL",
        banco_codigo="001",
        layout="BANCO_DO_BRASIL_CONTA_CORRENTE",
        empresa_nome=empresa_nome,
        agencia=agencia,
        conta=conta,
        digito=digito,
        transacoes=transacoes,
    )


def extrair_basa(caminho: Path, paginas) -> ExtracaoPDFBanco:
    linhas = todas_linhas(paginas)
    texto = "\n".join(linha for _, linha in linhas)
    agencia = None
    conta = None
    digito = None
    empresa_nome = None

    agencia_match = re.search(r"Ag[êe]ncia:\s*(\d+)", texto)
    if agencia_match:
        agencia = agencia_match.group(1)

    conta_match = re.search(r"Conta:\s*([\d.]+-\d)", texto)
    if conta_match:
        conta, digito = separar_conta(conta_match.group(1))

    cliente = re.search(r"Nome do Cliente:\s*(.+)", texto)
    if cliente:
        empresa_nome = cliente.group(1).strip()

    row = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\S+)\s*(.*?)\s*R\$\s*([\d.]+,\d{2})\s*(.*)$")
    pendentes = []
    transacoes = []
    ultima = None
    dentro_movimentacoes = False

    for pagina, linha in linhas:
        linha_norm = normalizar_texto(linha)
        if "MOVIMENTACOES" in linha_norm:
            dentro_movimentacoes = True
            continue
        if dentro_movimentacoes and linha_norm in ("SALDOS", "SALDO ATUAL", "= SALDO DISPONIVEL"):
            dentro_movimentacoes = False
        if not dentro_movimentacoes:
            continue

        if "SALDO DO DIA" in linha_norm or "SALDO ATUAL" in linha_norm or "SALDO ANTERIOR" in linha_norm:
            continue

        resultado = row.match(linha)
        if resultado:
            valor = converter_valor_texto(resultado.group(4))
            cauda = resultado.group(5)
            tipo = "SAIDA" if ("" in cauda or "D" in cauda) else "ENTRADA"
            descricao = " ".join(pendentes + [resultado.group(3)]).strip()
            pendentes = []
            ultima = criar_transacao(
                resultado.group(1),
                tipo,
                valor,
                descricao or resultado.group(2),
                resultado.group(2),
                pagina,
            )
            transacoes.append(ultima)
            continue

        if ultima and linha_norm not in ("DETALHES DA", "DATA DOCUMENTO HISTORICO VALOR SALDO", "TRANSACAO"):
            ultima["descricao"] = f"{ultima['descricao']} {linha}".strip()
        elif linha_norm not in ("DETALHES DA", "DATA DOCUMENTO HISTORICO VALOR SALDO", "TRANSACAO"):
            pendentes.append(linha)

    return ExtracaoPDFBanco(
        banco_nome="BANCO DA AMAZONIA",
        banco_codigo="003",
        layout="BASA_AMAZONIA_ONLINE",
        empresa_nome=empresa_nome,
        agencia=agencia,
        conta=conta,
        digito=digito,
        transacoes=transacoes,
    )


def extrair_sicoob(caminho: Path, paginas) -> ExtracaoPDFBanco:
    linhas = todas_linhas(paginas)
    texto = "\n".join(linha for _, linha in linhas)
    empresa_nome = None
    conta = None
    digito = None
    ano = None

    conta_match = re.search(r"CONTA:\s*([\d.]+-\d)\s*/\s*(.+)", texto)
    if conta_match:
        conta, digito = separar_conta(conta_match.group(1))
        empresa_nome = conta_match.group(2).strip()

    periodo = re.search(r"PER[IÍ]ODO:\s*\d{2}/\d{2}/(\d{4})", texto, flags=re.IGNORECASE)
    if periodo:
        ano = periodo.group(1)

    row = re.compile(r"^(\d{2}/\d{2})\s+(.+?)\s+([\d.]+,\d{2})([CD])$")
    transacoes = []
    ultima = None

    for pagina, linha in linhas:
        resultado = row.match(linha)
        if resultado and ano:
            descricao = resultado.group(2)
            if normalizar_texto(descricao).startswith("SALDO"):
                ultima = None
                continue

            valor = converter_valor_texto(resultado.group(3))
            tipo = "ENTRADA" if resultado.group(4) == "C" else "SAIDA"
            ultima = criar_transacao(
                f"{resultado.group(1)}/{ano}",
                tipo,
                valor,
                descricao,
                pagina=pagina,
            )
            transacoes.append(ultima)
            continue

        if ultima and linha.startswith("DOC.:"):
            ultima["documento"] = linha.replace("DOC.:", "").strip()
        elif ultima and not re.search(r"[\d.]+,\d{2}[CD]$", linha):
            ultima["descricao"] = f"{ultima['descricao']} {linha}".strip()

    return ExtracaoPDFBanco(
        banco_nome="SICOOB",
        banco_codigo="756",
        layout="SICOOB_SISBR",
        empresa_nome=empresa_nome,
        conta=conta,
        digito=digito,
        transacoes=transacoes,
    )


def extrair_safra(caminho: Path, paginas) -> ExtracaoPDFBanco:
    linhas = todas_linhas(paginas)
    texto = "\n".join(linha for _, linha in linhas)
    empresa_nome = None
    empresa_cnpj = None
    agencia = None
    conta = None
    digito = None
    ano = None

    empresa = re.search(r"Extrato de Movimenta[çc][aã]o\s+(.+)", texto)
    if empresa:
        empresa_nome = empresa.group(1).strip()

    conta_match = re.search(
        r"CNPJ:\s*([\d./-]+)\s*\|\s*AG:\s*(\d+)\s*\|\s*CONTA:\s*([\d.]+-\d)",
        texto,
        flags=re.IGNORECASE,
    )
    if conta_match:
        empresa_cnpj = conta_match.group(1)
        agencia = conta_match.group(2)
        conta, digito = separar_conta(conta_match.group(3))

    periodo = re.search(r"Per[ií]odo de \d{2}/\d{2}/(\d{4})", texto, flags=re.IGNORECASE)
    if periodo:
        ano = periodo.group(1)

    row = re.compile(r"^(\d{2}/\d{2})\s+(.+?)\s+(-?[\d.]+,\d{2})$")
    transacoes = []
    dentro_tabela = False
    ultima = None

    for pagina, linha in linhas:
        linha_norm = normalizar_texto(linha)
        if "LANCAMENTOS REALIZADOS" in linha_norm:
            dentro_tabela = True
            continue
        if not dentro_tabela or not ano:
            continue
        if linha_norm.startswith("DATA LANCAMENTO") or linha_norm.startswith("BANCO SAFRA"):
            continue

        resultado = row.match(linha)
        if resultado:
            descricao = resultado.group(2).strip()
            if normalizar_texto(descricao).startswith("SALDO"):
                ultima = None
                continue

            valor = converter_valor_texto(resultado.group(3))
            tipo = "SAIDA" if valor < 0 else "ENTRADA"
            ultima = criar_transacao(
                f"{resultado.group(1)}/{ano}",
                tipo,
                valor,
                descricao,
                pagina=pagina,
            )
            transacoes.append(ultima)
            continue

        if ultima and re.fullmatch(r"[\d.\s-]{8,}", linha):
            ultima["descricao"] = f"{ultima['descricao']} {linha}".strip()

    return ExtracaoPDFBanco(
        banco_nome="BANCO SAFRA",
        banco_codigo="422",
        layout="SAFRA_EXTRATO_MOVIMENTACAO",
        empresa_nome=empresa_nome,
        empresa_cnpj=empresa_cnpj,
        agencia=agencia,
        conta=conta,
        digito=digito,
        transacoes=transacoes,
    )


def extrair_stone(caminho: Path, paginas) -> ExtracaoPDFBanco:
    linhas = todas_linhas(paginas)
    texto = "\n".join(linha for _, linha in linhas)
    empresa_nome = None
    empresa_cnpj = None
    agencia = None
    conta = None
    digito = None

    cabecalho = re.search(
        r"Titular\s+(.+?)\s+Institui[çc][aã]o\s+Stone.+?Documento\s+(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\s+Ag[êe]ncia\s+(\d+)",
        texto,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if cabecalho:
        empresa_nome = cabecalho.group(1).strip()
        empresa_cnpj = cabecalho.group(2)
        agencia = cabecalho.group(3)

    conta_match = re.search(r"Conta\s+([\d.]+-\d)", texto)
    if conta_match:
        conta, digito = separar_conta(conta_match.group(1))

    row = re.compile(
        r"^(\d{2}/\d{2}/\d{4})\s+(Cr[eé]dito|D[eé]bito)\s+([\d.]+,\d{2})\s+(-?[\d.]+,\d{2})$",
        flags=re.IGNORECASE,
    )
    transacoes = []
    descricao_pendente = []
    ultima = None

    for pagina, linha in linhas:
        linha_norm = normalizar_texto(linha)
        if linha_norm.startswith(("DATA TIPO", "INFORMACOES DO COMPROVANTE", "CODIGO DE AUTENTICACAO")):
            descricao_pendente = []
            continue

        resultado = row.match(linha)
        if resultado:
            valor = converter_valor_texto(resultado.group(3))
            tipo_credito = normalizar_texto(resultado.group(2)).startswith("CREDITO")
            tipo = "ENTRADA" if tipo_credito else "SAIDA"
            descricao = " ".join(descricao_pendente) or resultado.group(2)
            descricao_pendente = []
            ultima = criar_transacao(
                resultado.group(1),
                tipo,
                valor,
                descricao,
                pagina=pagina,
            )
            transacoes.append(ultima)
            continue

        if ultima and "|" in linha:
            ultima["descricao"] = f"{ultima['descricao']} {linha}".strip()
            continue

        if not re.search(r"\d{2}/\d{2}/\d{4}|[\d.]+,\d{2}", linha):
            descricao_pendente.append(linha)

    return ExtracaoPDFBanco(
        banco_nome="STONE",
        banco_codigo=None,
        layout="STONE_CONTA_CORRENTE",
        empresa_nome=empresa_nome,
        empresa_cnpj=empresa_cnpj,
        agencia=agencia,
        conta=conta,
        digito=digito,
        transacoes=transacoes,
    )


def extrair_bnb_conta_corrente(caminho: Path, paginas) -> ExtracaoPDFBanco:
    linhas = todas_linhas(paginas)
    texto = "\n".join(linha for _, linha in linhas)
    empresa_nome = None
    agencia = None
    conta = None
    digito = None

    titular = re.search(r"Titular:\s*(.+)", texto, flags=re.IGNORECASE)
    if titular:
        empresa_nome = titular.group(1).strip()

    conta_match = re.search(
        r"Ag[êe]ncia/Conta Corrente:\s*(\d+)\s*-\s*[^/]+/([\d.]+-\d)",
        texto,
        flags=re.IGNORECASE,
    )
    if conta_match:
        agencia = conta_match.group(1)
        conta, digito = separar_conta(conta_match.group(2))

    row = re.compile(
        r"^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(\d+)\s+(-?\s*[\d.]+,\d{2})\s+(-?\s*[\d.]+,\d{2})$"
    )
    row_doc_valor = re.compile(
        r"^(\d{2}/\d{2}/\d{4})\s+(\d+)\s+(-?\s*[\d.]+,\d{2})\s+(-?\s*[\d.]+,\d{2})$"
    )
    transacoes = []
    pendentes = []
    dentro_tabela = False

    for pagina, linha in linhas:
        linha_norm = normalizar_texto(linha)
        if "DATA HISTORICO DOCUMENTO VALOR" in linha_norm:
            dentro_tabela = True
            pendentes = []
            continue
        if linha_norm.startswith("DETALHAMENTO DO SALDO"):
            dentro_tabela = False
        if not dentro_tabela:
            continue

        resultado = row.match(linha)
        if resultado:
            descricao = " ".join(pendentes + [resultado.group(2)]).strip()
            pendentes = []
            valor = converter_valor_texto(resultado.group(4))
            tipo = "SAIDA" if valor < 0 else "ENTRADA"
            transacoes.append(
                criar_transacao(
                    resultado.group(1),
                    tipo,
                    valor,
                    descricao,
                    resultado.group(3),
                    pagina,
                )
            )
            continue

        resultado_doc_valor = row_doc_valor.match(linha)
        if resultado_doc_valor:
            descricao = " ".join(pendentes).strip() or resultado_doc_valor.group(2)
            pendentes = []
            valor = converter_valor_texto(resultado_doc_valor.group(3))
            tipo = "SAIDA" if valor < 0 else "ENTRADA"
            transacoes.append(
                criar_transacao(
                    resultado_doc_valor.group(1),
                    tipo,
                    valor,
                    descricao,
                    resultado_doc_valor.group(2),
                    pagina,
                )
            )
            continue

        if not re.match(r"^\d{2}/\d{2}/\d{4}", linha) and not linha_norm.startswith("::"):
            pendentes.append(linha)

    return ExtracaoPDFBanco(
        banco_nome="BANCO DO NORDESTE",
        banco_codigo="004",
        layout="BNB_CONTA_CORRENTE",
        empresa_nome=empresa_nome,
        agencia=agencia,
        conta=conta,
        digito=digito,
        transacoes=transacoes,
    )


def extrair_unicred_conta_corrente(caminho: Path, paginas) -> ExtracaoPDFBanco:
    linhas = todas_linhas(paginas)
    texto = "\n".join(linha for _, linha in linhas)
    empresa_nome = None
    conta = None

    conta_match = re.search(r"CONTA:\s*(\d+)", texto, flags=re.IGNORECASE)
    if conta_match:
        conta = conta_match.group(1)

    cliente = re.search(r"CLIENTE:\s*(.+?)(?:\n|USU[ÁA]RIO)", texto, flags=re.IGNORECASE | re.DOTALL)
    if cliente:
        empresa_nome = re.sub(r"\s+", " ", cliente.group(1)).strip()

    transacoes = []
    for pagina, linha in linhas:
        limpa = linha.replace("(cid:9)", " ")
        resultado = re.match(
            r"^(\d{2}/\d{2}/\d{4})\s+(\S+)\s+(.+?)\s+(-?[\d.]+,\d{2})\s+(-?[\d.]+,\d{2})$",
            limpa,
        )
        if not resultado:
            continue

        valor = converter_valor_texto(resultado.group(4))
        tipo = "SAIDA" if valor < 0 else "ENTRADA"
        transacoes.append(
            criar_transacao(
                resultado.group(1),
                tipo,
                valor,
                resultado.group(3),
                resultado.group(2),
                pagina,
            )
        )

    return ExtracaoPDFBanco(
        banco_nome="BANCO UNICRED",
        banco_codigo="136",
        layout="UNICRED_CONTA_CORRENTE",
        empresa_nome=empresa_nome,
        conta=conta,
        transacoes=transacoes,
    )


MESES = {
    "JAN": "01",
    "FEV": "02",
    "MAR": "03",
    "ABR": "04",
    "MAI": "05",
    "JUN": "06",
    "JUL": "07",
    "AGO": "08",
    "SET": "09",
    "OUT": "10",
    "NOV": "11",
    "DEZ": "12",
}


def extrair_itau(caminho: Path, paginas) -> ExtracaoPDFBanco:
    linhas = todas_linhas(paginas)
    texto = "\n".join(linha for _, linha in linhas)
    empresa_nome = None
    empresa_cnpj = None
    agencia = None
    conta = None
    digito = None
    ano = None

    cabecalho = re.search(
        r"^(.+?)\s+ag[êe]ncia\s+conta corrente\s+"
        r"(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\s+(\d+)\s+([\d.]+-\d)",
        texto,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if cabecalho:
        empresa_nome = cabecalho.group(1).strip()
        empresa_cnpj = cabecalho.group(2)
        agencia = cabecalho.group(3)
        conta, digito = separar_conta(cabecalho.group(4))
    else:
        cabecalho_novo = re.search(
            r"^(.+?)\s+CNPJ\s+Ag[êe]ncia\s+(\d+)\s+Conta\s+([\d.]+-\d)\s*\n"
            r"(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})",
            texto,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if cabecalho_novo:
            empresa_nome = cabecalho_novo.group(1).strip()
            agencia = cabecalho_novo.group(2)
            conta, digito = separar_conta(cabecalho_novo.group(3))
            empresa_cnpj = cabecalho_novo.group(4)
        else:
            conta_simples = re.search(
                r"(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\s+(\d{3,5})\s+([\d.]+-\d)",
                texto,
            )
            if conta_simples:
                empresa_cnpj = conta_simples.group(1)
                agencia = conta_simples.group(2)
                conta, digito = separar_conta(conta_simples.group(3))

    periodo = re.search(
        r"lan[çc]amentos(?:\s+do)?\s+per[ií]odo:\s*\d{2}/\d{2}/(\d{4})",
        texto,
        flags=re.IGNORECASE,
    )
    if periodo:
        ano = periodo.group(1)
    else:
        ano_match = re.search(r"\b(20\d{2})\b", texto)
        if ano_match:
            ano = ano_match.group(1)

    row_antigo = re.compile(
        r"^(\d{2})\s*/\s*([a-zç]{3})\s+(.+?)\s+(-?[\d.]+,\d{2})$",
        flags=re.IGNORECASE,
    )
    row_novo = re.compile(
        r"^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?[\d.]+,\d{2})$"
    )
    ignorar_descricoes = (
        "SALDO ANTERIOR",
        "SALDO DO DIA",
        "SALDO TOTAL",
        "SALDO DISPON",
        "SDO CTA/APL",
    )

    transacoes = []
    dentro_tabela = False
    pendentes = []

    for pagina, linha in linhas:
        linha_norm = normalizar_texto(linha)
        if (
            "DATA LANCAMENTOS" in linha_norm and "VALOR" in linha_norm
            or "DATA LANGAMENTOS" in linha_norm and "VALOR" in linha_norm
        ):
            dentro_tabela = True
            continue
        if linha_norm.startswith("SALDO DA CONTA CORRENTE"):
            dentro_tabela = False
        if not dentro_tabela or not ano:
            continue

        resultado_antigo = row_antigo.match(linha)
        if resultado_antigo:
            descricao = resultado_antigo.group(3).strip()
            descricao_norm = normalizar_texto(descricao)
            if any(descricao_norm.startswith(item) for item in ignorar_descricoes):
                pendentes = []
                continue

            mes = MESES.get(normalizar_texto(resultado_antigo.group(2))[:3])
            if not mes:
                continue

            valor = converter_valor_texto(resultado_antigo.group(4))
            tipo = "SAIDA" if valor < 0 else "ENTRADA"
            transacoes.append(
                criar_transacao(
                    f"{resultado_antigo.group(1)}/{mes}/{ano}",
                    tipo,
                    valor,
                    descricao,
                    pagina=pagina,
                )
            )
            pendentes = []
            continue

        resultado_novo = row_novo.match(linha)
        if resultado_novo:
            descricao = " ".join(pendentes + [resultado_novo.group(2)]).strip()
            pendentes = []
            descricao_norm = normalizar_texto(descricao)
            if any(descricao_norm.startswith(item) for item in ignorar_descricoes):
                continue

            valor = converter_valor_texto(resultado_novo.group(3))
            tipo = "SAIDA" if valor < 0 else "ENTRADA"
            transacoes.append(
                criar_transacao(
                    resultado_novo.group(1),
                    tipo,
                    valor,
                    descricao,
                    pagina=pagina,
                )
            )
            continue

        if not re.search(r"R\$\s*[\d.]+,\d{2}|[\d.]+,\d{2}$", linha):
            pendentes.append(linha)

    return ExtracaoPDFBanco(
        banco_nome="BANCO ITAU",
        banco_codigo="341",
        layout="ITAU_CONTA_CORRENTE",
        empresa_nome=empresa_nome,
        empresa_cnpj=empresa_cnpj,
        agencia=agencia,
        conta=conta,
        digito=digito,
        transacoes=transacoes,
    )


def extrair_pdf_sem_movimento_transacional(caminho: Path, paginas) -> ExtracaoPDFBanco:
    texto = "\n".join(linha for _, linha in todas_linhas(paginas))
    texto_norm = normalizar_texto(texto)

    if "UNICRED" in texto_norm:
        banco_nome = "BANCO UNICRED"
        banco_codigo = "136"
        layout = "UNICRED_RENTABILIDADE"
    elif "ITAU" in texto_norm:
        banco_nome = "BANCO ITAU"
        banco_codigo = "341"
        layout = "ITAU_DEMONSTRATIVO_APLICACAO"
    elif "CDB CAIXA" in texto_norm or "INFORMATIVO MENSAL CDB" in texto_norm:
        banco_nome = "CAIXA ECONOMICA FEDERAL"
        banco_codigo = "104"
        layout = "CAIXA_DEMONSTRATIVO_APLICACAO"
    elif "BANCO DO NORDESTE" in texto_norm or "BNB" in texto_norm:
        banco_nome = "BANCO DO NORDESTE"
        banco_codigo = "004"
        layout = "BNB_CONSOLIDADO_INVESTIMENTO"
    else:
        banco_nome = "BANCO NAO IDENTIFICADO"
        banco_codigo = None
        layout = "DEMONSTRATIVO_SEM_MOVIMENTO_TRANSACIONAL"

    return ExtracaoPDFBanco(
        banco_nome=banco_nome,
        banco_codigo=banco_codigo,
        layout=layout,
        transacoes=[],
        avisos=[
            "PDF identificado como demonstrativo/resumo sem lancamentos transacionais para conciliacao bancaria."
        ],
    )


def extrair_caixa_novo(caminho: Path, paginas) -> ExtracaoPDFBanco:
    linhas = todas_linhas(paginas)
    texto = "\n".join(linha for _, linha in linhas)
    empresa_nome = None
    empresa_cnpj = None
    agencia = None
    conta = None
    digito = None

    if linhas:
        empresa_nome = linhas[0][1]

    cnpj = re.search(r"CNPJ:\s*(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", texto)
    if cnpj:
        empresa_cnpj = cnpj.group(1)

    conta_match = re.search(r"Ag[êe]ncia:\s*(\d+)\s+Conta:\s*([\d.]+-\d)", texto, re.IGNORECASE)
    if conta_match:
        agencia = conta_match.group(1).lstrip("0") or conta_match.group(1)
        conta, digito = separar_conta(conta_match.group(2))

    transacoes = []
    pendentes = []
    item_atual = None
    dentro_tabela = False

    for pagina, linha in linhas:
        linha_norm = normalizar_texto(linha)
        if "DOCUMENTO HISTORICO" in linha_norm or "DATA EFETIVA" in linha_norm:
            dentro_tabela = True
            pendentes = []
            continue
        if not dentro_tabela:
            continue
        if "SALDO DIA" in linha_norm or "SALDO ANTERIOR" in linha_norm:
            continue

        data_sozinha = re.match(r"^(\d{2}/\d{2}/\d{4})(\s+-)?$", linha)
        if data_sozinha:
            item_atual = {
                "data": data_sozinha.group(1),
                "descricao": " ".join(pendentes).strip(),
                "documento": "",
                "pagina": pagina,
                "sinal": "-" if data_sozinha.group(2) else "+",
            }
            pendentes = []
            continue

        simples = re.match(
            r"^(\d{2}/\d{2}/\d{4})\s+(\S+)\s+(.+?)\s+(-?\s*)?R\$\s*([\d.]+,\d{2})\s+R\$\s*[\d.]+,\d{2}\s*[CD]?$",
            linha,
        )
        if simples:
            descricao = simples.group(3)
            valor = converter_valor_texto((simples.group(4) or "") + simples.group(5))
            tipo = "SAIDA" if valor < 0 else "ENTRADA"
            transacoes.append(
                criar_transacao(
                    simples.group(1),
                    tipo,
                    valor,
                    descricao,
                    simples.group(2),
                    pagina,
                )
            )
            continue

        valor_quebrado = re.search(r"R\$\s*([\d.]+,\d{2})$", linha)
        if item_atual and valor_quebrado:
            valor = converter_valor_texto(valor_quebrado.group(1))
            tipo = "SAIDA" if item_atual["sinal"] == "-" else "ENTRADA"
            descricao = item_atual["descricao"].rstrip("-").strip()
            transacoes.append(
                criar_transacao(
                    item_atual["data"],
                    tipo,
                    valor,
                    descricao,
                    item_atual["documento"],
                    item_atual["pagina"],
                )
            )
            item_atual = None
            continue

        if item_atual and re.match(r"^\d{6}\s+", linha):
            linha_sem_saldo = re.sub(r"R\$\s*[\d.]+,\d{2}\s*[CD]?$", "", linha).strip()
            partes = linha_sem_saldo.split(maxsplit=1)
            item_atual["documento"] = partes[0]
            item_atual["descricao"] = f"{item_atual['descricao']} {partes[1]}".strip()
            continue

        if re.match(r"^\d{2}/\d{2}\s+\d{2}:\d{2}", linha):
            continue

        if not re.match(r"^\d{2}/\d{2}/\d{4}", linha) and not re.search(r"R\$", linha):
            pendentes.append(linha)

    return ExtracaoPDFBanco(
        banco_nome="CAIXA ECONOMICA FEDERAL",
        banco_codigo="104",
        layout="CAIXA_EXTRATO_NOVO",
        empresa_nome=empresa_nome,
        empresa_cnpj=empresa_cnpj,
        agencia=agencia,
        conta=conta,
        digito=digito,
        transacoes=transacoes,
    )


def extrair_unicred_novo(caminho: Path, paginas) -> ExtracaoPDFBanco:
    linhas = todas_linhas(paginas)
    texto = "\n".join(linha for _, linha in linhas)
    empresa_nome = None
    agencia = None
    conta = None

    conta_match = re.search(r"Coop:\s*\d+\s*-\s*AG:\s*(\d+)\s*-\s*Conta:\s*(\d+)", texto, re.IGNORECASE)
    if conta_match:
        agencia = conta_match.group(1)
        conta = conta_match.group(2)

    titular = re.search(r"Extrato\s+(.+?)\s+Per[ií]odo", texto, re.IGNORECASE | re.DOTALL)
    if titular:
        empresa_nome = re.sub(r"\s+", " ", titular.group(1)).strip()

    row = re.compile(
        r"^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?\s*)?R\$\s*([\d.]+,\d{2})\s+R\$\s*[\d.]+,\d{2}$"
    )
    row_valor_quebrado = re.compile(
        r"^(\d{2}/\d{2}/\d{4})\s+(-?\s*)?R\$\s*([\d.]+,\d{2})\s+R\$\s*[\d.]+,\d{2}$"
    )
    transacoes = []
    pendentes = []
    dentro_tabela = False

    for pagina, linha in linhas:
        linha_norm = normalizar_texto(linha)
        if "DATA LANCAMENTOS VALOR" in linha_norm:
            dentro_tabela = True
            pendentes = []
            continue
        if linha_norm.startswith("CENTRAL DE RELACIONAMENTO"):
            dentro_tabela = False
        if not dentro_tabela:
            continue

        resultado_quebrado = row_valor_quebrado.match(linha)
        if resultado_quebrado:
            descricao = " ".join(pendentes).strip()
            pendentes = []
            valor = converter_valor_texto(
                (resultado_quebrado.group(2) or "") + resultado_quebrado.group(3)
            )
            tipo = "SAIDA" if valor < 0 else "ENTRADA"
            documento = ""
            doc = re.search(r"Doc\.?:\s*([^)]+)", descricao, re.IGNORECASE)
            if doc:
                documento = doc.group(1).strip()
            transacoes.append(
                criar_transacao(
                    resultado_quebrado.group(1),
                    tipo,
                    valor,
                    descricao,
                    documento,
                    pagina,
                )
            )
            continue

        resultado = row.match(linha)
        if resultado:
            descricao = " ".join(pendentes + [resultado.group(2)]).strip()
            pendentes = []
            valor = converter_valor_texto((resultado.group(3) or "") + resultado.group(4))
            tipo = "SAIDA" if valor < 0 else "ENTRADA"
            documento = ""
            doc = re.search(r"Doc\.?:\s*([^)]+)", descricao, re.IGNORECASE)
            if doc:
                documento = doc.group(1).strip()
            transacoes.append(
                criar_transacao(
                    resultado.group(1),
                    tipo,
                    valor,
                    descricao,
                    documento,
                    pagina,
                )
            )
            continue

        if (
            not re.match(r"^\d{2}/\d{2}/\d{4}", linha)
            and not linha_norm.startswith(("CENTRAL DE RELACIONAMENTO", "SALDO", "LIMITE"))
        ):
            pendentes.append(linha)

    return ExtracaoPDFBanco(
        banco_nome="BANCO UNICRED",
        banco_codigo="136",
        layout="UNICRED_CONTA_CORRENTE_NOVO",
        empresa_nome=empresa_nome,
        agencia=agencia,
        conta=conta,
        transacoes=transacoes,
    )


def extrair_uniprime(caminho: Path, paginas) -> ExtracaoPDFBanco:
    linhas = todas_linhas(paginas)
    texto = "\n".join(linha for _, linha in linhas)
    empresa_nome = None
    agencia = None
    conta = None
    digito = None

    conta_match = re.search(r"Conta Corrente:\s*([\d.]+-\d)", texto, re.IGNORECASE)
    if conta_match:
        conta, digito = separar_conta(conta_match.group(1))

    agencia_match = re.search(r"Ag[êe]ncia:\s*(\d+)", texto, re.IGNORECASE)
    if agencia_match:
        agencia = agencia_match.group(1)

    coop = re.search(r"Cooperado:\s*(.+?)\s+Usu[áa]rio:", texto, re.IGNORECASE)
    if coop:
        empresa_nome = coop.group(1).strip()

    row = re.compile(
        r"^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+([\d.]+,\d{2})\s+([+-])\s+[-\d.,]+(?:\s+[+-])?$"
    )
    transacoes = []

    for pagina, linha in linhas:
        resultado = row.match(linha)
        if not resultado:
            continue

        corpo = resultado.group(2).strip()
        documento = ""
        descricao = corpo
        partes = corpo.split(maxsplit=1)
        if partes and re.fullmatch(r"\d+", partes[0]):
            documento = partes[0]
            descricao = partes[1] if len(partes) > 1 else partes[0]

        valor = converter_valor_texto(resultado.group(3))
        tipo = "ENTRADA" if resultado.group(4) == "+" else "SAIDA"
        transacoes.append(
            criar_transacao(
                resultado.group(1),
                tipo,
                valor,
                descricao,
                documento,
                pagina,
            )
        )

    return ExtracaoPDFBanco(
        banco_nome="BANCO UNIPRIME",
        banco_codigo="099",
        layout="UNIPRIME_CONTA_CORRENTE",
        empresa_nome=empresa_nome,
        agencia=agencia,
        conta=conta,
        digito=digito,
        transacoes=transacoes,
    )


def detectar_layout(caminho: Path, paginas) -> str:
    texto = "\n".join(linha for _, linha in todas_linhas(paginas))
    texto_norm = normalizar_texto(texto)
    nome_norm = normalizar_texto(caminho.name)

    if "EXTRATO BANCO USUARIO" in texto_norm or "CLINUX - SISTEMA DE GESTAO" in texto_norm:
        return "CLINUX_EXTRATO_BANCO"
    if "AGENCIA:" in texto_norm and "CONTA:" in texto_norm and "CORA" in texto_norm:
        return "CORA"
    if "GEREN_CIADOR CAI_XA" in texto_norm or "EXTRATO POR PERIODO" in texto_norm and ("CAIXA" in texto_norm or "CONTA:" in texto_norm):
        return "CAIXA_GERENCIADOR"
    if "EXTRATO NO PERIODO" in texto_norm and "CAIXA" in nome_norm:
        return "CAIXA_EXTRATO_NOVO"
    if "CONSULTAS - EXTRATO DE CONTA CORRENTE" in texto_norm and ("BANCO DO BRASIL" in texto_norm or "CONTA CORRENTE" in texto_norm):
        return "BANCO_DO_BRASIL_CONTA_CORRENTE"
    if "BANCO DO BRASIL" in nome_norm or re.search(r"\bBB\b", nome_norm):
        return "BANCO_DO_BRASIL_CONTA_CORRENTE"
    if "EXTRATO DE CONTA CORRENTE - NO PERIODO" in texto_norm and "BANCO DO NORDESTE" in nome_norm:
        return "BNB_CONTA_CORRENTE"
    if "AGENCIA/CONTA CORRENTE" in texto_norm and "DETALHAMENTO DO EXTRATO" in texto_norm:
        return "BNB_CONTA_CORRENTE"
    if "EXTRATO DE CONTA CORRENTE PARA SIMPLES CONFERENCIA" in texto_norm and "UNICRED" in texto_norm:
        return "UNICRED_CONTA_CORRENTE"
    if "DATA LANCAMENTOS VALOR" in texto_norm and "UNICRED" in nome_norm:
        return "UNICRED_CONTA_CORRENTE_NOVO"
    if "COOPERATIVA UNIPRIME" in texto_norm or "UNIPRIME" in nome_norm and "CONTA CORRENTE" in texto_norm:
        return "UNIPRIME_CONTA_CORRENTE"
    if "BANCO BRADESCO" in texto_norm or "BRADESCO" in nome_norm:
        return "BRADESCO_NET_EMPRESA"
    if "BANCO DA AMAZONIA" in texto_norm or "AMAZONIA ONLINE" in texto_norm or "BASA" in nome_norm:
        return "BASA_AMAZONIA_ONLINE"
    if "SICOOB" in texto_norm:
        return "SICOOB_SISBR"
    if "BANCO SAFRA" in texto_norm or "SAFRA" in nome_norm:
        return "SAFRA_EXTRATO_MOVIMENTACAO"
    if "INSTITUICAO STONE" in texto_norm or "STONE" in nome_norm and "EXTRATO DE CONTA CORRENTE" in texto_norm:
        return "STONE_CONTA_CORRENTE"
    if (
        "LANCAMENTOS DO PERIODO" in texto_norm
        or "LANGAMENTOS" in texto_norm and "ITAU" in texto_norm
        or "LANÇAMENTOS PERÍODO" in texto.upper()
        or "LANCAMENTOS PERIODO" in texto_norm and "ITAU" in nome_norm
    ):
        return "ITAU_CONTA_CORRENTE"
    if (
        "DEMONSTRATIVO DE RENTABILIDADE" in texto_norm
        or "EXTRATO CONSOLIDADO" in texto_norm
        or "INFORMATIVO MENSAL CDB" in texto_norm
        or "APLIC" in nome_norm
    ):
        return "DEMONSTRATIVO_SEM_MOVIMENTO_TRANSACIONAL"
    if not texto_norm.strip():
        return "PDF_SEM_TEXTO_EXTRAIVEL"

    return "NAO_SUPORTADO"


def extrair_pdf_bancario(caminho: Path) -> ExtracaoPDFBanco:
    paginas = texto_pdf(caminho)
    layout = detectar_layout(caminho, paginas)
    avisos_ocr = []

    if layout == "PDF_SEM_TEXTO_EXTRAIVEL":
        paginas_ocr = texto_pdf_ocr(caminho)
        if paginas_ocr and any(linhas for _, linhas in paginas_ocr):
            paginas = paginas_ocr
            layout = detectar_layout(caminho, paginas)
            avisos_ocr.append("Texto extraido por OCR.")

    leitores = {
        "CORA": extrair_cora,
        "CLINUX_EXTRATO_BANCO": extrair_clinux,
        "BRADESCO_NET_EMPRESA": extrair_bradesco,
        "CAIXA_GERENCIADOR": extrair_caixa,
        "BANCO_DO_BRASIL_CONTA_CORRENTE": extrair_banco_do_brasil,
        "BASA_AMAZONIA_ONLINE": extrair_basa,
        "SICOOB_SISBR": extrair_sicoob,
        "SAFRA_EXTRATO_MOVIMENTACAO": extrair_safra,
        "STONE_CONTA_CORRENTE": extrair_stone,
        "BNB_CONTA_CORRENTE": extrair_bnb_conta_corrente,
        "UNICRED_CONTA_CORRENTE": extrair_unicred_conta_corrente,
        "UNICRED_CONTA_CORRENTE_NOVO": extrair_unicred_novo,
        "UNIPRIME_CONTA_CORRENTE": extrair_uniprime,
        "ITAU_CONTA_CORRENTE": extrair_itau,
        "CAIXA_EXTRATO_NOVO": extrair_caixa_novo,
        "DEMONSTRATIVO_SEM_MOVIMENTO_TRANSACIONAL": extrair_pdf_sem_movimento_transacional,
    }

    leitor = leitores.get(layout)
    if not leitor:
        return ExtracaoPDFBanco(
            banco_nome="BANCO NAO IDENTIFICADO",
            layout=layout,
            transacoes=[],
            avisos=avisos_ocr + [f"Layout ainda nao suportado: {layout}"],
        )

    extracao = leitor(caminho, paginas)
    extracao.avisos = avisos_ocr + extracao.avisos
    if not extracao.transacoes:
        extracao.avisos.append("Nenhuma transacao foi extraida deste PDF.")
    return extracao
