from pathlib import Path
import hashlib
import os
import re
from datetime import datetime

import psycopg
from dotenv import load_dotenv


# ============================================================
# CONFIGURAÇÃO
# ============================================================

load_dotenv()

PASTA_ENTRADA = Path(r"C:\ConciliaFinanceira\entrada")

# Conta bancária que criamos para este OFX
CONTA_BANCARIA_ID = 2


# ============================================================
# CONEXÃO COM POSTGRESQL
# ============================================================

def conectar_banco():
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


# ============================================================
# LOCALIZAR OFX
# ============================================================

def localizar_ofx():
    arquivos = list(PASTA_ENTRADA.glob("*.ofx"))

    if not arquivos:
        raise FileNotFoundError(
            f"Nenhum arquivo OFX encontrado em: {PASTA_ENTRADA}"
        )

    if len(arquivos) > 1:
        print("⚠️ Mais de um arquivo OFX encontrado.")
        print("Será utilizado o primeiro.")

    return arquivos[0]


# ============================================================
# HASH
# ============================================================

def calcular_hash(caminho):
    sha256 = hashlib.sha256()

    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            sha256.update(bloco)

    return sha256.hexdigest()


# ============================================================
# LEITURA
# ============================================================

def ler_arquivo(caminho):
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return caminho.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue

    raise ValueError(
        "Não foi possível identificar a codificação do arquivo OFX."
    )


# ============================================================
# EXTRAIR TAG
# ============================================================

def extrair_tag(conteudo, tag):
    padrao = rf"<{tag}>\s*(.*?)(?=\s*<|$)"

    resultado = re.search(
        padrao,
        conteudo,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if resultado:
        return resultado.group(1).strip()

    return None


# ============================================================
# DATA
# ============================================================

def converter_data(data_ofx):
    if not data_ofx:
        return None

    apenas_data = data_ofx[:8]

    try:
        return datetime.strptime(
            apenas_data,
            "%Y%m%d"
        ).date()

    except ValueError:
        return None


# ============================================================
# VALOR
# ============================================================

def converter_valor(valor):
    if not valor:
        return 0.0

    try:
        return abs(
            float(
                valor.replace(",", ".").strip()
            )
        )

    except ValueError:
        return 0.0


# ============================================================
# TIPO MOVIMENTO
# ============================================================

def identificar_tipo(trntype):
    if not trntype:
        return None

    trntype = trntype.upper().strip()

    if trntype == "CREDIT":
        return "ENTRADA"

    if trntype == "DEBIT":
        return "SAIDA"

    return None


# ============================================================
# IDENTIFICAR SALDOS
# ============================================================

def identificar_registro(descricao):
    if not descricao:
        return "MOVIMENTACAO"

    descricao_normalizada = descricao.upper()

    if "SALDO ANTERIOR" in descricao_normalizada:
        return "SALDO_ANTERIOR"

    if "SALDO TOTAL DISPONIVEL DIA" in descricao_normalizada:
        return "SALDO_DIA"

    if "SALDO TOTAL DISPONÍVEL DIA" in descricao_normalizada:
        return "SALDO_DIA"

    return "MOVIMENTACAO"


# ============================================================
# EXTRAIR TRANSAÇÕES
# ============================================================

def extrair_transacoes(conteudo):
    return re.findall(
        r"<STMTTRN>(.*?)</STMTTRN>",
        conteudo,
        flags=re.IGNORECASE | re.DOTALL,
    )


# ============================================================
# PROCESSAR TRANSAÇÃO
# ============================================================

def processar_transacao(bloco):
    trntype = extrair_tag(bloco, "TRNTYPE")
    dtposted = extrair_tag(bloco, "DTPOSTED")
    trnamt = extrair_tag(bloco, "TRNAMT")
    fitid = extrair_tag(bloco, "FITID")
    checknum = extrair_tag(bloco, "CHECKNUM")
    memo = extrair_tag(bloco, "MEMO")

    return {
        "tipo_registro": identificar_registro(memo),
        "tipo_movimento": identificar_tipo(trntype),
        "data": converter_data(dtposted),
        "valor": converter_valor(trnamt),
        "fitid": fitid,
        "documento": checknum,
        "descricao": memo,
    }


# ============================================================
# OBTER ARQUIVO IMPORTADO
# ============================================================

def buscar_arquivo(hash_arquivo):
    sql = """
        SELECT
            id,
            nome_arquivo,
            status
        FROM arquivos_importados
        WHERE hash_arquivo = %s;
    """

    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(sql, (hash_arquivo,))
            return cursor.fetchone()


# ============================================================
# VERIFICAR TRANSAÇÃO EXISTENTE
# ============================================================

def transacao_existe(fitid):
    sql = """
        SELECT id
        FROM transacoes_bancarias
        WHERE identificador_transacao = %s
          AND conta_bancaria_id = %s
        LIMIT 1;
    """

    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    fitid,
                    CONTA_BANCARIA_ID,
                ),
            )

            return cursor.fetchone() is not None


# ============================================================
# INSERIR TRANSAÇÃO
# ============================================================

def inserir_transacao(transacao, arquivo_id):
    sql = """
        INSERT INTO transacoes_bancarias (
            arquivo_id,
            conta_bancaria_id,
            data_movimento,
            tipo_movimento,
            valor,
            descricao,
            documento,
            identificador_transacao
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s
        );
    """

    with conectar_banco() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    arquivo_id,
                    CONTA_BANCARIA_ID,
                    transacao["data"],
                    transacao["tipo_movimento"],
                    transacao["valor"],
                    transacao["descricao"],
                    transacao["documento"],
                    transacao["fitid"],
                ),
            )

        conexao.commit()


# ============================================================
# PROCESSAR E IMPORTAR
# ============================================================

def importar_transacoes(arquivo, arquivo_id):
    conteudo = ler_arquivo(arquivo)

    blocos = extrair_transacoes(conteudo)

    movimentacoes = []

    for bloco in blocos:
        transacao = processar_transacao(bloco)

        if transacao["tipo_registro"] != "MOVIMENTACAO":
            continue

        movimentacoes.append(transacao)

    inseridas = 0
    duplicadas = 0
    erros = 0

    for indice, transacao in enumerate(
        movimentacoes,
        start=1
    ):

        try:

            if not transacao["fitid"]:
                print(
                    f"⚠️ Registro #{indice} "
                    f"sem FITID. Ignorado."
                )
                erros += 1
                continue

            if transacao["tipo_movimento"] not in (
                "ENTRADA",
                "SAIDA",
            ):
                print(
                    f"⚠️ Registro #{indice} "
                    f"com tipo inválido. Ignorado."
                )
                erros += 1
                continue

            if transacao["data"] is None:
                print(
                    f"⚠️ FITID {transacao['fitid']} "
                    f"sem data válida. Ignorado."
                )
                erros += 1
                continue

            if transacao_existe(
                transacao["fitid"]
            ):
                duplicadas += 1
                continue

            inserir_transacao(
                transacao,
                arquivo_id
            )

            inseridas += 1

            if inseridas % 50 == 0:
                print(
                    f"📥 {inseridas} "
                    f"transações inseridas..."
                )

        except Exception as erro:
            erros += 1

            print(
                f"❌ Erro no FITID "
                f"{transacao['fitid']}: "
                f"{erro}"
            )

    return (
        len(movimentacoes),
        inseridas,
        duplicadas,
        erros,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "🚀 Importando movimentações bancárias...\n"
    )

    try:

        # ----------------------------------------------------
        # 1. Localizar arquivo
        # ----------------------------------------------------

        arquivo = localizar_ofx()

        print(
            f"📄 Arquivo: "
            f"{arquivo.name}"
        )

        # ----------------------------------------------------
        # 2. Hash
        # ----------------------------------------------------

        hash_arquivo = calcular_hash(
            arquivo
        )

        print(
            f"🔐 SHA-256: "
            f"{hash_arquivo}"
        )

        # ----------------------------------------------------
        # 3. Buscar arquivo no banco
        # ----------------------------------------------------

        registro = buscar_arquivo(
            hash_arquivo
        )

        if not registro:

            print(
                "\n❌ O arquivo não está registrado "
                "em arquivos_importados."
            )

            print(
                "Execute primeiro a versão anterior "
                "do importador."
            )

            return

        arquivo_id = registro[0]

        print(
            f"\n🆔 Arquivo ID: "
            f"{arquivo_id}"
        )

        # ----------------------------------------------------
        # 4. Importar
        # ----------------------------------------------------

        total, inseridas, duplicadas, erros = (
            importar_transacoes(
                arquivo,
                arquivo_id
            )
        )

        # ----------------------------------------------------
        # 5. Resultado
        # ----------------------------------------------------

        print("\n" + "=" * 55)
        print("📊 RESULTADO DA IMPORTAÇÃO")
        print("=" * 55)

        print(
            f"Registros movimentação: {total}"
        )

        print(
            f"✅ Inseridas: {inseridas}"
        )

        print(
            f"🔁 Já existentes: {duplicadas}"
        )

        print(
            f"❌ Com erro: {erros}"
        )

        print("=" * 55)

        print(
            "\n✅ Processo concluído."
        )

    except Exception as erro:

        print("\n❌ ERRO")
        print(
            f"Tipo: {type(erro).__name__}"
        )
        print(
            f"Mensagem: {erro}"
        )


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":
    main()
