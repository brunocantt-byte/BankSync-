-- ============================================================
-- BANCO DE DADOS: CONCILIAÇÃO FINANCEIRA
-- ============================================================

-- ============================================================
-- 1. EMPRESAS
-- ============================================================

CREATE TABLE IF NOT EXISTS empresas (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    razao_social VARCHAR(200) NOT NULL,
    nome_fantasia VARCHAR(200),
    cnpj VARCHAR(20) NOT NULL UNIQUE,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 2. BANCOS
-- ============================================================

CREATE TABLE IF NOT EXISTS bancos (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo_banco VARCHAR(10),
    nome VARCHAR(100) NOT NULL UNIQUE,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 3. CONTAS BANCÁRIAS
-- ============================================================

CREATE TABLE IF NOT EXISTS contas_bancarias (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    empresa_id BIGINT NOT NULL,
    banco_id BIGINT NOT NULL,
    agencia VARCHAR(20),
    conta VARCHAR(30) NOT NULL,
    digito VARCHAR(5),
    descricao VARCHAR(150),
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_conta_empresa
        FOREIGN KEY (empresa_id)
        REFERENCES empresas(id),

    CONSTRAINT fk_conta_banco
        FOREIGN KEY (banco_id)
        REFERENCES bancos(id),

    CONSTRAINT uq_conta_empresa_banco
        UNIQUE (empresa_id, banco_id, agencia, conta, digito)
);

-- ============================================================
-- 4. ARQUIVOS IMPORTADOS
-- Controle para não processar o mesmo arquivo duas vezes
-- ============================================================

CREATE TABLE IF NOT EXISTS arquivos_importados (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome_arquivo VARCHAR(255) NOT NULL,
    caminho_arquivo TEXT NOT NULL,
    tipo_arquivo VARCHAR(20),
    tamanho_bytes BIGINT,
    hash_arquivo VARCHAR(128) NOT NULL UNIQUE,
    data_arquivo TIMESTAMP,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDENTE',
    quantidade_registros INTEGER DEFAULT 0,
    mensagem_erro TEXT,
    processado_em TIMESTAMP,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_status_arquivo
        CHECK (status IN ('PENDENTE', 'PROCESSANDO', 'PROCESSADO', 'ERRO'))
);

-- ============================================================
-- 5. TRANSAÇÕES BANCÁRIAS
-- Tudo que efetivamente aconteceu no banco
-- ============================================================

CREATE TABLE IF NOT EXISTS transacoes_bancarias (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    arquivo_id BIGINT,
    conta_bancaria_id BIGINT NOT NULL,

    data_movimento DATE NOT NULL,
    data_hora TIMESTAMP,

    tipo_movimento VARCHAR(10) NOT NULL,
    valor NUMERIC(18,2) NOT NULL,

    descricao TEXT,
    documento VARCHAR(100),
    identificador_transacao VARCHAR(150),

    saldo_anterior NUMERIC(18,2),
    saldo_posterior NUMERIC(18,2),

    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_transacao_arquivo
        FOREIGN KEY (arquivo_id)
        REFERENCES arquivos_importados(id),

    CONSTRAINT fk_transacao_conta
        FOREIGN KEY (conta_bancaria_id)
        REFERENCES contas_bancarias(id),

    CONSTRAINT chk_tipo_movimento
        CHECK (tipo_movimento IN ('ENTRADA', 'SAIDA')),

    CONSTRAINT chk_valor_positivo
        CHECK (valor >= 0)
);

-- ============================================================
-- 6. LANÇAMENTOS DO SISTEMA / ERP
-- O que a empresa esperava que acontecesse
-- ============================================================

CREATE TABLE IF NOT EXISTS lancamentos_sistema (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    empresa_id BIGINT NOT NULL,

    data_lancamento DATE,
    data_vencimento DATE,
    data_pagamento DATE,

    tipo_movimento VARCHAR(10) NOT NULL,

    valor NUMERIC(18,2) NOT NULL,

    fornecedor_cliente VARCHAR(200),
    documento VARCHAR(100),
    cnpj_cpf VARCHAR(20),

    descricao TEXT,
    categoria VARCHAR(150),
    centro_custo VARCHAR(150),

    sistema_origem VARCHAR(100),

    identificador_externo VARCHAR(150),

    status VARCHAR(30) NOT NULL DEFAULT 'ABERTO',

    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_lancamento_empresa
        FOREIGN KEY (empresa_id)
        REFERENCES empresas(id),

    CONSTRAINT chk_tipo_lancamento
        CHECK (tipo_movimento IN ('ENTRADA', 'SAIDA')),

    CONSTRAINT chk_valor_lancamento
        CHECK (valor >= 0),

    CONSTRAINT chk_status_lancamento
        CHECK (
            status IN (
                'ABERTO',
                'CONCILIADO',
                'PENDENTE',
                'CANCELADO'
            )
        )
);

-- ============================================================
-- 7. CONCILIAÇÕES
-- Resultado da análise entre banco e sistema
-- ============================================================

CREATE TABLE IF NOT EXISTS conciliacoes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    status VARCHAR(30) NOT NULL,

    score NUMERIC(5,2),

    metodo VARCHAR(50),

    observacao TEXT,

    revisado BOOLEAN NOT NULL DEFAULT FALSE,

    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_status_conciliacao
        CHECK (
            status IN (
                'CONCILIADO',
                'POSSIVEL_CORRESPONDENCIA',
                'DIVERGENCIA',
                'NAO_ENCONTRADO',
                'DUPLICIDADE',
                'PENDENTE'
            )
        ),

    CONSTRAINT chk_score
        CHECK (
            score IS NULL
            OR (score >= 0 AND score <= 100)
        )
);

-- ============================================================
-- 8. VÍNCULOS DA CONCILIAÇÃO
-- Permite conciliar vários lançamentos com uma ou mais transações
-- ============================================================

CREATE TABLE IF NOT EXISTS conciliacao_vinculos (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    conciliacao_id BIGINT NOT NULL,
    transacao_bancaria_id BIGINT NOT NULL,
    lancamento_sistema_id BIGINT NOT NULL,

    valor_conciliado NUMERIC(18,2),

    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_vinculo_conciliacao
        FOREIGN KEY (conciliacao_id)
        REFERENCES conciliacoes(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_vinculo_transacao
        FOREIGN KEY (transacao_bancaria_id)
        REFERENCES transacoes_bancarias(id),

    CONSTRAINT fk_vinculo_lancamento
        FOREIGN KEY (lancamento_sistema_id)
        REFERENCES lancamentos_sistema(id)
);

-- ============================================================
-- 9. ÍNDICES
-- Melhoram a velocidade das consultas e conciliações
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_transacoes_data
    ON transacoes_bancarias(data_movimento);

CREATE INDEX IF NOT EXISTS idx_transacoes_valor
    ON transacoes_bancarias(valor);

CREATE INDEX IF NOT EXISTS idx_transacoes_documento
    ON transacoes_bancarias(documento);

CREATE INDEX IF NOT EXISTS idx_transacoes_conta
    ON transacoes_bancarias(conta_bancaria_id);

CREATE INDEX IF NOT EXISTS idx_lancamentos_data
    ON lancamentos_sistema(data_lancamento);

CREATE INDEX IF NOT EXISTS idx_lancamentos_valor
    ON lancamentos_sistema(valor);

CREATE INDEX IF NOT EXISTS idx_lancamentos_documento
    ON lancamentos_sistema(documento);

CREATE INDEX IF NOT EXISTS idx_lancamentos_empresa
    ON lancamentos_sistema(empresa_id);

CREATE INDEX IF NOT EXISTS idx_conciliacoes_status
    ON conciliacoes(status);

-- ============================================================
-- FIM DO SCHEMA
-- ============================================================