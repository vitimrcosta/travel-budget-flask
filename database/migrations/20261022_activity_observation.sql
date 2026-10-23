USE controle_viagem;

ALTER TABLE atividade
    ADD COLUMN observacao TEXT NULL AFTER custo_estimado;
