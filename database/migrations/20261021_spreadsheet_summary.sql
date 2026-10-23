USE controle_viagem;

ALTER TABLE viagem
    DROP COLUMN moeda_base,
    DROP COLUMN orcamento_total;

ALTER TABLE gasto
    DROP COLUMN valor_previsto,
    DROP COLUMN valor_real,
    ADD COLUMN data_gasto DATE NOT NULL AFTER viagem_id,
    MODIFY COLUMN moeda ENUM('BRL', 'CLP') NOT NULL DEFAULT 'BRL',
    MODIFY COLUMN valor_original DECIMAL(14,2) NOT NULL,
    MODIFY COLUMN cotacao DECIMAL(18,8) NOT NULL DEFAULT 1.00000000,
    ADD KEY idx_gasto_categoria (viagem_id, categoria),
    ADD CONSTRAINT chk_gasto_cotacao
        CHECK ((moeda = 'BRL' AND cotacao = 1.00000000) OR (moeda = 'CLP' AND cotacao > 0));

CREATE TABLE IF NOT EXISTS planejamento_categoria (
    id INT NOT NULL AUTO_INCREMENT,
    viagem_id INT NOT NULL,
    categoria VARCHAR(100) NOT NULL,
    valor_previsto DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    PRIMARY KEY (id),
    UNIQUE KEY uq_planejamento_viagem_categoria (viagem_id, categoria),
    CONSTRAINT fk_planejamento_viagem
        FOREIGN KEY (viagem_id) REFERENCES viagem(id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
