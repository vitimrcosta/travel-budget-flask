USE controle_viagem;

ALTER TABLE reserva
    ADD COLUMN horario_checkin TIME NULL AFTER data_inicio,
    ADD COLUMN horario_checkout TIME NULL AFTER data_fim;
