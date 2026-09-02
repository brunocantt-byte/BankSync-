from diagnosticar_clinux_db import carregar_config, conectar


def main():
    config = carregar_config()
    label, conexao = conectar(config)
    print(f"Conexao OK: {label}")

    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'empresas'
                    ORDER BY ordinal_position;
                """
            )
            colunas = [linha[0] for linha in cursor.fetchall()]
            print("Colunas:", ", ".join(colunas))

            campos_preferidos = [
                campo
                for campo in (
                    "cd_empresa",
                    "ds_empresa",
                    "ds_razao",
                    "ds_fantasia",
                    "ds_cnpj",
                    "sn_ativo",
                )
                if campo in colunas
            ]

            if not campos_preferidos:
                print("Tabela empresas nao tem os campos esperados.")
                return

            campos_sql = ", ".join(f'"{campo}"' for campo in campos_preferidos)
            cursor.execute(
                f"""
                    SELECT {campos_sql}
                    FROM public.empresas
                    ORDER BY 1
                    LIMIT 80;
                """
            )

            print("Empresas:")
            for linha in cursor.fetchall():
                print(" | ".join("" if item is None else str(item) for item in linha))


if __name__ == "__main__":
    main()
