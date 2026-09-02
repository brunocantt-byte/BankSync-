import os
import re
import unicodedata
from difflib import SequenceMatcher
from decimal import Decimal

import psycopg
from dotenv import load_dotenv


load_dotenv()

CONTA_BANCARIA_ID = 3
EMPRESA_ID = 2
SISTEMA_ORIGEM = "CLINUX"
LIMITE_AMOSTRA = 20
JANELA_DIAS = 3
JANELA_DIAS_FORNECEDOR = 45
MAX_CANDIDATOS_GRUPO = 14
MAX_CANDIDATOS_TRIBUTOS_CAIXA = 20
LIMITE_TEXTO_FORNECEDOR = 0.35

TERMOS_TRIBUTOS_CAIXA = {
    "darf",
    "imposto",
    "impostos",
    "tributo",
    "tributos",
    "irpf",
    "irpj",
    "irrf",
    "imposto renda",
    "simples",
    "simples nacional",
    "das",
    "fgts",
    "fundo garantia",
    "inss",
    "previdencia",
    "gps",
    "pis",
    "cofins",
    "csll",
    "ipi",
    "ipva",
    "icms",
    "itcmd",
    "licenciamento",
    "multa",
    "multas",
    "transito",
    "iptu",
    "iss",
    "issqn",
    "itbi",
    "alvara",
    "coleta lixo",
    "iluminacao publica",
    "taxa municipal",
    "taxas municipais",
}

CATEGORIAS_TEXTO = {
    "tecnologia": {
        "tecnologia",
        "informatica",
        "software",
        "hardware",
        "computador",
        "notebook",
        "impressora",
        "toner",
        "sistema",
        "internet",
        "digital",
        "dados",
        "licenca",
        "cloud",
        "nuvem",
    },
    "papelaria": {
        "papelaria",
        "papel",
        "caneta",
        "toner",
        "cartucho",
        "material",
        "expediente",
    },
    "escritorio": {
        "escritorio",
        "administrativo",
        "expediente",
        "material",
        "arquivo",
        "mobiliario",
        "cadeira",
        "mesa",
    },
    "limpeza": {
        "limpeza",
        "higiene",
        "descartavel",
        "conservacao",
        "sanitizante",
    },
    "manutencao": {
        "manutencao",
        "reparo",
        "servico",
        "peca",
        "instalacao",
        "conserto",
    },
    "transporte": {
        "transporte",
        "frete",
        "entrega",
        "corrida",
        "logistica",
        "combustivel",
        "gasolina",
        "diesel",
    },
    "alimentacao": {
        "alimentacao",
        "refeicao",
        "restaurante",
        "lanche",
        "mercado",
    },
    "saude": {
        "saude",
        "hospital",
        "clinica",
        "medico",
        "laboratorio",
        "medicamento",
        "exame",
        "cardiologia",
    },
    "tributos": {
        "darf",
        "imposto",
        "impostos",
        "tributo",
        "tributos",
        "taxa",
        "das",
        "gps",
        "fgts",
        "irrf",
        "irpf",
        "irpj",
        "inss",
        "iss",
        "issqn",
        "pis",
        "cofins",
        "csll",
        "ipi",
        "ipva",
        "icms",
        "itcmd",
        "iptu",
        "itbi",
        "alvara",
    },
    "servicos profissionais": {
        "contabilidade",
        "contador",
        "advogado",
        "juridico",
        "consultoria",
        "honorario",
    },
}


def conectar_banco():
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def somente_digitos(valor):
    if not valor:
        return ""

    return re.sub(r"\D", "", str(valor))


def normalizar_texto(valor):
    if not valor:
        return ""

    texto = unicodedata.normalize("NFKD", str(valor))
    texto = "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(caractere)
    )
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9]+", " ", texto)

    return re.sub(r"\s+", " ", texto).strip()


def similaridade(texto1, texto2):
    texto1 = normalizar_texto(texto1)
    texto2 = normalizar_texto(texto2)

    if not texto1 or not texto2:
        return 0

    return SequenceMatcher(None, texto1, texto2).ratio()


def tokens_relevantes(valor):
    texto = normalizar_texto(valor)
    ignorar = {
        "boleto",
        "pago",
        "pix",
        "pgto",
        "qr",
        "code",
        "transf",
        "transferencia",
        "enviada",
        "recebida",
        "ltda",
        "sa",
        "s",
        "a",
        "me",
        "eireli",
        "mei",
        "cpf",
        "cnpj",
    }

    return {
        token
        for token in texto.split()
        if len(token) >= 4
        and not token.isdigit()
        and token not in ignorar
    }


def fornecedor_compativel(texto_banco, favorecido, descricao_sistema):
    texto_sistema = " ".join(
        parte
        for parte in (
            favorecido,
            descricao_sistema,
        )
        if parte
    )

    score = similaridade(
        texto_banco,
        texto_sistema,
    )

    if score >= LIMITE_TEXTO_FORNECEDOR:
        return True, score

    tokens_banco = tokens_relevantes(texto_banco)
    tokens_sistema = tokens_relevantes(texto_sistema)

    if not tokens_banco or not tokens_sistema:
        return False, score

    intersecao = tokens_banco & tokens_sistema

    return len(intersecao) >= 1, score


def categorias_detectadas(valor):
    tokens = tokens_relevantes(valor)
    categorias = []

    for categoria, palavras in CATEGORIAS_TEXTO.items():
        if tokens & palavras:
            categorias.append(categoria)

    return set(categorias)


def contem_termo(texto, termos):
    texto = normalizar_texto(texto)

    if not texto:
        return False

    tokens = set(texto.split())

    for termo in termos:
        termo_normalizado = normalizar_texto(termo)

        if " " in termo_normalizado:
            if termo_normalizado in texto:
                return True
            continue

        if termo_normalizado in tokens:
            return True

    return False


def banco_caixa_economica(banco):
    texto = normalizar_texto(banco[4])

    return "caixa economica" in texto or (
        "caixa" in texto.split()
        and "economic" in texto
    )


def sistema_tributo_caixa(sistema):
    texto_sistema = " ".join(
        parte
        for parte in (
            sistema[4],
            sistema[5],
        )
        if parte
    )

    return contem_termo(texto_sistema, TERMOS_TRIBUTOS_CAIXA)


def regra_tributo_caixa(banco, sistema):
    return banco_caixa_economica(banco) and sistema_tributo_caixa(sistema)


def explicar_relacao_palavras(texto_banco, favorecido, descricao_sistema):
    texto_sistema = " ".join(
        parte
        for parte in (
            favorecido,
            descricao_sistema,
        )
        if parte
    )

    tokens_banco = tokens_relevantes(texto_banco)
    tokens_sistema = tokens_relevantes(texto_sistema)
    tokens_comuns = sorted(tokens_banco & tokens_sistema)

    categorias_banco = categorias_detectadas(texto_banco)
    categorias_sistema = categorias_detectadas(texto_sistema)
    categorias_comuns = sorted(categorias_banco & categorias_sistema)

    partes = []

    if categorias_comuns:
        partes.append(
            "categorias relacionadas: "
            + ", ".join(categorias_comuns)
        )

    if tokens_comuns:
        partes.append(
            "palavras em comum: "
            + ", ".join(tokens_comuns[:5])
        )

    return "; ".join(partes)


def metodo_valor_igual(metodo):
    return metodo.startswith("VALOR_") or metodo in {
        "CNPJ_VALOR_DATA_DIFERENTE",
    }


def aplicar_observacao_valor_igual(resultado):
    if resultado.get("status") != "CONCILIADO_VALOR_IGUAL":
        return resultado

    banco = resultado.get("banco")
    sistema = resultado.get("sistema")

    if not banco or not sistema:
        return resultado

    diferencas = []

    if banco[1] != sistema[1]:
        diferencas.append("data diferente")

    banco_documento = somente_digitos(banco[5])
    sistema_documento = somente_digitos(sistema[6])

    if banco_documento != sistema_documento:
        diferencas.append("CNPJ/CPF diferente ou ausente")

    fornecedor_ok, _ = fornecedor_compativel(
        banco[4],
        sistema[4],
        sistema[5],
    )

    if not fornecedor_ok:
        diferencas.append("fornecedor/prestador diferente ou nao identificado")

    relacao = explicar_relacao_palavras(
        banco[4],
        sistema[4],
        sistema[5],
    )

    observacoes = [
        "Conciliado automaticamente porque o tipo e o valor sao iguais."
    ]

    if regra_tributo_caixa(banco, sistema):
        observacoes.append(
            "Pagamento para CAIXA ECONOMICA associado a tributo/encargo do sistema."
        )

    if diferencas:
        observacoes.append(
            "Outras informacoes divergentes: "
            + ", ".join(diferencas)
            + "."
        )

    if relacao:
        observacoes.append(
            "Ligacao textual encontrada: "
            + relacao
            + "."
        )
    else:
        observacoes.append(
            "Sem ligacao textual clara; manter na aba de validacao por valor igual."
        )

    return {
        **resultado,
        "observacao": " ".join(observacoes),
    }


def centavos(valor):
    return int(Decimal(valor) * 100)


def documento_igual(documento1, documento2):
    doc1 = somente_digitos(documento1)
    doc2 = somente_digitos(documento2)

    return bool(doc1 and doc2 and doc1 == doc2)


def cnpj_raiz_igual(documento1, documento2):
    doc1 = somente_digitos(documento1)
    doc2 = somente_digitos(documento2)

    return bool(
        len(doc1) == 14
        and len(doc2) == 14
        and doc1[:8] == doc2[:8]
    )


def documento_compativel(documento1, documento2):
    return documento_igual(documento1, documento2) or cnpj_raiz_igual(
        documento1,
        documento2,
    )


def data_proxima(data1, data2):
    return abs((data1 - data2).days) <= JANELA_DIAS


def data_compativel_fornecedor(data1, data2):
    return abs((data1 - data2).days) <= JANELA_DIAS_FORNECEDOR


def data_compativel_tributo_caixa(data1, data2):
    return (
        data1.year == data2.year
        and data1.month == data2.month
    ) or data_compativel_fornecedor(data1, data2)


def chave_quantidade_documento(data, tipo, valor, documento):
    doc = somente_digitos(documento)

    if not doc:
        return None

    return (
        doc,
        tipo,
        centavos(valor),
        data.year,
        data.month,
    )


def contar_repeticoes_por_documento(bancos, sistemas):
    contagem_banco = {}
    contagem_sistema = {}

    for banco in bancos:
        chave = chave_quantidade_documento(
            banco[1],
            banco[2],
            banco[3],
            banco[5],
        )

        if chave:
            contagem_banco[chave] = contagem_banco.get(chave, 0) + 1

    for sistema in sistemas:
        chave = chave_quantidade_documento(
            sistema[1],
            sistema[2],
            sistema[3],
            sistema[6],
        )

        if chave:
            contagem_sistema[chave] = contagem_sistema.get(chave, 0) + 1

    return contagem_banco, contagem_sistema


def aplicar_regra_quantidade(resultado, contagem_banco, contagem_sistema):
    if resultado.get("sistemas") or resultado.get("bancos"):
        return resultado

    banco = resultado.get("banco")
    sistema = resultado.get("sistema")

    if not banco or not sistema:
        return resultado

    chave_banco = chave_quantidade_documento(
        banco[1],
        banco[2],
        banco[3],
        banco[5],
    )
    chave_sistema = chave_quantidade_documento(
        sistema[1],
        sistema[2],
        sistema[3],
        sistema[6],
    )

    if not chave_banco or chave_banco != chave_sistema:
        return resultado

    quantidade_banco = contagem_banco.get(chave_banco, 0)
    quantidade_sistema = contagem_sistema.get(chave_sistema, 0)

    if quantidade_banco != quantidade_sistema:
        return {
            **resultado,
            "score": min(resultado["score"], 72),
            "status": "POSSIVEL_REVISAO",
            "metodo": f"{resultado['metodo']}_QTD_DIVERGENTE",
            "observacao": (
                "Mesmo fornecedor, mes e valor, mas quantidade diferente: "
                f"banco={quantidade_banco}, sistema={quantidade_sistema}"
            ),
        }

    if quantidade_banco > 1:
        return {
            **resultado,
            "observacao": (
                "Quantidade mensal conferida: "
                f"banco={quantidade_banco}, sistema={quantidade_sistema}"
            ),
        }

    return resultado


def buscar_subconjunto_por_soma(candidatos, alvo):
    alvo_centavos = centavos(alvo)
    estados = {0: []}

    for candidato in candidatos:
        valor = centavos(candidato[3])

        for soma, itens in list(estados.items()):
            nova_soma = soma + valor

            if nova_soma > alvo_centavos:
                continue

            if nova_soma not in estados:
                estados[nova_soma] = [*itens, candidato]

            if nova_soma == alvo_centavos:
                return estados[nova_soma]

    return []


def buscar_dados(
    conta_bancaria_id=CONTA_BANCARIA_ID,
    empresa_id=EMPRESA_ID,
    sistema_origem=SISTEMA_ORIGEM,
    periodo_inicio=None,
    periodo_fim=None,
):
    filtros_banco = [
        "cv.id IS NULL",
        "b.conta_bancaria_id = %s",
    ]
    parametros_banco = [conta_bancaria_id]

    if periodo_inicio:
        filtros_banco.append("b.data_movimento >= %s")
        parametros_banco.append(periodo_inicio)

    if periodo_fim:
        filtros_banco.append("b.data_movimento <= %s")
        parametros_banco.append(periodo_fim)

    filtros_sistema = [
        "cv.id IS NULL",
        "l.empresa_id = %s",
        "l.status <> 'CANCELADO'",
    ]
    parametros_sistema = [empresa_id]

    if sistema_origem:
        filtros_sistema.append("l.sistema_origem = %s")
        parametros_sistema.append(sistema_origem)

    if periodo_inicio:
        filtros_sistema.append(
            "COALESCE(l.data_pagamento, l.data_lancamento) >= %s"
        )
        parametros_sistema.append(periodo_inicio)

    if periodo_fim:
        filtros_sistema.append(
            "COALESCE(l.data_pagamento, l.data_lancamento) <= %s"
        )
        parametros_sistema.append(periodo_fim)

    sql_banco = f"""
        SELECT
            b.id,
            b.data_movimento,
            b.tipo_movimento,
            b.valor,
            b.descricao,
            b.documento
        FROM transacoes_bancarias b
        LEFT JOIN conciliacao_vinculos cv
            ON cv.transacao_bancaria_id = b.id
        WHERE {" AND ".join(filtros_banco)}
        ORDER BY b.data_movimento, b.id;
    """

    sql_sistema = f"""
        SELECT
            l.id,
            COALESCE(l.data_pagamento, l.data_lancamento),
            l.tipo_movimento,
            l.valor,
            l.fornecedor_cliente,
            l.descricao,
            l.cnpj_cpf
        FROM lancamentos_sistema l
        LEFT JOIN conciliacao_vinculos cv
            ON cv.lancamento_sistema_id = l.id
        WHERE {" AND ".join(filtros_sistema)}
        ORDER BY COALESCE(l.data_pagamento, l.data_lancamento), l.id;
    """

    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(sql_banco, parametros_banco)
            bancos = cursor.fetchall()

            cursor.execute(sql_sistema, parametros_sistema)
            sistemas = cursor.fetchall()

    return bancos, sistemas


def calcular_score(banco, sistema):
    (
        banco_id,
        banco_data,
        banco_tipo,
        banco_valor,
        banco_descricao,
        banco_documento,
    ) = banco

    (
        sistema_id,
        sistema_data,
        sistema_tipo,
        sistema_valor,
        sistema_favorecido,
        sistema_descricao,
        sistema_documento,
    ) = sistema

    if banco_tipo != sistema_tipo:
        return 0, "TIPO_DIFERENTE", False

    banco_doc = somente_digitos(banco_documento)
    sistema_doc = somente_digitos(sistema_documento)
    docs_iguais = bool(banco_doc and sistema_doc and banco_doc == sistema_doc)

    data_diferenca = abs((banco_data - sistema_data).days)
    valor_igual = banco_valor == sistema_valor

    fornecedor_ok, texto_score = fornecedor_compativel(
        banco_descricao,
        sistema_favorecido,
        sistema_descricao,
    )

    if docs_iguais and valor_igual and data_diferenca == 0:
        return 100, "CNPJ_VALOR_DATA", False

    if docs_iguais and valor_igual and data_diferenca <= JANELA_DIAS:
        return 95, "CNPJ_VALOR_DATA_APROXIMADA", False

    if docs_iguais and valor_igual and fornecedor_ok:
        return 96, "CNPJ_VALOR_FORNECEDOR_DATA_DIFERENTE", False

    if docs_iguais and valor_igual:
        return 88, "CNPJ_VALOR_DATA_DIFERENTE", False

    if valor_igual and regra_tributo_caixa(banco, sistema):
        if data_diferenca <= JANELA_DIAS:
            return 94, "VALOR_TRIBUTO_CAIXA_DATA", False

        if data_compativel_fornecedor(banco_data, sistema_data):
            return 92, "VALOR_TRIBUTO_CAIXA_MES", False

        return 86, "VALOR_TRIBUTO_CAIXA_DATA_DIFERENTE", False

    if valor_igual and data_diferenca == 0 and fornecedor_ok:
        return 90, "VALOR_DATA_TEXTO", False

    if valor_igual and data_diferenca <= JANELA_DIAS and fornecedor_ok:
        return 85, "VALOR_DATA_TEXTO_APROXIMADA", False

    if valor_igual and fornecedor_ok:
        return 82, "VALOR_FORNECEDOR_DATA_DIFERENTE", False

    if valor_igual and data_diferenca == 0:
        return 80, "VALOR_DATA", False

    if valor_igual and data_diferenca <= JANELA_DIAS:
        return 75, "VALOR_DATA_APROXIMADA", False

    relacao_palavras = explicar_relacao_palavras(
        banco_descricao,
        sistema_favorecido,
        sistema_descricao,
    )

    if valor_igual and relacao_palavras:
        return 74, "VALOR_IGUAL_PALAVRAS_RELACIONADAS_INFO_DIFERENTE", False

    if valor_igual:
        return 70, "VALOR_IGUAL_INFO_DIFERENTE", False

    if docs_iguais and data_diferenca <= JANELA_DIAS:
        return 60, "CNPJ_DATA_VALOR_DIFERENTE", True

    return 0, "SEM_CORRESPONDENCIA", False


def montar_resultado_grupo_banco_para_sistemas(
    banco,
    sistemas,
    score=98,
    status="CONCILIADO",
    metodo="AGRUPAMENTO_SISTEMA_CNPJ_DATA_VALOR",
    observacao=None,
):
    if not observacao and any(
        cnpj_raiz_igual(banco[5], sistema[6])
        and not documento_igual(banco[5], sistema[6])
        for sistema in sistemas
    ):
        observacao = (
            "Agrupamento conciliado por soma exata com CNPJ de mesma raiz "
            "e filial diferente entre Banco e Sistema."
        )

    resultado = {
        "banco": banco,
        "sistema": sistemas[0],
        "sistemas": sistemas,
        "score": score,
        "status": status,
        "metodo": metodo,
        "divergencia": False,
    }

    if observacao:
        resultado["observacao"] = observacao

    return resultado


def montar_resultado_grupo_sistema_para_bancos(
    sistema,
    bancos,
    score=98,
    status="CONCILIADO",
    metodo="AGRUPAMENTO_BANCO_CNPJ_DATA_VALOR",
    observacao=None,
):
    if not observacao and any(
        cnpj_raiz_igual(banco[5], sistema[6])
        and not documento_igual(banco[5], sistema[6])
        for banco in bancos
    ):
        observacao = (
            "Agrupamento conciliado por soma exata com CNPJ de mesma raiz "
            "e filial diferente entre Banco e Sistema."
        )

    resultado = {
        "banco": bancos[0],
        "bancos": bancos,
        "sistema": sistema,
        "score": score,
        "status": status,
        "metodo": metodo,
        "divergencia": False,
    }

    if observacao:
        resultado["observacao"] = observacao

    return resultado


def encontrar_grupo_sistemas(banco, sistemas, sistemas_usados):
    candidatos = [
        sistema
        for sistema in sistemas
        if sistema[0] not in sistemas_usados
        and banco[2] == sistema[2]
        and data_proxima(banco[1], sistema[1])
        and documento_compativel(banco[5], sistema[6])
        and sistema[3] < banco[3]
    ]

    if len(candidatos) < 2 or len(candidatos) > MAX_CANDIDATOS_GRUPO:
        return []

    candidatos = sorted(
        candidatos,
        key=lambda sistema: (
            abs((banco[1] - sistema[1]).days),
            sistema[3],
            sistema[0],
        ),
    )

    return buscar_subconjunto_por_soma(
        candidatos,
        banco[3],
    )


def encontrar_grupo_sistemas_por_fornecedor(banco, sistemas, sistemas_usados):
    candidatos = []

    for sistema in sistemas:
        if sistema[0] in sistemas_usados:
            continue

        if banco[2] != sistema[2]:
            continue

        if not data_compativel_fornecedor(banco[1], sistema[1]):
            continue

        if sistema[3] >= banco[3]:
            continue

        fornecedor_ok, _ = fornecedor_compativel(
            banco[4],
            sistema[4],
            sistema[5],
        )

        if fornecedor_ok:
            candidatos.append(sistema)

    if len(candidatos) < 2 or len(candidatos) > MAX_CANDIDATOS_GRUPO:
        return []

    candidatos = sorted(
        candidatos,
        key=lambda sistema: (
            abs((banco[1] - sistema[1]).days),
            sistema[3],
            sistema[0],
        ),
    )

    return buscar_subconjunto_por_soma(
        candidatos,
        banco[3],
    )


def encontrar_grupo_sistemas_por_fornecedor_data(banco, sistemas, sistemas_usados):
    tokens_banco = tokens_relevantes(banco[4]) - {
        "servico",
        "servicos",
        "pagamento",
        "referente",
    }
    candidatos_por_favorecido = {}

    for sistema in sistemas:
        if sistema[0] in sistemas_usados:
            continue

        if banco[2] != sistema[2]:
            continue

        if not data_proxima(banco[1], sistema[1]):
            continue

        if sistema[3] >= banco[3]:
            continue

        tokens_favorecido = tokens_relevantes(sistema[4]) - {
            "servico",
            "servicos",
            "pagamento",
            "referente",
        }

        if not tokens_banco or not tokens_favorecido:
            continue

        if not (tokens_banco & tokens_favorecido):
            continue

        chave = normalizar_texto(sistema[4])
        candidatos_por_favorecido.setdefault(chave, []).append(sistema)

    for candidatos in candidatos_por_favorecido.values():
        if len(candidatos) < 2 or len(candidatos) > MAX_CANDIDATOS_GRUPO:
            continue

        candidatos = sorted(
            candidatos,
            key=lambda sistema: (
                abs((banco[1] - sistema[1]).days),
                sistema[3],
                sistema[0],
            ),
        )

        grupo = buscar_subconjunto_por_soma(
            candidatos,
            banco[3],
        )

        if grupo:
            return grupo

    return []


def encontrar_grupo_bancos(sistema, bancos, bancos_usados):
    candidatos = [
        banco
        for banco in bancos
        if banco[0] not in bancos_usados
        and banco[2] == sistema[2]
        and data_proxima(banco[1], sistema[1])
        and documento_compativel(banco[5], sistema[6])
        and banco[3] < sistema[3]
    ]

    if len(candidatos) < 2 or len(candidatos) > MAX_CANDIDATOS_GRUPO:
        return []

    candidatos = sorted(
        candidatos,
        key=lambda banco: (
            abs((banco[1] - sistema[1]).days),
            banco[3],
            banco[0],
        ),
    )

    return buscar_subconjunto_por_soma(
        candidatos,
        sistema[3],
    )


def encontrar_grupo_bancos_por_fornecedor_data(sistema, bancos, bancos_usados):
    candidatos = []

    for banco in bancos:
        if banco[0] in bancos_usados:
            continue

        if banco[2] != sistema[2]:
            continue

        if not data_proxima(banco[1], sistema[1]):
            continue

        if banco[3] >= sistema[3]:
            continue

        fornecedor_ok, _ = fornecedor_compativel(
            banco[4],
            sistema[4],
            sistema[5],
        )

        if fornecedor_ok:
            candidatos.append(banco)

    if len(candidatos) < 2 or len(candidatos) > MAX_CANDIDATOS_GRUPO:
        return []

    candidatos = sorted(
        candidatos,
        key=lambda banco: (
            abs((banco[1] - sistema[1]).days),
            banco[3],
            banco[0],
        ),
    )

    return buscar_subconjunto_por_soma(
        candidatos,
        sistema[3],
    )


def encontrar_grupo_sistemas_tributos_caixa(banco, sistemas, sistemas_usados):
    if not banco_caixa_economica(banco):
        return []

    candidatos = [
        sistema
        for sistema in sistemas
        if sistema[0] not in sistemas_usados
        and banco[2] == sistema[2]
        and data_compativel_tributo_caixa(banco[1], sistema[1])
        and sistema_tributo_caixa(sistema)
        and sistema[3] < banco[3]
    ]

    if len(candidatos) < 2:
        return []

    candidatos = sorted(
        candidatos,
        key=lambda sistema: (
            abs((banco[1] - sistema[1]).days),
            sistema[3],
            sistema[0],
        ),
    )[:MAX_CANDIDATOS_TRIBUTOS_CAIXA]

    return buscar_subconjunto_por_soma(
        candidatos,
        banco[3],
    )


def encontrar_grupo_bancos_tributos_caixa(sistema, bancos, bancos_usados):
    if not sistema_tributo_caixa(sistema):
        return []

    candidatos = [
        banco
        for banco in bancos
        if banco[0] not in bancos_usados
        and banco[2] == sistema[2]
        and data_compativel_tributo_caixa(banco[1], sistema[1])
        and banco_caixa_economica(banco)
        and banco[3] < sistema[3]
    ]

    if len(candidatos) < 2:
        return []

    candidatos = sorted(
        candidatos,
        key=lambda banco: (
            abs((banco[1] - sistema[1]).days),
            banco[3],
            banco[0],
        ),
    )[:MAX_CANDIDATOS_TRIBUTOS_CAIXA]

    return buscar_subconjunto_por_soma(
        candidatos,
        sistema[3],
    )


def encontrar_grupo_bancos_por_fornecedor(sistema, bancos, bancos_usados):
    candidatos = []

    for banco in bancos:
        if banco[0] in bancos_usados:
            continue

        if banco[2] != sistema[2]:
            continue

        if not data_compativel_fornecedor(banco[1], sistema[1]):
            continue

        if banco[3] >= sistema[3]:
            continue

        fornecedor_ok, _ = fornecedor_compativel(
            banco[4],
            sistema[4],
            sistema[5],
        )

        if fornecedor_ok:
            candidatos.append(banco)

    if len(candidatos) < 2 or len(candidatos) > MAX_CANDIDATOS_GRUPO:
        return []

    candidatos = sorted(
        candidatos,
        key=lambda banco: (
            abs((banco[1] - sistema[1]).days),
            banco[3],
            banco[0],
        ),
    )

    return buscar_subconjunto_por_soma(
        candidatos,
        sistema[3],
    )


def chave_ordenacao_par_forte(candidato):
    banco = candidato["banco"]
    sistema = candidato["sistema"]
    data_diferenca = abs((banco[1] - sistema[1]).days)
    docs_iguais = documento_igual(banco[5], sistema[6])
    fornecedor_ok, texto_score = fornecedor_compativel(
        banco[4],
        sistema[4],
        sistema[5],
    )

    return (
        -candidato["score"],
        data_diferenca,
        0 if docs_iguais else 1,
        0 if fornecedor_ok else 1,
        -texto_score,
        banco[0],
        sistema[0],
    )


def selecionar_pares_fortes(
    bancos,
    sistemas,
    bancos_usados,
    sistemas_usados,
    contagem_banco,
    contagem_sistema,
):
    candidatos = []

    for banco in bancos:
        if banco[0] in bancos_usados:
            continue

        for sistema in sistemas:
            if sistema[0] in sistemas_usados:
                continue

            if banco[2] != sistema[2]:
                continue

            if banco[3] != sistema[3]:
                continue

            if not documento_igual(banco[5], sistema[6]):
                continue

            score, metodo, divergencia = calcular_score(banco, sistema)

            if divergencia or score < 95:
                continue

            candidatos.append(
                {
                    "banco": banco,
                    "sistema": sistema,
                    "score": score,
                    "metodo": metodo,
                    "divergencia": divergencia,
                }
            )

    resultados = []

    for candidato in sorted(candidatos, key=chave_ordenacao_par_forte):
        banco = candidato["banco"]
        sistema = candidato["sistema"]

        if banco[0] in bancos_usados or sistema[0] in sistemas_usados:
            continue

        resultado = aplicar_regra_quantidade(
            {
                **candidato,
                "status": classificar(
                    candidato["score"],
                    candidato["divergencia"],
                    candidato["metodo"],
                ),
            },
            contagem_banco,
            contagem_sistema,
        )
        resultado = aplicar_observacao_valor_igual(resultado)

        resultados.append(resultado)
        bancos_usados.add(banco[0])
        sistemas_usados.add(sistema[0])

    return resultados


def classificar(score, divergencia, metodo=""):
    if divergencia:
        return "DIVERGENCIA"

    if score >= 95:
        return "CONCILIADO"

    if metodo_valor_igual(metodo) and score >= 70:
        return "CONCILIADO_VALOR_IGUAL"

    if score >= 80:
        return "POSSIVEL_CORRESPONDENCIA"

    if score >= 70:
        return "POSSIVEL_REVISAO"

    return "NAO_ENCONTRADO"


def conciliar(
    conta_bancaria_id=CONTA_BANCARIA_ID,
    empresa_id=EMPRESA_ID,
    sistema_origem=SISTEMA_ORIGEM,
    periodo_inicio=None,
    periodo_fim=None,
):
    bancos, sistemas = buscar_dados(
        conta_bancaria_id=conta_bancaria_id,
        empresa_id=empresa_id,
        sistema_origem=sistema_origem,
        periodo_inicio=periodo_inicio,
        periodo_fim=periodo_fim,
    )

    contagem_banco, contagem_sistema = contar_repeticoes_por_documento(
        bancos,
        sistemas,
    )
    sistemas_usados = set()
    bancos_usados = set()
    resultados = []

    for banco in bancos:
        grupo = encontrar_grupo_sistemas(
            banco,
            sistemas,
            sistemas_usados,
        )
        metodo = "AGRUPAMENTO_SISTEMA_CNPJ_DATA_VALOR"
        observacao = None

        if not grupo:
            continue

        resultados.append(
            montar_resultado_grupo_banco_para_sistemas(
                banco,
                grupo,
                metodo=metodo,
                observacao=observacao,
            )
        )
        bancos_usados.add(banco[0])
        sistemas_usados.update(sistema[0] for sistema in grupo)

    for sistema in sistemas:
        if sistema[0] in sistemas_usados:
            continue

        grupo = encontrar_grupo_bancos(
            sistema,
            bancos,
            bancos_usados,
        )
        metodo = "AGRUPAMENTO_BANCO_CNPJ_DATA_VALOR"
        observacao = None

        if not grupo:
            continue

        resultados.append(
            montar_resultado_grupo_sistema_para_bancos(
                sistema,
                grupo,
                metodo=metodo,
                observacao=observacao,
            )
        )
        sistemas_usados.add(sistema[0])
        bancos_usados.update(banco[0] for banco in grupo)

    for banco in bancos:
        if banco[0] in bancos_usados:
            continue

        grupo = encontrar_grupo_sistemas_tributos_caixa(
            banco,
            sistemas,
            sistemas_usados,
        )

        if not grupo:
            continue

        resultados.append(
            montar_resultado_grupo_banco_para_sistemas(
                banco,
                grupo,
                metodo="AGRUPAMENTO_SISTEMA_TRIBUTO_CAIXA_VALOR",
                observacao=(
                    "Agrupamento de tributo/encargo conciliado com "
                    "CAIXA ECONOMICA porque a soma dos valores fecha."
                ),
            )
        )
        bancos_usados.add(banco[0])
        sistemas_usados.update(sistema[0] for sistema in grupo)

    for sistema in sistemas:
        if sistema[0] in sistemas_usados:
            continue

        grupo = encontrar_grupo_bancos_tributos_caixa(
            sistema,
            bancos,
            bancos_usados,
        )

        if not grupo:
            continue

        resultados.append(
            montar_resultado_grupo_sistema_para_bancos(
                sistema,
                grupo,
                metodo="AGRUPAMENTO_BANCO_TRIBUTO_CAIXA_VALOR",
                observacao=(
                    "Agrupamento de tributo/encargo conciliado com "
                    "CAIXA ECONOMICA porque a soma dos valores fecha."
                ),
            )
        )
        sistemas_usados.add(sistema[0])
        bancos_usados.update(banco[0] for banco in grupo)

    for banco in bancos:
        if banco[0] in bancos_usados:
            continue

        grupo = encontrar_grupo_sistemas_por_fornecedor_data(
            banco,
            sistemas,
            sistemas_usados,
        )

        if not grupo:
            continue

        resultados.append(
            montar_resultado_grupo_banco_para_sistemas(
                banco,
                grupo,
                metodo="AGRUPAMENTO_SISTEMA_FORNECEDOR_DATA_VALOR",
                observacao=(
                    "Agrupamento conciliado por soma exata, data proxima "
                    "e fornecedor/prestador compativel."
                ),
            )
        )
        bancos_usados.add(banco[0])
        sistemas_usados.update(sistema[0] for sistema in grupo)

    resultados.extend(
        selecionar_pares_fortes(
            bancos,
            sistemas,
            bancos_usados,
            sistemas_usados,
            contagem_banco,
            contagem_sistema,
        )
    )

    for banco in bancos:
        if banco[0] in bancos_usados:
            continue

        melhor = None

        for sistema in sistemas:
            if sistema[0] in sistemas_usados:
                continue

            score, metodo, divergencia = calcular_score(banco, sistema)

            if not melhor or score > melhor["score"]:
                melhor = {
                    "banco": banco,
                    "sistema": sistema,
                    "score": score,
                    "metodo": metodo,
                    "divergencia": divergencia,
                }

        if not melhor or melhor["score"] == 0:
            resultados.append(
                {
                    "banco": banco,
                    "sistema": None,
                    "score": 0,
                    "status": "NAO_ENCONTRADO",
                    "metodo": "SEM_CORRESPONDENCIA",
                    "divergencia": False,
                }
            )
            continue

        status = classificar(
            melhor["score"],
            melhor["divergencia"],
            melhor["metodo"],
        )

        resultado = aplicar_regra_quantidade(
            {
                **melhor,
                "status": status,
            },
            contagem_banco,
            contagem_sistema,
        )
        resultado = aplicar_observacao_valor_igual(resultado)
        resultados.append(resultado)

        if resultado["status"] in (
            "CONCILIADO",
            "CONCILIADO_VALOR_IGUAL",
            "POSSIVEL_CORRESPONDENCIA",
            "POSSIVEL_REVISAO",
            "DIVERGENCIA",
        ):
            sistemas_usados.add(resultado["sistema"][0])
            bancos_usados.add(banco[0])

    return bancos, sistemas, resultados, sistemas_usados


def imprimir_resultado(bancos, sistemas, resultados, sistemas_usados):
    print(f"Transacoes bancarias pendentes: {len(bancos)}")
    print(f"Lancamentos do sistema pendentes: {len(sistemas)}")
    print()

    por_status = {}

    for item in resultados:
        por_status[item["status"]] = por_status.get(item["status"], 0) + 1

    print("Resumo por status:")

    for status, quantidade in sorted(por_status.items()):
        print(f"- {status}: {quantidade}")

    print(f"- SISTEMA_SEM_BANCO: {len(sistemas) - len(sistemas_usados)}")

    print()
    print("Amostra de correspondencias:")

    mostradas = 0

    for item in resultados:
        if item["sistema"] is None:
            continue

        banco = item["banco"]
        sistema = item["sistema"]
        grupo_sistemas = item.get("sistemas")
        grupo_bancos = item.get("bancos")
        detalhes_grupo = ""

        if grupo_sistemas:
            detalhes_grupo = f" | {len(grupo_sistemas)} lancamentos do sistema"

        if grupo_bancos:
            detalhes_grupo = f" | {len(grupo_bancos)} transacoes bancarias"

        print(
            f"Banco #{banco[0]} -> Sistema #{sistema[0]} | "
            f"{item['status']} | "
            f"Score {item['score']} | "
            f"{item['metodo']} | "
            f"Banco {banco[1]} R$ {banco[3]:.2f} | "
            f"Sistema {sistema[1]} R$ {sistema[3]:.2f}"
            f"{detalhes_grupo}"
        )

        mostradas += 1

        if mostradas >= LIMITE_AMOSTRA:
            break

    print()
    print("Amostra de banco sem correspondencia:")

    mostradas = 0

    for item in resultados:
        if item["status"] != "NAO_ENCONTRADO":
            continue

        banco = item["banco"]

        print(
            f"Banco #{banco[0]} | "
            f"{banco[1]} | "
            f"{banco[2]} | "
            f"R$ {banco[3]:.2f} | "
            f"{banco[4]}"
        )

        mostradas += 1

        if mostradas >= LIMITE_AMOSTRA:
            break

    print()
    print("Amostra de sistema sem banco:")

    mostradas = 0

    for sistema in sistemas:
        if sistema[0] in sistemas_usados:
            continue

        print(
            f"Sistema #{sistema[0]} | "
            f"{sistema[1]} | "
            f"{sistema[2]} | "
            f"R$ {sistema[3]:.2f} | "
            f"{sistema[4]} | "
            f"{sistema[5]}"
        )

        mostradas += 1

        if mostradas >= LIMITE_AMOSTRA:
            break


def main():
    print("Iniciando conciliacao Cora x Sistema...")
    print()

    bancos, sistemas, resultados, sistemas_usados = conciliar()
    imprimir_resultado(bancos, sistemas, resultados, sistemas_usados)


if __name__ == "__main__":
    main()
