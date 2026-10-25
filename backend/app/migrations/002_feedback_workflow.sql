-- Visszajelzés-kezelés az adminon: állapot (új / vizsgálva / javítva / nem hiba) + admin-megjegyzés,
-- és a visszajelzésből felvett mérési esetek (a következő mérési futás a YAML-kérdéssor mellett ezeket is méri).

ALTER TABLE feedback
    ADD COLUMN status     text NOT NULL DEFAULT 'uj' CHECK (status IN ('uj', 'vizsgalva', 'javitva', 'nem_hiba')),
    ADD COLUMN admin_note text,
    ADD COLUMN status_at  timestamptz;

CREATE TABLE eval_cases (
    id         serial PRIMARY KEY,
    message_id uuid REFERENCES messages ON DELETE SET NULL,   -- melyik (visszajelzett) válaszból lett
    level      text NOT NULL CHECK (level IN ('rag', 'prompt')),
    question   text NOT NULL,
    doc_file   text,                                         -- rag: az elvárt útmutató fájlneve
    pages      int[],                                        -- rag: az elvárt oldal(ak)
    expect     text CHECK (expect IN ('answer', 'not_found', 'refuse', 'clarify')),  -- prompt: elvárt viselkedés
    facts      text[],                                       -- prompt: a helyes válasz kulcselemei
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX eval_cases_message_idx ON eval_cases (message_id);
