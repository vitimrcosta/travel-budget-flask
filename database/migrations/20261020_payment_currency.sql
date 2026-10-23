USE controle_viagem;

ALTER TABLE viagem
    ADD COLUMN moeda_base CHAR(3) NOT NULL DEFAULT 'BRL';

ALTER TABLE gasto
    ADD COLUMN forma_pagamento VARCHAR(30) NULL,
    ADD COLUMN observacao TEXT NULL,
    ADD COLUMN pago BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN moeda CHAR(3) NOT NULL DEFAULT 'BRL',
    ADD COLUMN valor_original DECIMAL(14,2) NULL,
    ADD COLUMN cotacao DECIMAL(18,8) NULL;

UPDATE gasto AS g
JOIN viagem AS v ON v.id = g.viagem_id
SET g.moeda = v.moeda_base,
    g.pago = (g.valor_real > 0),
    g.valor_original = CASE WHEN g.valor_real > 0 THEN g.valor_real ELSE NULL END,
    g.cotacao = CASE WHEN g.valor_real > 0 THEN 1.00000000 ELSE NULL END;

ALTER TABLE atividade
    MODIFY COLUMN custo_estimado DECIMAL(10,2) NULL DEFAULT NULL;
