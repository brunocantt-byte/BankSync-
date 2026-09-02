from collections import defaultdict

from base_historica import conectar_banco
from diagnosticar_clinux_db import carregar_config, conectar as conectar_clinux


INICIO = "2024-01-01"
FIM = "2026-12-31"


def moeda(valor):
    return f"R$ {float(valor or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def empresas_clinux():
    config = carregar_config()
    label, conexao = conectar_clinux(config)
    print(f"Conexao Clinux OK: {label}")

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                    SELECT
                        e.cd_empresa,
                        e.ds_empresa,
                        e.ds_razao,
                        e.ds_cnpj
                    FROM empresas e
                    ORDER BY e.cd_empresa;
                """
            )
            empresas = cursor.fetchall()

            cursor.execute(
                """
                    SELECT
                        l.cd_empresa,
                        COUNT(*) AS pagamentos,
                        SUM(p.nr_realizado) AS total_realizado
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    WHERE p.dt_realizacao BETWEEN %s AND %s
                      AND COALESCE(p.nr_realizado, 0) <> 0
                    GROUP BY l.cd_empresa;
                """,
                (INICIO, FIM),
            )
            pagamentos = {
                cd_empresa: (quantidade, total)
                for cd_empresa, quantidade, total in cursor.fetchall()
            }

            cursor.execute(
                """
                    WITH lados AS (
                        SELECT bsrc.cd_empresa AS cd_empresa, bt.nr_valor
                        FROM bancos_transfere bt
                        LEFT JOIN bancos bsrc ON bsrc.cd_banco = bt.cd_banco_src
                        WHERE COALESCE(bt.dt_conciliacao, bt.dt_lancamento, bt.dt_emissao, bt.dt_previsao)
                              BETWEEN %s AND %s
                          AND COALESCE(bt.nr_valor, 0) <> 0
                        UNION ALL
                        SELECT bdst.cd_empresa AS cd_empresa, bt.nr_valor
                        FROM bancos_transfere bt
                        LEFT JOIN bancos bdst ON bdst.cd_banco = bt.cd_banco_dst
                        WHERE COALESCE(bt.dt_conciliacao, bt.dt_lancamento, bt.dt_emissao, bt.dt_previsao)
                              BETWEEN %s AND %s
                          AND COALESCE(bt.nr_valor, 0) <> 0
                    )
                    SELECT cd_empresa, COUNT(*), SUM(nr_valor)
                    FROM lados
                    WHERE cd_empresa IS NOT NULL
                    GROUP BY cd_empresa;
                """,
                (INICIO, FIM, INICIO, FIM),
            )
            transferencias = {
                cd_empresa: (quantidade, total)
                for cd_empresa, quantidade, total in cursor.fetchall()
            }

    return empresas, pagamentos, transferencias


def importados_locais():
    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                    SELECT
                        (l.metadados ->> 'cd_empresa_clinux')::integer AS cd_empresa,
                        l.sistema_origem,
                        COUNT(*),
                        SUM(l.valor)
                    FROM lancamentos_sistema l
                    WHERE l.sistema_origem IN ('CLINUX', 'CLINUX_TRANSFERENCIA')
                      AND l.metadados ? 'cd_empresa_clinux'
                    GROUP BY 1, 2;
                """
            )

            resultado = defaultdict(dict)
            for cd_empresa, origem, quantidade, total in cursor.fetchall():
                resultado[cd_empresa][origem] = (quantidade, total)

    return resultado


def main():
    empresas, pagamentos, transferencias = empresas_clinux()
    local = importados_locais()

    print()
    print("EMPRESAS ENCONTRADAS NO CLINUX E IMPORTACAO LOCAL")
    print("COD | EMPRESA | RAZAO | CNPJ | PAGAMENTOS IMPORTADOS | TRANSFERENCIAS IMPORTADAS | STATUS")

    nao_importadas = []
    for cd_empresa, nome, razao, cnpj in empresas:
        pag_qtd, pag_total = pagamentos.get(cd_empresa, (0, 0))
        transf_qtd, transf_total = transferencias.get(cd_empresa, (0, 0))
        loc_pag_qtd, loc_pag_total = local.get(cd_empresa, {}).get("CLINUX", (0, 0))
        loc_transf_qtd, loc_transf_total = local.get(cd_empresa, {}).get("CLINUX_TRANSFERENCIA", (0, 0))

        if loc_pag_qtd or loc_transf_qtd:
            status = "IMPORTADA"
        else:
            status = "NAO IMPORTADA: sem pagamento realizado ou transferencia no periodo"
            nao_importadas.append((cd_empresa, nome, razao, cnpj))

        print(
            f"{cd_empresa} | {nome or ''} | {razao or ''} | {cnpj or ''} | "
            f"{loc_pag_qtd} ({moeda(loc_pag_total)}) | "
            f"{loc_transf_qtd} ({moeda(loc_transf_total)}) | {status}"
        )

    print()
    print(f"Total de empresas encontradas no Clinux: {len(empresas)}")
    print(f"Empresas com algum dado importado: {len(empresas) - len(nao_importadas)}")
    print(f"Empresas sem dado importado no periodo: {len(nao_importadas)}")

    if nao_importadas:
        print("Nao importadas:")
        for cd_empresa, nome, razao, cnpj in nao_importadas:
            print(f"- {cd_empresa} | {nome or ''} | {razao or ''} | {cnpj or ''}")


if __name__ == "__main__":
    main()
