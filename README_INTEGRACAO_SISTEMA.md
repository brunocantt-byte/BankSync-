# Integracao com o banco do sistema da empresa

O objetivo desta etapa e conectar o conciliador diretamente ao banco do sistema da empresa, de preferencia com usuario somente leitura.

## Dados que precisamos pedir ao suporte/TI

Peca estes dados:

- Tipo do banco: PostgreSQL ou SQL Server.
- Servidor/host.
- Porta.
- Nome do banco.
- Usuario somente leitura.
- Senha desse usuario.
- Quais tabelas ou views contem contas pagas/recebidas.

O usuario deve ter permissao apenas de `SELECT`. Nao precisa inserir, alterar nem apagar nada no banco do sistema.

## Variaveis no .env

Adicionar ao arquivo `C:\ConciliaFinanceira\.env`:

```text
SISTEMA_DB_TIPO=postgres
SISTEMA_DB_HOST=
SISTEMA_DB_PORT=5432
SISTEMA_DB_NAME=
SISTEMA_DB_USER=
SISTEMA_DB_PASSWORD=
```

Para SQL Server:

```text
SISTEMA_DB_TIPO=sqlserver
SISTEMA_DB_HOST=
SISTEMA_DB_PORT=1433
SISTEMA_DB_NAME=
SISTEMA_DB_USER=
SISTEMA_DB_PASSWORD=
SISTEMA_DB_DRIVER=ODBC Driver 18 for SQL Server
```

## Testar conexao

Depois de preencher as variaveis:

```powershell
C:\ConciliaFinanceira\.venv\Scripts\python.exe C:\ConciliaFinanceira\python\testar_conexao_sistema_db.py
```

Se funcionar, o comando vai listar as primeiras tabelas encontradas. A partir disso, identificamos a tabela certa de lancamentos financeiros e criamos o importador automatico para a base historica.

## Resultado do diagnostico local

No diagnostico feito agora, o PostgreSQL local apareceu ativo, mas com as credenciais atuais so foram encontrados:

- `concilia_financeira`
- `postgres`

Ou seja: ate aqui nao apareceu um banco separado do sistema da empresa no PostgreSQL local.
