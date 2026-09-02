# Tunel proprio do Clinux/Genesis

Hoje o conciliador consegue conectar no banco do Clinux de duas formas:

1. Pelo tunel que o proprio Clinux abre quando o programa esta aberto.
2. Pelo tunel proprio do conciliador, sem precisar abrir a tela do Clinux.

O segundo modo ja esta implementado, mas precisa de uma credencial SSH valida para uso externo ao programa.

## Resultado do teste atual

O `clinux.ini` possui:

- dados do banco PostgreSQL;
- usuario e senha do banco;
- host e porta SSH;
- usuario SSH;
- uma senha SSH alternativa/codificada.

O teste com essa senha alternativa/codificada falhou com `AuthenticationException`. Isso indica que essa senha provavelmente e interpretada pelo proprio Clinux, mas nao serve diretamente para abrir um tunel fora do programa.

## O que pedir ao suporte/TI

Pedir uma destas duas opcoes:

- senha SSH real do usuario de tunel; ou
- chave SSH privada autorizada para acessar o servidor.

Idealmente, criar um usuario somente para conciliacao, com acesso apenas ao tunel do PostgreSQL.

## Variaveis no .env

Adicionar ao arquivo `C:\ConciliaFinanceira\.env`:

```text
CLINUX_SSH_HOST=
CLINUX_SSH_PORT=1122
CLINUX_SSH_USER=
CLINUX_SSH_PASSWORD=
```

Ou, usando chave SSH:

```text
CLINUX_SSH_HOST=
CLINUX_SSH_PORT=1122
CLINUX_SSH_USER=
CLINUX_SSH_KEY_PATH=C:\ConciliaFinanceira\segredos\clinux_tunel
```

Os dados do banco podem continuar vindo do `clinux.ini`, mas tambem podem ser sobrescritos no `.env`:

```text
CLINUX_DB_HOST=10.17.90.50
CLINUX_DB_PORT=5432
CLINUX_DB_NAME=clinux_ctr
CLINUX_DB_USER=
CLINUX_DB_PASSWORD=
```

## Testar sem abrir o Clinux

Com o Clinux fechado e as credenciais SSH reais no `.env`:

```powershell
C:\ConciliaFinanceira\.venv\Scripts\python.exe C:\ConciliaFinanceira\python\testar_tunel_proprio_clinux.py
```

Se funcionar, o comando `atualizar_base.bat` tambem funcionara sem abrir o Clinux.
