from __future__ import annotations

from argparse import ArgumentParser
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
import hashlib
import json
import sys

from base_historica import conectar_banco
from diagnosticar_clinux_db import carregar_config, conectar as conectar_clinux


SISTEMA_ORIGEM = "CLINUX"
ORIGEM_TRANSFERENCIA = "CLINUX_TRANSFERENCIA"
ORIGENS_XLS_ANTIGAS = ("SISTEMA.xls", "SISTEMA.xlsx")
ORIGENS_CLINUX = (SISTEMA_ORIGEM, ORIGEM_TRANSFERENCIA)


def parse_data(valor: str) -> date:
    return date.fromisoformat(valor)


def valor_decimal(valor) -> Decimal:
    return Decimal(str(valor or 0)).quantize(Decimal("0.01"))


def normalizar_cnpj(cnpj):
    if not cnpj:
        return None

    apenas_digitos = "".join(caracter for caracter in str(cnpj) if caracter.isdigit())
    return apenas_digitos or None


def tipo_movimento(sn_despesa, tipo_lancamento: str) -> str:
    if sn_despesa is False:
        return "ENTRADA"

    if sn_despesa is True:
        return "SAIDA"

    tipo = (tipo_lancamento or "").strip().upper()
    if tipo in ("F", "U"):
        return "ENTRADA"

    return "SAIDA"


def listar_empresas_clinux(empresa_clinux_ids=None):
    config = carregar_config()
    label, conexao = conectar_clinux(config)
    print(f"Conexao Clinux OK: {label}")

    with conexao:
        with conexao.cursor() as cursor:
            filtros = []
            parametros = []

            if empresa_clinux_ids:
                filtros.append("e.cd_empresa = ANY(%s)")
                parametros.append(empresa_clinux_ids)

            where = "WHERE " + " AND ".join(filtros) if filtros else ""
            cursor.execute(
                f"""
                    SELECT e.cd_empresa, e.ds_empresa, e.ds_razao, e.ds_cnpj
                    FROM empresas e
                    {where}
                    ORDER BY e.cd_empresa;
                """,
                parametros,
            )
            return cursor.fetchall()


def buscar_lancamentos_clinux(
    inicio,
    fim,
    empresa_clinux_ids=None,
    cd_pagamento_maior_que=None,
):
    config = carregar_config()
    label, conexao = conectar_clinux(config)
    print(f"Conexao Clinux OK: {label}")

    with conexao:
        with conexao.cursor() as cursor:
            filtros = [
                "p.dt_realizacao BETWEEN %s AND %s",
                "COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0) <> 0",
            ]
            parametros = [inicio, fim]

            if empresa_clinux_ids:
                filtros.append("l.cd_empresa = ANY(%s)")
                parametros.append(empresa_clinux_ids)

            if cd_pagamento_maior_que is not None:
                filtros.append("p.cd_pagamento > %s")
                parametros.append(cd_pagamento_maior_que)

            cursor.execute(
                f"""
                    SELECT
                        p.cd_pagamento,
                        l.cd_lancamento,
                        l.cd_empresa,
                        e.ds_empresa,
                        e.ds_razao,
                        e.ds_cnpj,
                        p.dt_realizacao,
                        p.dt_vencimento,
                        l.dt_emissao,
                        COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0) AS valor,
                        l.ds_tipo AS tipo_lancamento,
                        p.ds_tipo AS tipo_pagamento,
                        f.ds_fornecedor,
                        f.ds_razao,
                        f.ds_cnpj,
                        l.ds_documento,
                        l.ds_historico,
                        c.ds_conta,
                        cg.ds_grupo,
                        cg.sn_despesa,
                        cc.ds_centro,
                        b.ds_banco,
                        p.cd_banco,
                        l.cd_conta,
                        l.cd_centro,
                        p.sn_previsto,
                        l.sn_fechado,
                        bt.cd_transferencia
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    LEFT JOIN empresas e ON e.cd_empresa = l.cd_empresa
                    LEFT JOIN fornecedores f ON f.cd_fornecedor = l.cd_fornecedor
                    LEFT JOIN contas c ON c.cd_conta = l.cd_conta
                    LEFT JOIN contas_grupos cg ON cg.cd_grupo = c.cd_grupo
                    LEFT JOIN centro_custos cc ON cc.cd_centro = l.cd_centro
                    LEFT JOIN bancos b ON b.cd_banco = p.cd_banco
                    LEFT JOIN bancos_transfere bt ON bt.cd_pagamento = p.cd_pagamento
                    WHERE {" AND ".join(filtros)}
                    ORDER BY p.dt_realizacao, p.cd_pagamento;
                """,
                parametros,
            )
            return cursor.fetchall()


def buscar_transferencias_clinux(
    inicio,
    fim,
    empresa_clinux_ids=None,
    cd_transferencia_maior_que=None,
):
    config = carregar_config()
    label, conexao = conectar_clinux(config)
    print(f"Conexao Clinux OK: {label}")

    with conexao:
        with conexao.cursor() as cursor:
            filtros = [
                "COALESCE(bt.dt_conciliacao, bt.dt_lancamento, bt.dt_emissao, bt.dt_previsao) BETWEEN %s AND %s",
                "COALESCE(bt.nr_valor, 0) <> 0",
            ]
            parametros = [inicio, fim]

            if empresa_clinux_ids:
                filtros.append("(bsrc.cd_empresa = ANY(%s) OR bdst.cd_empresa = ANY(%s))")
                parametros.extend([empresa_clinux_ids, empresa_clinux_ids])

            if cd_transferencia_maior_que is not None:
                filtros.append("bt.cd_transferencia > %s")
                parametros.append(cd_transferencia_maior_que)

            cursor.execute(
                f"""
                    SELECT
                        bt.cd_transferencia,
                        COALESCE(bt.dt_conciliacao, bt.dt_lancamento, bt.dt_emissao, bt.dt_previsao) AS data_movimento,
                        bt.nr_valor,
                        bt.ds_historico,
                        bt.cd_banco_src,
                        bsrc.ds_banco AS banco_origem,
                        bsrc.cd_empresa AS empresa_origem,
                        e_src.ds_empresa AS unidade_origem,
                        e_src.ds_razao AS razao_origem,
                        e_src.ds_cnpj AS cnpj_origem,
                        bt.cd_banco_dst,
                        bdst.ds_banco AS banco_destino,
                        bdst.cd_empresa AS empresa_destino,
                        e_dst.ds_empresa AS unidade_destino,
                        e_dst.ds_razao AS razao_destino,
                        e_dst.ds_cnpj AS cnpj_destino,
                        bt.cd_pagamento,
                        bt.cd_centro
                    FROM bancos_transfere bt
                    LEFT JOIN bancos bsrc ON bsrc.cd_banco = bt.cd_banco_src
                    LEFT JOIN empresas e_src ON e_src.cd_empresa = bsrc.cd_empresa
                    LEFT JOIN bancos bdst ON bdst.cd_banco = bt.cd_banco_dst
                    LEFT JOIN empresas e_dst ON e_dst.cd_empresa = bdst.cd_empresa
                    WHERE {" AND ".join(filtros)}
                    ORDER BY data_movimento, bt.cd_transferencia;
                """,
                parametros,
            )
            return cursor.fetchall()


def montar_lancamento(linha):
    (
        cd_pagamento,
        cd_lancamento,
        cd_empresa,
        ds_empresa,
        ds_razao_empresa,
        ds_cnpj_empresa,
        dt_realizacao,
        dt_vencimento,
        dt_emissao,
        valor,
        ds_tipo_lancamento,
        ds_tipo_pagamento,
        ds_fornecedor,
        ds_razao,
        ds_cnpj,
        ds_documento,
        ds_historico,
        ds_conta,
        ds_grupo,
        sn_despesa,
        ds_centro,
        ds_banco,
        cd_banco,
        cd_conta,
        cd_centro,
        sn_previsto,
        sn_fechado,
        cd_transferencia,
    ) = linha

    descricao = ds_historico or ""
    if ds_banco:
        descricao = f"{descricao} | Banco Clinux: {ds_banco}".strip()

    metadados = {
        "cd_pagamento": cd_pagamento,
        "cd_lancamento": cd_lancamento,
        "cd_empresa_clinux": cd_empresa,
        "unidade_clinux": ds_empresa,
        "razao_empresa_clinux": ds_razao_empresa,
        "cnpj_empresa_clinux": ds_cnpj_empresa,
        "ds_tipo_lancamento": ds_tipo_lancamento,
        "ds_tipo_pagamento": ds_tipo_pagamento,
        "grupo_conta_clinux": ds_grupo,
        "sn_despesa": sn_despesa,
        "cd_banco_clinux": cd_banco,
        "banco_clinux": ds_banco,
        "cd_conta_clinux": cd_conta,
        "cd_centro_clinux": cd_centro,
        "sn_previsto": sn_previsto,
        "sn_fechado": sn_fechado,
        "eh_transferencia": cd_transferencia is not None,
        "cd_transferencia": cd_transferencia,
    }

    return {
        "cd_empresa_clinux": cd_empresa,
        "data_lancamento": dt_emissao or dt_realizacao,
        "data_vencimento": dt_vencimento,
        "data_pagamento": dt_realizacao,
        "tipo_movimento": tipo_movimento(sn_despesa, ds_tipo_lancamento),
        "valor": abs(valor_decimal(valor)),
        "fornecedor_cliente": ds_fornecedor or ds_razao,
        "documento": ds_documento,
        "cnpj_cpf": ds_cnpj,
        "descricao": descricao or None,
        "categoria": ds_conta,
        "centro_custo": ds_centro,
        "sistema_origem": SISTEMA_ORIGEM,
        "identificador_externo": f"CLINUX:PAGAMENTO:{cd_pagamento}",
        "status": "ABERTO",
        "metadados": metadados,
    }


def montar_transferencias(linhas):
    lancamentos = []

    for linha in linhas:
        (
            cd_transferencia,
            data_movimento,
            valor,
            historico,
            cd_banco_src,
            banco_origem,
            empresa_origem,
            unidade_origem,
            razao_origem,
            cnpj_origem,
            cd_banco_dst,
            banco_destino,
            empresa_destino,
            unidade_destino,
            razao_destino,
            cnpj_destino,
            cd_pagamento,
            cd_centro,
        ) = linha

        lados = (
            ("SAIDA_ORIGEM", "SAIDA", empresa_origem, unidade_origem, razao_origem, cnpj_origem),
            ("ENTRADA_DESTINO", "ENTRADA", empresa_destino, unidade_destino, razao_destino, cnpj_destino),
        )

        for direcao, tipo, empresa_clinux, unidade, razao, cnpj in lados:
            descricao = (
                f"TRANSFERENCIA ENTRE CONTAS | {banco_origem or 'origem'} "
                f"-> {banco_destino or 'destino'}"
            )
            if historico:
                descricao = f"{descricao} | {historico}"

            metadados = {
                "cd_transferencia": cd_transferencia,
                "cd_pagamento": cd_pagamento,
                "cd_empresa_clinux": empresa_clinux,
                "unidade_clinux": unidade,
                "razao_empresa_clinux": razao,
                "cnpj_empresa_clinux": cnpj,
                "cd_banco_origem_clinux": cd_banco_src,
                "banco_origem_clinux": banco_origem,
                "cd_banco_destino_clinux": cd_banco_dst,
                "banco_destino_clinux": banco_destino,
                "cd_centro_clinux": cd_centro,
                "grupo_conta_clinux": "TRANSFERENCIA ENTRE CONTAS",
                "eh_transferencia": True,
                "direcao_transferencia": direcao,
            }

            lancamentos.append(
                {
                    "cd_empresa_clinux": empresa_clinux,
                    "data_lancamento": data_movimento,
                    "data_vencimento": data_movimento,
                    "data_pagamento": data_movimento,
                    "tipo_movimento": tipo,
                    "valor": abs(valor_decimal(valor)),
                    "fornecedor_cliente": "TRANSFERENCIA ENTRE CONTAS",
                    "documento": str(cd_transferencia),
                    "cnpj_cpf": None,
                    "descricao": descricao,
                    "categoria": "TRANSFERENCIA ENTRE CONTAS",
                    "centro_custo": None,
                    "sistema_origem": ORIGEM_TRANSFERENCIA,
                    "identificador_externo": f"CLINUX:TRANSFERENCIA:{cd_transferencia}:{direcao}",
                    "status": "ABERTO",
                    "metadados": metadados,
                }
            )

    return lancamentos


def registrar_fonte_clinux(cursor, *, empresa_id, inicio, fim, quantidade, empresa_clinux):
    nome = f"CLINUX_DB_{inicio}_{fim}_EMPRESA_{empresa_clinux}"
    hash_arquivo = hashlib.sha256(nome.encode("utf-8")).hexdigest()

    cursor.execute(
        """
            INSERT INTO arquivos_importados (
                nome_arquivo,
                caminho_arquivo,
                tipo_arquivo,
                tamanho_bytes,
                hash_arquivo,
                quantidade_registros,
                status,
                processado_em,
                empresa_id,
                origem,
                periodo_inicio,
                periodo_fim,
                metadados
            )
            VALUES (
                %s,
                'clinux://clinux_ctr/public.pagamentos',
                'DB',
                0,
                %s,
                %s,
                'PROCESSADO',
                CURRENT_TIMESTAMP,
                %s,
                'SISTEMA',
                %s,
                %s,
                %s
            )
            ON CONFLICT (hash_arquivo) DO UPDATE
            SET quantidade_registros = EXCLUDED.quantidade_registros,
                status = 'PROCESSADO',
                processado_em = CURRENT_TIMESTAMP,
                empresa_id = EXCLUDED.empresa_id,
                origem = EXCLUDED.origem,
                periodo_inicio = EXCLUDED.periodo_inicio,
                periodo_fim = EXCLUDED.periodo_fim,
                metadados = arquivos_importados.metadados || EXCLUDED.metadados
            RETURNING id;
        """,
        (
            nome,
            hash_arquivo,
            quantidade,
            empresa_id,
            inicio,
            fim,
            json.dumps(
                {
                    "sistema": "CLINUX",
                    "banco_origem": "clinux_ctr",
                    "empresa_clinux": empresa_clinux,
                    "tabela_principal": "public.pagamentos",
                    "inclui_transferencias": True,
                    "regra_tipo_movimento": "contas_grupos.sn_despesa",
                }
            ),
        ),
    )

    return cursor.fetchone()[0]


def garantir_empresa_local(cursor, empresa_clinux):
    cd_empresa, ds_empresa, ds_razao, ds_cnpj = empresa_clinux
    cnpj = normalizar_cnpj(ds_cnpj) or f"CLINUX-{cd_empresa}"
    razao_social = ds_razao or ds_empresa or f"CLINUX EMPRESA {cd_empresa}"
    nome_fantasia = ds_empresa or razao_social

    cursor.execute(
        """
            INSERT INTO empresas (
                razao_social,
                nome_fantasia,
                cnpj
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (cnpj) DO UPDATE
            SET razao_social = EXCLUDED.razao_social,
                nome_fantasia = EXCLUDED.nome_fantasia
            RETURNING id;
        """,
        (razao_social, nome_fantasia, cnpj),
    )

    return cursor.fetchone()[0]


def limpar_origens(cursor, origens):
    cursor.execute(
        """
            SELECT id
            FROM lancamentos_sistema
            WHERE sistema_origem = ANY(%s);
        """,
        (list(origens),),
    )
    ids = [linha[0] for linha in cursor.fetchall()]

    if not ids:
        return {
            "lancamentos": 0,
            "vinculos": 0,
            "conciliacoes_orfas": 0,
            "arquivos": 0,
        }

    cursor.execute(
        """
            DELETE FROM conciliacao_vinculos
            WHERE lancamento_sistema_id = ANY(%s);
        """,
        (ids,),
    )
    vinculos = cursor.rowcount

    cursor.execute(
        """
            DELETE FROM conciliacoes c
            WHERE NOT EXISTS (
                SELECT 1
                FROM conciliacao_vinculos cv
                WHERE cv.conciliacao_id = c.id
            );
        """
    )
    conciliacoes_orfas = cursor.rowcount

    cursor.execute(
        """
            DELETE FROM lancamentos_sistema
            WHERE id = ANY(%s);
        """,
        (ids,),
    )
    lancamentos = cursor.rowcount

    cursor.execute(
        """
            DELETE FROM arquivos_importados
            WHERE origem = 'SISTEMA'
              AND (
                  nome_arquivo = ANY(%s)
                  OR metadados ->> 'sistema' = 'CLINUX'
              );
        """,
        (list(ORIGENS_XLS_ANTIGAS),),
    )
    arquivos = cursor.rowcount

    return {
        "lancamentos": lancamentos,
        "vinculos": vinculos,
        "conciliacoes_orfas": conciliacoes_orfas,
        "arquivos": arquivos,
    }


def lancamento_existe(cursor, empresa_id, identificador):
    cursor.execute(
        """
            SELECT id
            FROM lancamentos_sistema
            WHERE empresa_id = %s
              AND identificador_externo = %s
            LIMIT 1;
        """,
        (empresa_id, identificador),
    )

    return cursor.fetchone() is not None


def inserir_lancamento(cursor, empresa_id, lancamento):
    dados = dict(lancamento)
    dados["empresa_id"] = empresa_id
    dados["metadados"] = json.dumps(dados["metadados"], default=str)

    cursor.execute(
        """
            INSERT INTO lancamentos_sistema (
                empresa_id,
                data_lancamento,
                data_vencimento,
                data_pagamento,
                tipo_movimento,
                valor,
                fornecedor_cliente,
                documento,
                cnpj_cpf,
                descricao,
                categoria,
                centro_custo,
                sistema_origem,
                identificador_externo,
                status,
                metadados
            )
            VALUES (
                %(empresa_id)s,
                %(data_lancamento)s,
                %(data_vencimento)s,
                %(data_pagamento)s,
                %(tipo_movimento)s,
                %(valor)s,
                %(fornecedor_cliente)s,
                %(documento)s,
                %(cnpj_cpf)s,
                %(descricao)s,
                %(categoria)s,
                %(centro_custo)s,
                %(sistema_origem)s,
                %(identificador_externo)s,
                %(status)s,
                %(metadados)s
            );
        """,
        dados,
    )


def somar_limpezas(*limpezas):
    total = Counter()
    for limpeza in limpezas:
        total.update(limpeza)
    return dict(total)


def buscar_maiores_ids_clinux_local():
    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                    SELECT
                        MAX((metadados ->> 'cd_pagamento')::bigint)
                    FROM lancamentos_sistema
                    WHERE sistema_origem = 'CLINUX'
                      AND metadados ? 'cd_pagamento'
                      AND metadados ->> 'cd_pagamento' ~ '^[0-9]+$';
                """
            )
            maior_pagamento = cursor.fetchone()[0]

            cursor.execute(
                """
                    SELECT
                        MAX((metadados ->> 'cd_transferencia')::bigint)
                    FROM lancamentos_sistema
                    WHERE sistema_origem = 'CLINUX_TRANSFERENCIA'
                      AND metadados ? 'cd_transferencia'
                      AND metadados ->> 'cd_transferencia' ~ '^[0-9]+$';
                """
            )
            maior_transferencia = cursor.fetchone()[0]

    return maior_pagamento, maior_transferencia


def importar(
    inicio,
    fim,
    empresa_id,
    empresa_clinux,
    todas_empresas,
    substituir_xls,
    substituir_clinux,
    somente_novos=False,
):
    empresa_clinux_ids = None if todas_empresas else [empresa_clinux]
    maior_pagamento = None
    maior_transferencia = None

    if somente_novos and not substituir_clinux:
        maior_pagamento, maior_transferencia = buscar_maiores_ids_clinux_local()

    empresas_clinux = listar_empresas_clinux(empresa_clinux_ids)
    linhas_pagamentos = buscar_lancamentos_clinux(
        inicio,
        fim,
        empresa_clinux_ids,
        cd_pagamento_maior_que=maior_pagamento,
    )
    linhas_transferencias = buscar_transferencias_clinux(
        inicio,
        fim,
        empresa_clinux_ids,
        cd_transferencia_maior_que=maior_transferencia,
    )
    lancamentos = [montar_lancamento(linha) for linha in linhas_pagamentos]
    transferencias = montar_transferencias(linhas_transferencias)
    todos_lancamentos = lancamentos + transferencias

    inseridos = 0
    existentes = 0
    por_tipo = Counter(item["tipo_movimento"] for item in todos_lancamentos)
    total_por_tipo = Counter()
    faturamento_bruto = defaultdict(Decimal)
    por_empresa = defaultdict(lambda: Counter())
    total_por_empresa = defaultdict(lambda: Counter())

    for item in todos_lancamentos:
        total_por_tipo[item["tipo_movimento"]] += item["valor"]
        por_empresa[item["cd_empresa_clinux"]][item["tipo_movimento"]] += 1
        total_por_empresa[item["cd_empresa_clinux"]][item["tipo_movimento"]] += item["valor"]

        if (
            item["tipo_movimento"] == "ENTRADA"
            and item["sistema_origem"] == SISTEMA_ORIGEM
            and item["metadados"].get("grupo_conta_clinux") == "RECEITAS"
            and not item["metadados"].get("eh_transferencia")
        ):
            faturamento_bruto[item["cd_empresa_clinux"]] += item["valor"]

    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            empresas_por_codigo = {
                cd_empresa: garantir_empresa_local(cursor, empresa)
                for empresa in empresas_clinux
                for cd_empresa in (empresa[0],)
            }

            limpezas = []
            if substituir_xls:
                limpezas.append(limpar_origens(cursor, ORIGENS_XLS_ANTIGAS))

            if substituir_clinux:
                limpezas.append(limpar_origens(cursor, ORIGENS_CLINUX))

            limpeza = somar_limpezas(*limpezas) if limpezas else {
                "lancamentos": 0,
                "vinculos": 0,
                "conciliacoes_orfas": 0,
                "arquivos": 0,
            }

            arquivo_id = registrar_fonte_clinux(
                cursor,
                empresa_id=empresa_id,
                inicio=inicio,
                fim=fim,
                quantidade=len(todos_lancamentos),
                empresa_clinux="TODAS" if todas_empresas else empresa_clinux,
            )

            for lancamento in todos_lancamentos:
                empresa_local_id = empresas_por_codigo.get(
                    lancamento["cd_empresa_clinux"],
                    empresa_id,
                )

                if lancamento_existe(
                    cursor,
                    empresa_local_id,
                    lancamento["identificador_externo"],
                ):
                    existentes += 1
                    continue

                inserir_lancamento(cursor, empresa_local_id, lancamento)
                inseridos += 1

        conexao.commit()

    return {
        "arquivo_id": arquivo_id,
        "pagamentos_lidos": len(lancamentos),
        "transferencias_lidas": len(transferencias),
        "lidos": len(todos_lancamentos),
        "inseridos": inseridos,
        "existentes": existentes,
        "limpeza": limpeza,
        "por_tipo": dict(por_tipo),
        "total_por_tipo": dict(total_por_tipo),
        "faturamento_bruto": dict(faturamento_bruto),
        "por_empresa": {empresa: dict(contador) for empresa, contador in por_empresa.items()},
        "total_por_empresa": {
            empresa: dict(contador)
            for empresa, contador in total_por_empresa.items()
        },
        "somente_novos": somente_novos,
        "maior_pagamento_anterior": maior_pagamento,
        "maior_transferencia_anterior": maior_transferencia,
    }


def main():
    parser = ArgumentParser(
        description="Importa lancamentos financeiros do Clinux para a base local."
    )
    parser.add_argument("--inicio", default="2024-01-01")
    parser.add_argument("--fim", default="2026-12-31")
    parser.add_argument("--empresa-id", type=int, default=2)
    parser.add_argument("--empresa-clinux", type=int, default=1)
    parser.add_argument("--todas-empresas", action="store_true")
    parser.add_argument("--substituir-sistema-xls", action="store_true")
    parser.add_argument("--substituir-clinux", action="store_true")
    parser.add_argument("--somente-novos", action="store_true")
    args = parser.parse_args()

    resultado = importar(
        inicio=parse_data(args.inicio),
        fim=parse_data(args.fim),
        empresa_id=args.empresa_id,
        empresa_clinux=args.empresa_clinux,
        todas_empresas=args.todas_empresas,
        substituir_xls=args.substituir_sistema_xls,
        substituir_clinux=args.substituir_clinux,
        somente_novos=args.somente_novos,
    )

    print("Importacao Clinux concluida.")
    print(f"Fonte registrada em arquivos_importados: {resultado['arquivo_id']}")
    print(f"Pagamentos lidos no Clinux: {resultado['pagamentos_lidos']}")
    print(f"Transferencias geradas: {resultado['transferencias_lidas']}")
    print(f"Total de movimentos lidos: {resultado['lidos']}")
    print(f"Inseridos na base local: {resultado['inseridos']}")
    print(f"Ja existentes: {resultado['existentes']}")
    print(f"Removidos antes da importacao: {resultado['limpeza']}")
    print(f"Modo somente novos: {resultado['somente_novos']}")
    print(f"Maior pagamento anterior: {resultado['maior_pagamento_anterior']}")
    print(f"Maior transferencia anterior: {resultado['maior_transferencia_anterior']}")
    print(f"Quantidade por tipo: {resultado['por_tipo']}")
    print(f"Total por tipo: {resultado['total_por_tipo']}")
    print(f"Faturamento bruto por empresa Clinux: {resultado['faturamento_bruto']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as erro:
        print(f"Erro ao importar Clinux: {erro}")
        sys.exit(1)
