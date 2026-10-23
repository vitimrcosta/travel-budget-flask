USE controle_viagem;

ALTER TABLE atividade
    ADD COLUMN horario TIME NULL AFTER data_atividade,
    ADD COLUMN local VARCHAR(255) NULL AFTER horario,
    ADD COLUMN situacao VARCHAR(20) NOT NULL DEFAULT 'planejada' AFTER observacao;