CREATE SCHEMA raw;
CREATE SCHEMA staging;
CREATE SCHEMA ontology;
CREATE SCHEMA dq;

CREATE TABLE dq.ingestion_run (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source        text NOT NULL,
    table_name    text NOT NULL,
    source_file   text NOT NULL,
    source_sha256 text NOT NULL,
    row_count     bigint NOT NULL,
    loaded_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (table_name, source_sha256)
);
