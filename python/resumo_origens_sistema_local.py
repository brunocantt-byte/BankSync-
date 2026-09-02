from base_historica import conectar_banco


def main():
    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                    SELECT
                        COALESCE(sistema_origem, 'SEM_ORIGEM') AS origem,
                        COUNT(*),
                        MIN(COALESCE(data_pagamento, data_lancamento)),
                        MAX(COALESCE(data_pagamento, data_lancamento)),
                        SUM(valor)
                    FROM lancamentos_sistema
                    GROUP BY COALESCE(sistema_origem, 'SEM_ORIGEM')
                    ORDER BY origem;
                """
            )

            for origem, quantidade, inicio, fim, total in cursor.fetchall():
                print(f"{origem} | qtd={quantidade} | periodo={inicio} a {fim} | total={total}")


if __name__ == "__main__":
    main()
