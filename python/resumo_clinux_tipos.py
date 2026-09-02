from argparse import ArgumentParser

from diagnosticar_clinux_db import carregar_config, conectar


def main():
    parser = ArgumentParser()
    parser.add_argument("--inicio", default="2026-06-01")
    parser.add_argument("--fim", default="2026-06-30")
    args = parser.parse_args()

    config = carregar_config()
    label, conexao = conectar(config)
    print(f"Conexao OK: {label}")

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                    SELECT
                        COALESCE(l.ds_tipo, '') AS tipo_lancamento,
                        COALESCE(p.ds_tipo, '') AS tipo_pagamento,
                        COALESCE(p.sn_previsto::text, '') AS previsto,
                        COALESCE(l.sn_fechado::text, '') AS fechado,
                        COUNT(*) AS quantidade,
                        SUM(COALESCE(p.nr_realizado, p.nr_pagamento, p.nr_previsto, 0)) AS total
                    FROM pagamentos p
                    JOIN lancamentos l ON l.cd_lancamento = p.cd_lancamento
                    WHERE l.cd_empresa = 1
                      AND p.dt_realizacao BETWEEN %s AND %s
                    GROUP BY l.ds_tipo, p.ds_tipo, p.sn_previsto, l.sn_fechado
                    ORDER BY total DESC NULLS LAST;
                """,
                (args.inicio, args.fim),
            )

            for linha in cursor.fetchall():
                print(
                    " | ".join(
                        "" if item is None else str(item)
                        for item in linha
                    )
                )


if __name__ == "__main__":
    main()
