CREATE DATABASE IF NOT EXISTS controle_viagem CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE controle_viagem;

CREATE TABLE IF NOT EXISTS viagem (
    id INT NOT NULL AUTO_INCREMENT,
    destino VARCHAR(150) NOT NULL,
    bandeira VARCHAR(12) NULL,
    data_ida DATE NOT NULL,
    data_volta DATE NOT NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS gasto (
    id INT NOT NULL AUTO_INCREMENT,
    viagem_id INT NOT NULL,
    data_gasto DATE NOT NULL,
    descricao VARCHAR(255) NOT NULL,
    categoria VARCHAR(100) NOT NULL,
    moeda VARCHAR(3) NOT NULL DEFAULT 'BRL',
    valor_original DECIMAL(14,2) NOT NULL,
    cotacao DECIMAL(18,8) NOT NULL DEFAULT 1.00000000,
    forma_pagamento VARCHAR(30) NULL,
    observacao TEXT NULL,
    pago BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (id),
    KEY idx_viagem_id (viagem_id),
    KEY idx_gasto_categoria (viagem_id, categoria),
    UNIQUE KEY uq_gasto_id_viagem (id, viagem_id),

    CONSTRAINT chk_gasto_cotacao
        CHECK ((moeda = 'BRL' AND cotacao = 1.00000000) OR (moeda <> 'BRL' AND cotacao > 0)),
    CONSTRAINT fk_gasto_viagem
        FOREIGN KEY (viagem_id) REFERENCES viagem(id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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

CREATE TABLE IF NOT EXISTS atividade (
    id INT NOT NULL AUTO_INCREMENT,
    viagem_id INT NOT NULL,
    nome VARCHAR(150) NOT NULL,
    data_atividade DATE NOT NULL,
    horario TIME NULL,
    local VARCHAR(255) NULL,
    custo_estimado DECIMAL(10,2) NULL DEFAULT NULL,
    observacao TEXT NULL,
    situacao VARCHAR(20) NOT NULL DEFAULT 'planejada',
    PRIMARY KEY (id),
    KEY idx_viagem_id (viagem_id),
    UNIQUE KEY uq_atividade_id_viagem (id, viagem_id),
    CONSTRAINT fk_atividade_viagem
        FOREIGN KEY (viagem_id) REFERENCES viagem(id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS reserva (
    id INT NOT NULL AUTO_INCREMENT,
    viagem_id INT NOT NULL,
    tipo VARCHAR(30) NOT NULL,
    fornecedor VARCHAR(150) NOT NULL,
    codigo_confirmacao VARCHAR(150) NULL,
    data_inicio DATE NOT NULL,
    horario_checkin TIME NULL,
    data_fim DATE NOT NULL,
    horario_checkout TIME NULL,
    local VARCHAR(255) NULL,
    prazo_cancelamento DATE NULL,
    situacao VARCHAR(20) NOT NULL DEFAULT 'pendente',
    observacao TEXT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_reserva_id_viagem (id, viagem_id),
    KEY idx_reserva_viagem_data (viagem_id, data_inicio),
    CONSTRAINT fk_reserva_viagem
        FOREIGN KEY (viagem_id) REFERENCES viagem(id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS participante (
    id INT NOT NULL AUTO_INCREMENT,
    viagem_id INT NOT NULL,
    nome VARCHAR(150) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_participante_viagem_nome (viagem_id, nome),
    UNIQUE KEY uq_participante_id_viagem (id, viagem_id),
    CONSTRAINT fk_participante_viagem
        FOREIGN KEY (viagem_id) REFERENCES viagem(id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS pagamento_gasto (
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
    CONSTRAINT fk_pagamento_gasto
        FOREIGN KEY (gasto_id, viagem_id) REFERENCES gasto(id, viagem_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_pagamento_participante
        FOREIGN KEY (participante_id, viagem_id) REFERENCES participante(id, viagem_id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS anexo (
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
    CONSTRAINT fk_anexo_viagem
        FOREIGN KEY (viagem_id) REFERENCES viagem(id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_anexo_gasto
        FOREIGN KEY (gasto_id, viagem_id) REFERENCES gasto(id, viagem_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT fk_anexo_atividade
        FOREIGN KEY (atividade_id, viagem_id) REFERENCES atividade(id, viagem_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
