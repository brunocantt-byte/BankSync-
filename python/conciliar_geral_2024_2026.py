from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import csv
import json
import os

import psycopg
from dotenv import load_dotenv

from conciliar_cora import (
    aplicar_observacao_valor_igual,
    buscar_subconjunto_por_soma,
    calcular_score,
    centavos,
    cnpj_raiz_igual,
    data_compativel_fornecedor,
    data_proxima,
    documento_compativel,
    documento_igual,
    fornecedor_compativel,
    normalizar_texto,
    somente_digitos,
    regra_tributo_caixa,
    sistema_tributo_caixa,
    banco_caixa_economica,
    explicar_relacao_palavras,
)


BASE_DIR = Path(r"C:\ConciliaFinanceira")
SAIDA_DIR = BASE_DIR / "conciliados" / "ultimos_12_meses"
PERIODO_INICIO = date(2025, 9, 1)
PERIODO_FIM = date(2026, 9, 1)
MAX_CANDIDATOS_VALOR = 250
MAX_CANDIDATOS_GRUPO = 18
MAX_CANDIDATOS_SCORE = 30


@dataclass(frozen=True)
class Banco:
    id: int
    data: date
    tipo: str
    valor: Decimal
    descricao: str
    documento: str
    banco_nome: str
    agencia: str
    conta: str
    empresa: str
    arquivo: str

    def tuple_score(self):
        return (self.id, self.data, self.tipo, self.valor, self.descricao, self.documento)


@dataclass(frozen=True)
class Sistema:
    id: int
    data: date
    tipo: str
    valor: Decimal
    favorecido: str
    descricao: str
    documento: str
    empresa: str
    categoria: str
    centro_custo: str
    sistema_origem: str
    status: str

    def tuple_score(self):
        return (
            self.id,
            self.data,
            self.tipo,
            self.valor,
            self.favorecido,
            self.descricao,
            self.documento,
        )


def conectar():
    load_dotenv(BASE_DIR / ".env")
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def carregar_dados(periodo_inicio=PERIODO_INICIO, periodo_fim=PERIODO_FIM):
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    tb.id,
                    tb.data_movimento,
                    tb.tipo_movimento,
                    tb.valor,
                    COALESCE(tb.descricao, ''),
                    COALESCE(tb.documento, ''),
                    COALESCE(b.nome, ''),
                    COALESCE(cb.agencia, ''),
                    COALESCE(cb.conta, '') || CASE WHEN COALESCE(cb.digito, '') <> '' THEN '-' || cb.digito ELSE '' END,
                    COALESCE(e.razao_social, ''),
                    COALESCE(ai.caminho_arquivo, '')
                FROM transacoes_bancarias tb
                LEFT JOIN contas_bancarias cb ON cb.id = tb.conta_bancaria_id
                LEFT JOIN bancos b ON b.id = cb.banco_id
                LEFT JOIN empresas e ON e.id = cb.empresa_id
                LEFT JOIN arquivos_importados ai ON ai.id = tb.arquivo_id
                WHERE tb.data_movimento BETWEEN %s AND %s
                ORDER BY tb.data_movimento, tb.id
                """,
                (periodo_inicio, periodo_fim),
            )
            bancos = [
                Banco(*row)
                for row in cur.fetchall()
                if row[2] in ("ENTRADA", "SAIDA")
            ]

            cur.execute(
                """
                SELECT
                    l.id,
                    COALESCE(l.data_pagamento, l.data_lancamento),
                    l.tipo_movimento,
                    l.valor,
                    COALESCE(l.fornecedor_cliente, ''),
                    COALESCE(l.descricao, ''),
                    COALESCE(l.cnpj_cpf, l.documento, ''),
                    COALESCE(e.razao_social, ''),
                    COALESCE(l.categoria, ''),
                    COALESCE(l.centro_custo, ''),
                    COALESCE(l.sistema_origem, ''),
                    COALESCE(l.status, '')
                FROM lancamentos_sistema l
                LEFT JOIN empresas e ON e.id = l.empresa_id
                WHERE COALESCE(l.data_pagamento, l.data_lancamento) BETWEEN %s AND %s
                  AND COALESCE(l.status, '') <> 'CANCELADO'
                ORDER BY COALESCE(l.data_pagamento, l.data_lancamento), l.id
                """,
                (periodo_inicio, periodo_fim),
            )
            sistemas = [
                Sistema(*row)
                for row in cur.fetchall()
                if row[2] in ("ENTRADA", "SAIDA") and row[1] is not None
            ]
    return bancos, sistemas


def chave_doc(valor):
    doc = somente_digitos(valor)
    if len(doc) == 14:
        return doc[:8]
    return doc


def indexar_sistemas(sistemas):
    por_tipo_valor = defaultdict(list)
    por_doc_tipo_valor = defaultdict(list)
    por_doc_tipo_mes = defaultdict(list)
    por_tipo_mes = defaultdict(list)
    por_tipo_mes_valor = defaultdict(list)

    for sistema in sistemas:
        valor = centavos(sistema.valor)
        mes = (sistema.data.year, sistema.data.month)
        doc = chave_doc(sistema.documento)
        por_tipo_valor[(sistema.tipo, valor)].append(sistema)
        por_tipo_mes[(sistema.tipo, mes)].append(sistema)
        por_tipo_mes_valor[(sistema.tipo, mes, valor)].append(sistema)
        if doc:
            por_doc_tipo_valor[(doc, sistema.tipo, valor)].append(sistema)
            por_doc_tipo_mes[(doc, sistema.tipo, mes)].append(sistema)

    return {
        "tipo_valor": por_tipo_valor,
        "doc_tipo_valor": por_doc_tipo_valor,
        "doc_tipo_mes": por_doc_tipo_mes,
        "tipo_mes": por_tipo_mes,
        "tipo_mes_valor": por_tipo_mes_valor,
    }


def texto_sistema(sistema):
    return " ".join(
        parte
        for parte in (sistema.favorecido, sistema.descricao, sistema.categoria)
        if parte
    )


def candidato_sort(banco, sistema):
    score, metodo, divergencia = score_match_fast(banco, sistema)
    fornecedor_ok, texto_score = fornecedor_compativel(
        banco.descricao,
        sistema.favorecido,
        sistema.descricao,
    )
    return (
        -score,
        abs((banco.data - sistema.data).days),
        0 if documento_igual(banco.documento, sistema.documento) else 1,
        0 if fornecedor_ok else 1,
        -texto_score,
        sistema.id,
    )


def score_match_fast(banco, sistema):
    if banco.tipo != sistema.tipo:
        return 0, "TIPO_DIFERENTE", False
    if banco.valor != sistema.valor:
        if documento_compativel(banco.documento, sistema.documento) and data_proxima(banco.data, sistema.data):
            return 60, "CNPJ_DATA_VALOR_DIFERENTE", True
        return 0, "SEM_CORRESPONDENCIA", False

    data_diferenca = abs((banco.data - sistema.data).days)
    docs_iguais = documento_igual(banco.documento, sistema.documento)
    docs_compativeis = documento_compativel(banco.documento, sistema.documento)

    if docs_iguais and data_diferenca == 0:
        return 100, "CNPJ_VALOR_DATA", False
    if docs_iguais and data_diferenca <= 3:
        return 95, "CNPJ_VALOR_DATA_APROXIMADA", False

    fornecedor_ok, _ = fornecedor_compativel(
        banco.descricao,
        sistema.favorecido,
        sistema.descricao,
    )

    if docs_compativeis and fornecedor_ok:
        return 96, "CNPJ_VALOR_FORNECEDOR_DATA_DIFERENTE", False
    if docs_compativeis:
        return 88, "CNPJ_VALOR_DATA_DIFERENTE", False

    if regra_tributo_caixa(banco.tuple_score(), sistema.tuple_score()):
        if data_diferenca <= 3:
            return 94, "VALOR_TRIBUTO_CAIXA_DATA", False
        return 92, "VALOR_TRIBUTO_CAIXA_MES", False

    if fornecedor_ok and data_diferenca == 0:
        return 90, "VALOR_DATA_TEXTO", False
    if fornecedor_ok and data_diferenca <= 3:
        return 85, "VALOR_DATA_TEXTO_APROXIMADA", False
    if fornecedor_ok:
        return 82, "VALOR_FORNECEDOR_DATA_DIFERENTE", False
    if data_diferenca == 0:
        return 80, "VALOR_DATA", False
    if data_diferenca <= 3:
        return 75, "VALOR_DATA_APROXIMADA", False
    if explicar_relacao_palavras(banco.descricao, sistema.favorecido, sistema.descricao):
        return 74, "VALOR_IGUAL_PALAVRAS_RELACIONADAS_INFO_DIFERENTE", False
    return 70, "VALOR_IGUAL_INFO_DIFERENTE", False


def classificar(score, metodo, divergencia):
    if divergencia:
        return "DIVERGENCIA"
    if score >= 95:
        return "CONCILIADO"
    if metodo.startswith("VALOR_") or metodo == "CNPJ_VALOR_DATA_DIFERENTE":
        return "CONCILIADO_VALOR_IGUAL"
    if score >= 80:
        return "POSSIVEL_CORRESPONDENCIA"
    if score >= 70:
        return "POSSIVEL_REVISAO"
    return "NAO_ENCONTRADO"


def melhor_um_para_um(banco, indices, sistemas_usados):
    valor = centavos(banco.valor)
    doc = chave_doc(banco.documento)
    candidatos = []

    if doc:
        candidatos.extend(indices["doc_tipo_valor"].get((doc, banco.tipo, valor), []))

    meses = {
        ((banco.data + timedelta(days=deslocamento)).year, (banco.data + timedelta(days=deslocamento)).month)
        for deslocamento in range(-3, 4)
    }
    meses.add((banco.data.year, banco.data.month))
    for mes in meses:
        candidatos.extend(indices["tipo_mes_valor"].get((banco.tipo, mes, valor), []))

    vistos = set()
    validos = []
    for sistema in candidatos:
        if sistema.id in sistemas_usados or sistema.id in vistos:
            continue
        vistos.add(sistema.id)
        validos.append(sistema)

    if not validos:
        return None

    validos = sorted(
        validos,
        key=lambda sistema: (
            0 if documento_compativel(banco.documento, sistema.documento) else 1,
            abs((banco.data - sistema.data).days),
            sistema.id,
        ),
    )[:MAX_CANDIDATOS_SCORE]

    pontuados = []
    for sistema in validos:
        score, metodo, divergencia = score_match_fast(banco, sistema)
        if score > 0:
            pontuados.append((score, metodo, divergencia, sistema))

    if not pontuados:
        return None

    score, metodo, divergencia, sistema = sorted(
        pontuados,
        key=lambda item: candidato_sort(banco, item[3]),
    )[0]

    return {
        "banco": banco,
        "sistema": sistema,
        "bancos": [],
        "sistemas": [],
        "score": score,
        "metodo": metodo,
        "status": classificar(score, metodo, divergencia),
        "divergencia": divergencia,
    }


def procurar_grupo_sistema(banco, indices, sistemas_usados):
    candidatos = []
    doc = chave_doc(banco.documento)
    mes = (banco.data.year, banco.data.month)

    if doc:
        candidatos.extend(indices["doc_tipo_mes"].get((doc, banco.tipo, mes), []))
    elif banco_caixa_economica(banco.tuple_score()):
        candidatos.extend(indices["tipo_mes"].get((banco.tipo, mes), []))
    else:
        return None

    filtrados = []
    vistos = set()
    for sistema in candidatos:
        if sistema.id in sistemas_usados or sistema.id in vistos:
            continue
        vistos.add(sistema.id)
        if sistema.valor >= banco.valor:
            continue
        if not data_compativel_fornecedor(banco.data, sistema.data):
            continue
        if documento_compativel(banco.documento, sistema.documento):
            filtrados.append(sistema)
            continue
        if banco_caixa_economica(banco.tuple_score()):
            if sistema_tributo_caixa(sistema.tuple_score()):
                filtrados.append(sistema)
            continue
        fornecedor_ok, _ = fornecedor_compativel(
            banco.descricao,
            sistema.favorecido,
            sistema.descricao,
        )
        if fornecedor_ok:
            filtrados.append(sistema)

    if len(filtrados) < 2:
        return None

    filtrados = sorted(
        filtrados,
        key=lambda sistema: (
            0 if documento_compativel(banco.documento, sistema.documento) else 1,
            abs((banco.data - sistema.data).days),
            sistema.valor,
            sistema.id,
        ),
    )[:MAX_CANDIDATOS_GRUPO]

    grupo = buscar_subconjunto_por_soma(
        [sistema.tuple_score() for sistema in filtrados],
        banco.valor,
    )
    if not grupo:
        return None

    ids = {item[0] for item in grupo}
    sistemas = [sistema for sistema in filtrados if sistema.id in ids]
    metodo = "AGRUPAMENTO_SISTEMA_VALOR"
    obs = "Conciliado por soma exata de parcelas do Sistema contra um lançamento do Banco."
    if banco_caixa_economica(banco.tuple_score()) and any(sistema_tributo_caixa(s.tuple_score()) for s in sistemas):
        metodo = "AGRUPAMENTO_SISTEMA_TRIBUTO_CAIXA_VALOR"
        obs = "Tributo/encargo associado a CAIXA ECONOMICA; parcelas do Sistema somam exatamente o valor do Banco."
    elif any(documento_compativel(banco.documento, s.documento) for s in sistemas):
        metodo = "AGRUPAMENTO_SISTEMA_CNPJ_VALOR"
    return {
        "banco": banco,
        "sistema": sistemas[0],
        "bancos": [],
        "sistemas": sistemas,
        "score": 98,
        "metodo": metodo,
        "status": "CONCILIADO",
        "divergencia": False,
        "observacao": obs,
    }


def quantidade_observacao(banco, sistema):
    doc_banco = chave_doc(banco.documento)
    doc_sistema = chave_doc(sistema.documento)
    if not doc_banco or doc_banco != doc_sistema:
        return ""
    return ""


def conciliar_periodo(periodo_inicio, periodo_fim):
    bancos, sistemas = carregar_dados(periodo_inicio, periodo_fim)
    indices = indexar_sistemas(sistemas)
    bancos_usados = set()
    sistemas_usados = set()
    resultados = []

    for banco in bancos:
        if banco.id in bancos_usados:
            continue
        match = melhor_um_para_um(banco, indices, sistemas_usados)
        if not match:
            continue
        compat = aplicar_observacao_valor_igual(
            {
                "banco": match["banco"].tuple_score(),
                "sistema": match["sistema"].tuple_score(),
                "score": match["score"],
                "metodo": match["metodo"],
                "status": match["status"],
                "divergencia": match["divergencia"],
            }
        )
        if compat.get("observacao"):
            match["observacao"] = compat["observacao"]
        resultados.append(match)
        bancos_usados.add(banco.id)
        sistemas_usados.add(match["sistema"].id)

    for banco in bancos:
        if banco.id in bancos_usados:
            continue
        grupo = procurar_grupo_sistema(banco, indices, sistemas_usados)
        if not grupo:
            continue
        resultados.append(grupo)
        bancos_usados.add(banco.id)
        sistemas_usados.update(sistema.id for sistema in grupo.get("sistemas", []))

    for banco in bancos:
        if banco.id in bancos_usados:
            continue
        resultados.append(
            {
                "banco": banco,
                "sistema": None,
                "bancos": [],
                "sistemas": [],
                "score": 0,
                "metodo": "SEM_CORRESPONDENCIA",
                "status": "NAO_ENCONTRADO",
                "divergencia": False,
            }
        )

    return bancos, sistemas, resultados, sistemas_usados


def meses_periodo():
    atual = date(PERIODO_INICIO.year, PERIODO_INICIO.month, 1)
    final = date(PERIODO_FIM.year, PERIODO_FIM.month, 1)
    while atual <= final:
        if atual.month == 12:
            proximo = date(atual.year + 1, 1, 1)
        else:
            proximo = date(atual.year, atual.month + 1, 1)
        yield atual, min(proximo - timedelta(days=1), PERIODO_FIM)
        atual = proximo


def conciliar():
    todos_bancos = []
    todos_sistemas = []
    todos_resultados = []
    todos_sistemas_usados = set()

    for inicio, fim in meses_periodo():
        bancos, sistemas, resultados, sistemas_usados = conciliar_periodo(inicio, fim)
        todos_bancos.extend(bancos)
        todos_sistemas.extend(sistemas)
        todos_resultados.extend(resultados)
        todos_sistemas_usados.update(sistemas_usados)
        print(
            f"{inicio:%Y-%m}: banco={len(bancos)} sistema={len(sistemas)} "
            f"matches={sum(1 for item in resultados if item.get('sistema'))}",
            flush=True,
        )

    return todos_bancos, todos_sistemas, todos_resultados, todos_sistemas_usados


def dinheiro(valor):
    return f"{Decimal(valor):.2f}"


def ids(itens):
    return ", ".join(str(item.id) for item in itens)


def datas(itens):
    return ", ".join(sorted({str(item.data) for item in itens}))


def docs(itens):
    return ", ".join(sorted({item.documento for item in itens if item.documento}))


def desc_banco(itens):
    return " | ".join(item.descricao for item in itens if item.descricao)


def desc_sistema(itens):
    return " | ".join(
        f"{item.favorecido} - {item.descricao}".strip(" -")
        for item in itens
        if item.favorecido or item.descricao
    )


def linha_match(item):
    banco = item["banco"]
    sistema = item["sistema"]
    bancos = item.get("bancos") or [banco]
    sistemas = item.get("sistemas") or ([sistema] if sistema else [])
    valor_banco = sum(item.valor for item in bancos)
    valor_sistema = sum(item.valor for item in sistemas)
    observacao = item.get("observacao", "")
    if item["status"] == "CONCILIADO_VALOR_IGUAL" and not observacao:
        observacao = "Conciliado automaticamente por valor igual; validar demais informacoes."

    return {
        "status": item["status"],
        "score": item["score"],
        "metodo": item["metodo"],
        "banco_id": ids(bancos),
        "banco_data": datas(bancos),
        "banco_tipo": banco.tipo,
        "banco_valor": dinheiro(valor_banco),
        "banco_documento": docs(bancos),
        "banco_banco": banco.banco_nome,
        "banco_conta": banco.conta,
        "banco_empresa": banco.empresa,
        "banco_descricao": desc_banco(bancos),
        "sistema_id": ids(sistemas),
        "sistema_data": datas(sistemas),
        "sistema_tipo": sistema.tipo if sistema else "",
        "sistema_valor": dinheiro(valor_sistema) if sistemas else "",
        "sistema_documento": docs(sistemas),
        "sistema_empresa": sistema.empresa if sistema else "",
        "sistema_favorecido_descricao": desc_sistema(sistemas),
        "sistema_categoria": sistema.categoria if sistema else "",
        "sistema_centro_custo": sistema.centro_custo if sistema else "",
        "sistema_origem": sistema.sistema_origem if sistema else "",
        "diferenca_valor": dinheiro(valor_banco - valor_sistema) if sistemas else "",
        "observacao": observacao,
    }


def linha_banco_sem_sistema(item):
    banco = item["banco"]
    return {
        "banco_id": banco.id,
        "data": banco.data,
        "tipo": banco.tipo,
        "valor": dinheiro(banco.valor),
        "documento": banco.documento,
        "banco": banco.banco_nome,
        "conta": banco.conta,
        "empresa": banco.empresa,
        "descricao": banco.descricao,
    }


def linha_sistema_sem_banco(sistema):
    return {
        "sistema_id": sistema.id,
        "data": sistema.data,
        "tipo": sistema.tipo,
        "valor": dinheiro(sistema.valor),
        "documento": sistema.documento,
        "empresa": sistema.empresa,
        "favorecido": sistema.favorecido,
        "descricao": sistema.descricao,
        "categoria": sistema.categoria,
        "centro_custo": sistema.centro_custo,
        "sistema_origem": sistema.sistema_origem,
    }


def chave_dup_banco(banco):
    doc = chave_doc(banco.documento)
    texto = doc or " ".join(normalizar_texto(banco.descricao).split()[:6])
    return ("BANCO", banco.tipo, banco.data.year, banco.data.month, centavos(banco.valor), texto)


def chave_dup_sistema(sistema):
    doc = chave_doc(sistema.documento)
    texto = doc or " ".join(normalizar_texto(texto_sistema(sistema)).split()[:6])
    return ("SISTEMA", sistema.tipo, sistema.data.year, sistema.data.month, centavos(sistema.valor), texto)


def encontrar_duplicidades(bancos, sistemas):
    grupos = defaultdict(list)
    for banco in bancos:
        grupos[chave_dup_banco(banco)].append(banco)
    for sistema in sistemas:
        grupos[chave_dup_sistema(sistema)].append(sistema)

    linhas = []
    for chave, itens in grupos.items():
        if len(itens) < 2:
            continue
        origem, tipo, ano, mes, valor_cent, chave_texto = chave
        linhas.append(
            {
                "origem": origem,
                "periodo": f"{ano}-{mes:02d}",
                "tipo": tipo,
                "valor": dinheiro(Decimal(valor_cent) / 100),
                "quantidade": len(itens),
                "ids": ids(itens),
                "chave": chave_texto,
                "observacao": "Possivel duplicidade: mesmo mes, tipo, valor e documento/texto-base.",
            }
        )
    return linhas


def escrever_csv(caminho, linhas, campos):
    with caminho.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=campos, delimiter=";")
        writer.writeheader()
        writer.writerows(linhas)


def resumo_totais(bancos, sistemas, resultados, sistemas_usados):
    status = Counter(item["status"] for item in resultados)
    banco_sem = status["NAO_ENCONTRADO"]
    sistema_sem = len(sistemas) - len(sistemas_usados)
    conciliados = status["CONCILIADO"] + status["CONCILIADO_VALOR_IGUAL"]
    return [
        {"indicador": "Periodo analisado", "valor": f"{PERIODO_INICIO} a {PERIODO_FIM}"},
        {"indicador": "Quantidade Banco", "valor": len(bancos)},
        {"indicador": "Quantidade Sistema", "valor": len(sistemas)},
        {"indicador": "Banco entradas", "valor": dinheiro(sum(b.valor for b in bancos if b.tipo == "ENTRADA"))},
        {"indicador": "Banco saidas", "valor": dinheiro(sum(b.valor for b in bancos if b.tipo == "SAIDA"))},
        {"indicador": "Sistema entradas", "valor": dinheiro(sum(s.valor for s in sistemas if s.tipo == "ENTRADA"))},
        {"indicador": "Sistema saidas", "valor": dinheiro(sum(s.valor for s in sistemas if s.tipo == "SAIDA"))},
        {"indicador": "Conciliados", "valor": conciliados},
        {"indicador": "Conciliados por valor igual para validar", "valor": status["CONCILIADO_VALOR_IGUAL"]},
        {"indicador": "Possiveis correspondencias", "valor": status["POSSIVEL_CORRESPONDENCIA"]},
        {"indicador": "Possiveis revisoes", "valor": status["POSSIVEL_REVISAO"]},
        {"indicador": "Divergencias", "valor": status["DIVERGENCIA"]},
        {"indicador": "Banco sem Sistema", "valor": banco_sem},
        {"indicador": "Sistema sem Banco", "valor": sistema_sem},
        {"indicador": "% Banco conciliado", "valor": f"{(conciliados / len(bancos) if bancos else 0):.4f}"},
    ]


def main():
    SAIDA_DIR.mkdir(parents=True, exist_ok=True)
    bancos, sistemas, resultados, sistemas_usados = conciliar()
    matches = [linha_match(item) for item in resultados if item.get("sistema")]
    valor_igual = [row for row in matches if row["status"] == "CONCILIADO_VALOR_IGUAL"]
    divergencias = [row for row in matches if row["status"] == "DIVERGENCIA"]
    banco_sem = [linha_banco_sem_sistema(item) for item in resultados if item["status"] == "NAO_ENCONTRADO"]
    sistema_sem = [linha_sistema_sem_banco(s) for s in sistemas if s.id not in sistemas_usados]
    duplicidades = encontrar_duplicidades(bancos, sistemas)
    resumo = resumo_totais(bancos, sistemas, resultados, sistemas_usados)

    campos_match = list(matches[0].keys()) if matches else []
    escrever_csv(SAIDA_DIR / "01_resumo.csv", resumo, ["indicador", "valor"])
    escrever_csv(SAIDA_DIR / "02_conciliados.csv", matches, campos_match)
    escrever_csv(SAIDA_DIR / "03_valor_igual_validar.csv", valor_igual, campos_match)
    escrever_csv(SAIDA_DIR / "04_divergencias.csv", divergencias, campos_match)
    escrever_csv(SAIDA_DIR / "05_banco_sem_sistema.csv", banco_sem, list(banco_sem[0].keys()) if banco_sem else [])
    escrever_csv(SAIDA_DIR / "06_sistema_sem_banco.csv", sistema_sem, list(sistema_sem[0].keys()) if sistema_sem else [])
    escrever_csv(SAIDA_DIR / "07_duplicidades.csv", duplicidades, list(duplicidades[0].keys()) if duplicidades else [])

    print(json.dumps({
        "saida": str(SAIDA_DIR),
        "banco": len(bancos),
        "sistema": len(sistemas),
        "matches": len(matches),
        "valor_igual_validar": len(valor_igual),
        "divergencias": len(divergencias),
        "banco_sem_sistema": len(banco_sem),
        "sistema_sem_banco": len(sistema_sem),
        "duplicidades": len(duplicidades),
        "status": dict(Counter(item["status"] for item in resultados)),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
