USE controle_viagem;

ALTER TABLE gasto
    ADD UNIQUE KEY uq_gasto_id_viagem (id, viagem_id);

ALTER TABLE atividade
    ADD UNIQUE KEY uq_atividade_id_viagem (id, viagem_id);

CREATE TABLE participante (
    id INT NOT NULL AUTO_INCREMENT,
    viagem_id INT NOT NULL,
    nome VARCHAR(150) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_participante_viagem_nome (viagem_id, nome),
    UNIQUE KEY uq_participante_id_viagem (id, viagem_id),
    CONSTRAINT fk_participante_viagem FOREIGN KEY (viagem_id) REFERENCES viagem(id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE pagamento_gasto (
    id INT NOT NULL AUTO_INCREMENT,
    viagem_id INT NOT NULL,
    gasto_id INT NOT NULL,
    participante_id INT NULL,
    valor_brl DECIMAL(14,2) NOT NULL,
    forma_pagamento VARCHAR(30) NULL,
    PRIMARY KEY (id),
    KEY idx_pagamento_gasto (gasto_id, viagem_id),
    KEY idx_pagamento_participante (participante_id, viagem_id),
    CONSTRAINT chk_pagamento_gasto_valor CHECK (valor_brl > 0),
    CONSTRAINT fk_pagamento_gasto FOREIGN KEY (gasto_id, viagem_id) REFERENCES gasto(id, viagem_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_pagamento_participante FOREIGN KEY (participante_id, viagem_id) REFERENCES participante(id, viagem_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE anexo (
    id INT NOT NULL AUTO_INCREMENT,
    viagem_id INT NOT NULL,
    gasto_id INT NULL,
    atividade_id INT NULL,
    nome_original VARCHAR(255) NOT NULL,
    nome_armazenado VARCHAR(80) NOT NULL,
    mime_type VARCHAR(80) NOT NULL,
    tamanho_bytes INT UNSIGNED NOT NULL,
    is_capa BOOLEAN NOT NULL DEFAULT FALSE,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_anexo_nome_armazenado (nome_armazenado),
    KEY idx_anexo_viagem (viagem_id),
    KEY idx_anexo_gasto (gasto_id, viagem_id),
    KEY idx_anexo_atividade (atividade_id, viagem_id),
    CONSTRAINT fk_anexo_viagem FOREIGN KEY (viagem_id) REFERENCES viagem(id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_anexo_gasto FOREIGN KEY (gasto_id, viagem_id) REFERENCES gasto(id, viagem_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_anexo_atividade FOREIGN KEY (atividade_id, viagem_id) REFERENCES atividade(id, viagem_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;