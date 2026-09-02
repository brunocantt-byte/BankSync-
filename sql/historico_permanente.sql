-- ============================================================
-- BASE HISTORICA PERMANENTE
-- Complementa o schema original sem apagar dados existentes.
-- ============================================================

ALTER TABLE arquivos_importados
    ADD COLUMN IF NOT EXISTS empresa_id BIGINT REFERENCES empresas(id),
    ADD COLUMN IF NOT EXISTS conta_bancaria_id BIGINT REFERENCES contas_bancarias(id),
    ADD COLUMN IF NOT EXISTS origem VARCHAR(30),
    ADD COLUMN IF NOT EXISTS periodo_inicio DATE,
    ADD COLUMN IF NOT EXISTS periodo_fim DATE,
    ADD COLUMN IF NOT EXISTS caminho_arquivado TEXT,
    ADD COLUMN IF NOT EXISTS metadados JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE lancamentos_sistema
    ADD COLUMN IF NOT EXISTS metadados JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_origem_arquivo_importado'
    ) THEN
        ALTER TABLE arquivos_importados
            ADD CONSTRAINT chk_origem_arquivo_importado
            CHECK (
                origem IS NULL OR origem IN (
                    'BANCO',
                    'SISTEMA',
                    'OUTRO'
                )
            );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS conciliacao_execucoes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    empresa_id BIGINT REFERENCES empresas(id),
    conta_bancaria_id BIGINT REFERENCES contas_bancarias(id),
    periodo_inicio DATE,
    periodo_fim DATE,
    nome VARCHAR(180),
    status VARCHAR(30) NOT NULL DEFAULT 'PROCESSANDO',
    parametros JSONB NOT NULL DEFAULT '{}'::jsonb,
    totais JSONB NOT NULL DEFAULT '{}'::jsonb,
    arquivo_relatorio TEXT,
    observacao TEXT,
    iniciado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finalizado_em TIMESTAMP,

    CONSTRAINT chk_status_conciliacao_execucao
        CHECK (status IN ('PROCESSANDO', 'PROCESSADO', 'ERRO'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_transacoes_conta_identificador
    ON transacoes_bancarias(conta_bancaria_id, identificador_transacao)
    WHERE identificador_transacao IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_lancamentos_empresa_identificador
    ON lancamentos_sistema(empresa_id, identificador_externo)
    WHERE identificador_externo IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_arquivos_importados_origem_periodo
    ON arquivos_importados(origem, periodo_inicio, periodo_fim);

CREATE INDEX IF NOT EXISTS idx_transacoes_conta_data
    ON transacoes_bancarias(conta_bancaria_id, data_movimento);

CREATE INDEX IF NOT EXISTS idx_lancamentos_empresa_pagamento
    ON lancamentos_sistema(empresa_id, (COALESCE(data_pagamento, data_lancamento)));
