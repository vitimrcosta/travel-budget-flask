USE controle_viagem;

ALTER TABLE viagem
    ADD COLUMN bandeira VARCHAR(12) NULL AFTER destino;
