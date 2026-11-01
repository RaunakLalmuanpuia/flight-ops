ALTER TABLE dq.ingestion_run ADD COLUMN quarantined_count bigint NOT NULL DEFAULT 0;

CREATE TABLE dq.quarantined_row (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ingestion_run_id bigint NOT NULL REFERENCES dq.ingestion_run (id),
    line_number      bigint NOT NULL,
    reason           text NOT NULL,
    fields           text[] NOT NULL
);
