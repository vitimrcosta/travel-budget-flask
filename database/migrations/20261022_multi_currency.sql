USE controle_viagem;

ALTER TABLE gasto
    DROP CONSTRAINT chk_gasto_cotacao,
    MODIFY COLUMN moeda VARCHAR(3) NOT NULL DEFAULT 'BRL',
    ADD CONSTRAINT chk_gasto_cotacao
        CHECK ((moeda = 'BRL' AND cotacao = 1.00000000) OR (moeda <> 'BRL' AND cotacao > 0));