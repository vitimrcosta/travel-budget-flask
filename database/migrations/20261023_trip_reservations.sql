USE controle_viagem;

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
    CONSTRAINT fk_reserva_viagem FOREIGN KEY (viagem_id) REFERENCES viagem(id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
