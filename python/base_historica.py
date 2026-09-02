from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import hashlib
import json
import os
import shutil

import psycopg
from dotenv import load_dotenv


BASE_DIR = Path(r"C:\ConciliaFinanceira")
ENTRADA_DIR = BASE_DIR / "entrada"
BANCO_ENTRADA_DIR = ENTRADA_DIR / "banco"
SISTEMA_ENTRADA_DIR = ENTRADA_DIR / "sistema"
DADOS_DIR = BASE_DIR / "dados"
EXTRACOES_DIR = DADOS_DIR / "extracoes"
PROCESSADOS_DIR = BASE_DIR / "processados"
ERROS_DIR = BASE_DIR / "erros"


def conectar_banco():
    load_dotenv(BASE_DIR / ".env")
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def garantir_pastas():
    for pasta in (
        BANCO_ENTRADA_DIR,
        SISTEMA_ENTRADA_DIR,
        EXTRACOES_DIR,
        PROCESSADOS_DIR / "banco",
        PROCESSADOS_DIR / "sistema",
        ERROS_DIR,
    ):
        pasta.mkdir(parents=True, exist_ok=True)


def calcular_hash(caminho: Path) -> str:
    sha256 = hashlib.sha256()

    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            sha256.update(bloco)

    return sha256.hexdigest()


def decimal_para_json(valor):
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    return valor


def detectar_periodo(registros, campo_data: str):
    datas = [
        registro[campo_data]
        for registro in registros
        if registro.get(campo_data)
    ]

    if not datas:
        return None, None

    datas_normalizadas = []
    for valor in datas:
        if isinstance(valor, str):
            datas_normalizadas.append(datetime.strptime(valor, "%d/%m/%Y").date())
        elif isinstance(valor, datetime):
            datas_normalizadas.append(valor.date())
        else:
            datas_normalizadas.append(valor)

    return min(datas_normalizadas), max(datas_normalizadas)


def arquivar_arquivo(caminho: Path, origem: str, hash_arquivo: str, periodo_inicio):
    periodo = periodo_inicio.isoformat()[:7] if periodo_inicio else "sem-periodo"
    destino_dir = PROCESSADOS_DIR / origem.lower() / periodo
    destino_dir.mkdir(parents=True, exist_ok=True)

    destino = destino_dir / f"{hash_arquivo[:12]}_{caminho.name}"
    if not destino.exists():
        shutil.copy2(caminho, destino)

    return destino


def registrar_arquivo_historico(
    cursor,
    *,
    caminho: Path,
    tipo_arquivo: str,
    origem: str,
    hash_arquivo: str,
    quantidade: int,
    empresa_id=None,
    conta_bancaria_id=None,
    periodo_inicio=None,
    periodo_fim=None,
    caminho_arquivado: Path | None = None,
    metadados: dict | None = None,
):
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
                conta_bancaria_id,
                origem,
                periodo_inicio,
                periodo_fim,
                caminho_arquivado,
                metadados
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, 'PROCESSADO',
                CURRENT_TIMESTAMP, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (hash_arquivo) DO UPDATE
            SET quantidade_registros = EXCLUDED.quantidade_registros,
                status = 'PROCESSADO',
                processado_em = CURRENT_TIMESTAMP,
                empresa_id = COALESCE(EXCLUDED.empresa_id, arquivos_importados.empresa_id),
                conta_bancaria_id = COALESCE(EXCLUDED.conta_bancaria_id, arquivos_importados.conta_bancaria_id),
                origem = COALESCE(EXCLUDED.origem, arquivos_importados.origem),
                periodo_inicio = COALESCE(EXCLUDED.periodo_inicio, arquivos_importados.periodo_inicio),
                periodo_fim = COALESCE(EXCLUDED.periodo_fim, arquivos_importados.periodo_fim),
                caminho_arquivado = COALESCE(EXCLUDED.caminho_arquivado, arquivos_importados.caminho_arquivado),
                metadados = arquivos_importados.metadados || EXCLUDED.metadados
            RETURNING id;
        """,
        (
            caminho.name,
            str(caminho),
            tipo_arquivo,
            caminho.stat().st_size,
            hash_arquivo,
            quantidade,
            empresa_id,
            conta_bancaria_id,
            origem,
            periodo_inicio,
            periodo_fim,
            str(caminho_arquivado) if caminho_arquivado else None,
            json.dumps(metadados or {}, default=decimal_para_json),
        ),
    )

    return cursor.fetchone()[0]
