-- 0016_operator_notes.sql — READY_QUEUE D-17: the operator-note store (Michael's own mechanic knowledge).
-- Spec: Agent 03 docs/research/agent-03-model-knowledge-source-plan.md §7 (research/agent-03-economics @ b41a0f8).
-- Ruling (Agent 01): Option A, no contract change — a dedicated append-only table with DB CHECKs, plus a
-- LESSON_RECORDED receipt with entity_type 'operator_note' (OPERATOR_NOTE_RECORDED is queued for ADR-0009 item 12).
-- mbos.lessons is deliberately not reused: it cannot enforce "a note must name a model".
--
-- Invariants held IN THE DATABASE:
--   * a note names a model: every match group has BOTH non-empty makes AND models
--   * the human provenance row exists FIRST (actor_type human, human_actor set, tool_name+tool_version), is the
--     note's provenance_id, and entered_by equals its human_actor
--   * the note's receipt is written in the SAME transaction and cites that provenance
--   * insert-only; an edit or retraction is a new row linking `supersedes` to the current chain head (no forks)
--   * basis is always RECOMMENDATION (owner-stated, never FACT)
--   * only the human channel (Operator UI = role approver) may insert; every other role reads

CREATE FUNCTION mbos.nonempty_text_array(a jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN jsonb_typeof(a) = 'array' AND jsonb_array_length(a) > 0
                THEN NOT EXISTS (SELECT 1 FROM jsonb_array_elements(a) e
                                 WHERE jsonb_typeof(e) <> 'string' OR btrim(e #>> '{}') = '')
                ELSE false END
$$;

CREATE FUNCTION mbos.valid_note_match(m jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN jsonb_typeof(m) = 'array' AND jsonb_array_length(m) > 0
                THEN NOT EXISTS (SELECT 1 FROM jsonb_array_elements(m) g
                                 WHERE jsonb_typeof(g) <> 'object'
                                    OR NOT mbos.nonempty_text_array(g -> 'makes')
                                    OR NOT mbos.nonempty_text_array(g -> 'models'))
                ELSE false END
$$;

CREATE TABLE mbos.operator_notes (
    seq                 bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    note_id             text PRIMARY KEY CHECK (note_id ~ '^mn_[0-9A-HJKMNP-TV-Z]{26}$'),
    category            text NOT NULL CHECK (category IN ('trailer','mower','generator','welder','compressor','tool',
                            'commercial_equipment','mechanical_equipment','project_vehicle','other_asset')),
    match               jsonb NOT NULL CHECK (mbos.valid_note_match(match)),
    kind                text NOT NULL CHECK (kind IN ('failure_mode','expensive_part','parts_availability',
                            'known_weakness','resale_demand','economic')),
    statement           text NOT NULL CHECK (btrim(statement) <> '' AND char_length(statement) <= 600),
    plan_hint           text CHECK (plan_hint IS NULL OR (btrim(plan_hint) <> '' AND char_length(plan_hint) <= 600)),
    entered_by          text NOT NULL CHECK (btrim(entered_by) <> ''),
    entered_at          timestamptz NOT NULL,                       -- tz-aware by type; supplied by the entry channel
    basis_of_knowledge  text NOT NULL CHECK (btrim(basis_of_knowledge) <> ''),
    provenance_id       text NOT NULL REFERENCES mbos.provenance (provenance_id),
    reference_url       text CHECK (reference_url IS NULL OR reference_url LIKE 'https://_%'),
    review_after        date,
    basis               text NOT NULL DEFAULT 'RECOMMENDATION' CHECK (basis = 'RECOMMENDATION'),
    supersedes          text UNIQUE REFERENCES mbos.operator_notes (note_id),     -- UNIQUE: a chain cannot fork
    retracted           boolean NOT NULL DEFAULT false,
    CONSTRAINT operator_notes_not_self_superseding CHECK (supersedes IS DISTINCT FROM note_id),
    CONSTRAINT operator_notes_retraction_links CHECK (NOT retracted OR supersedes IS NOT NULL)
);
CREATE INDEX operator_notes_category_idx ON mbos.operator_notes (category, kind);
CREATE INDEX operator_notes_match_gin ON mbos.operator_notes USING gin (match jsonb_path_ops);
COMMENT ON TABLE mbos.operator_notes IS
    'Michael''s own mechanic notes (D-17). Append-only; edits/retractions are new rows via supersedes. '
    'Read the folded view mbos.v_operator_notes_current / mbos.operator_notes_document().';
SELECT mbos.make_append_only('mbos.operator_notes');

-- Human provenance first; chain rules.
CREATE FUNCTION mbos.operator_notes_before_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE pv mbos.provenance; prior mbos.operator_notes;
BEGIN
    SELECT * INTO pv FROM mbos.provenance WHERE provenance_id = NEW.provenance_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'mbos: operator note % needs its human provenance %, inserted first', NEW.note_id, NEW.provenance_id
            USING ERRCODE = 'MB002';
    END IF;
    IF pv.actor_type <> 'human' OR coalesce(btrim(pv.human_actor), '') = '' OR pv.tool_name IS NULL
       OR pv.tool_version IS NULL OR pv.basis <> 'RECOMMENDATION' THEN
        RAISE EXCEPTION 'mbos: provenance % is not a human RECOMMENDATION record (actor_type human, human_actor, tool_name+tool_version)',
            NEW.provenance_id USING ERRCODE = 'MB002';
    END IF;
    IF pv.human_actor <> NEW.entered_by THEN
        RAISE EXCEPTION 'mbos: entered_by % does not match the provenance human_actor %', NEW.entered_by, pv.human_actor
            USING ERRCODE = 'MB002';
    END IF;
    IF EXISTS (SELECT 1 FROM mbos.operator_notes WHERE provenance_id = NEW.provenance_id) THEN
        RAISE EXCEPTION 'mbos: provenance % already backs another note', NEW.provenance_id USING ERRCODE = 'MB002';
    END IF;
    IF NEW.supersedes IS NOT NULL THEN
        SELECT * INTO prior FROM mbos.operator_notes WHERE note_id = NEW.supersedes;
        IF prior.retracted THEN
            RAISE EXCEPTION 'mbos: % is retracted; enter a new note instead of editing it', NEW.supersedes USING ERRCODE = 'MB004';
        END IF;
        IF NEW.entered_at < prior.entered_at THEN
            RAISE EXCEPTION 'mbos: an edit cannot predate the note it supersedes' USING ERRCODE = 'MB004';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER aa_operator_notes_before_insert BEFORE INSERT ON mbos.operator_notes
    FOR EACH ROW EXECUTE FUNCTION mbos.operator_notes_before_insert();

-- No note without its receipt, in this transaction, citing the same human provenance.
CREATE FUNCTION mbos.operator_notes_require_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM mbos.receipts r
                   WHERE r.tx_id = pg_current_xact_id() AND r.type = 'LESSON_RECORDED'
                     AND r.entity_type = 'operator_note' AND r.entity_id = NEW.note_id
                     AND NEW.provenance_id = ANY (r.provenance_ids)) THEN
        RAISE EXCEPTION 'mbos: operator note % has no LESSON_RECORDED/operator_note receipt in this transaction citing %',
            NEW.note_id, NEW.provenance_id USING ERRCODE = 'MB003';
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER zz_operator_notes_receipt AFTER INSERT ON mbos.operator_notes
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mbos.operator_notes_require_receipt();

-- ---------------------------------------------------------------------------
-- Entry. The bundle is exactly what mbos_economics.new_manual_note() returns: {"note": {...}, "provenance": {...}}.
-- Provenance first, then the note, then the receipt, all in the caller's transaction. Replay-safe on note_id.
-- An edit is the same call with note.supersedes = the current head.
-- ---------------------------------------------------------------------------
CREATE FUNCTION mbos.record_operator_note(p_bundle jsonb) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE n jsonb := p_bundle -> 'note'; pv jsonb := p_bundle -> 'provenance'; rec mbos.operator_notes; ex mbos.operator_notes;
BEGIN
    IF jsonb_typeof(n) <> 'object' OR jsonb_typeof(pv) <> 'object' THEN
        RAISE EXCEPTION 'mbos: bundle needs "note" and "provenance" objects' USING ERRCODE = 'MB004';
    END IF;
    IF n ? 'retracted' AND (n -> 'retracted') <> 'false'::jsonb THEN
        RAISE EXCEPTION 'mbos: use mbos.retract_operator_note to retract' USING ERRCODE = 'MB004';
    END IF;
    IF n ? 'basis' AND n->>'basis' IS DISTINCT FROM 'RECOMMENDATION' THEN        -- refuse, never silently rewrite
        RAISE EXCEPTION 'mbos: a manual note is owner-stated: basis is always RECOMMENDATION, never %', n->>'basis'
            USING ERRCODE = '23514';
    END IF;
    IF n->>'provenance_id' IS DISTINCT FROM pv->>'provenance_id' THEN
        RAISE EXCEPTION 'mbos: note.provenance_id must be the bundle''s provenance record' USING ERRCODE = 'MB002';
    END IF;
    SELECT * INTO ex FROM mbos.operator_notes WHERE note_id = n->>'note_id';
    IF FOUND THEN
        IF ex.provenance_id = n->>'provenance_id' THEN RETURN ex.note_id; END IF;      -- replay
        RAISE EXCEPTION 'mbos: note % already exists with different provenance', ex.note_id USING ERRCODE = 'MB409';
    END IF;
    PERFORM mbos.record_provenance(pv);
    rec := jsonb_populate_record(NULL::mbos.operator_notes, n);
    INSERT INTO mbos.operator_notes (note_id, category, match, kind, statement, plan_hint, entered_by, entered_at,
                                     basis_of_knowledge, provenance_id, reference_url, review_after, supersedes)
    VALUES (rec.note_id, rec.category, rec.match, rec.kind, rec.statement, rec.plan_hint, rec.entered_by, rec.entered_at,
            rec.basis_of_knowledge, rec.provenance_id, rec.reference_url, rec.review_after, rec.supersedes);
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', 'LESSON_RECORDED', 'actor', jsonb_build_object('type', 'human', 'id', rec.entered_by),
        'intent', format('operator note %s: %s (%s)', CASE WHEN rec.supersedes IS NULL THEN 'recorded' ELSE 'edited' END,
                         rec.kind, rec.category),
        'entity_type', 'operator_note', 'entity_id', rec.note_id, 'effect', 'create',
        'idempotency_key', 'operator_note:' || rec.note_id, 'provenance_ids', jsonb_build_array(rec.provenance_id),
        'after_state', jsonb_strip_nulls(jsonb_build_object('category', rec.category, 'kind', rec.kind,
                                                            'supersedes', rec.supersedes, 'retracted', false)),
        'details', jsonb_build_object('kind', 'generic')));
    RETURN rec.note_id;
END $$;

-- Current head of the chain containing p_note_id (follow `supersedes` forward). NULL if the note does not exist.
CREATE FUNCTION mbos.operator_note_head(p_note_id text) RETURNS text
LANGUAGE sql STABLE AS $$
    WITH RECURSIVE walk(note_id, depth) AS (
        SELECT note_id, 0 FROM mbos.operator_notes WHERE note_id = p_note_id
        UNION ALL
        SELECT n.note_id, w.depth + 1 FROM walk w JOIN mbos.operator_notes n ON n.supersedes = w.note_id
    )
    SELECT note_id FROM walk ORDER BY depth DESC LIMIT 1
$$;

-- Retract: a new row that copies the CURRENT head's content with retracted = true, so the folded document stays valid.
-- Needs its own human provenance (inserted first) and its own receipt, like any note.
CREATE FUNCTION mbos.retract_operator_note(p_note_id text, p_entered_by text, p_entered_at timestamptz,
                                           p_reason text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE head mbos.operator_notes; nid text; pid text;
BEGIN
    IF coalesce(btrim(p_reason), '') = '' THEN
        RAISE EXCEPTION 'mbos: a retraction needs a reason' USING ERRCODE = 'MB004';
    END IF;
    SELECT * INTO head FROM mbos.operator_notes WHERE note_id = mbos.operator_note_head(p_note_id);
    IF NOT FOUND THEN RAISE EXCEPTION 'mbos: note % not found', p_note_id USING ERRCODE = 'MB404'; END IF;
    IF head.retracted THEN RETURN head.note_id; END IF;                       -- already retracted: replay-safe
    nid := mbos.new_id('mn');
    pid := mbos.record_provenance(jsonb_build_object(
        'actor_type', 'human', 'human_actor', p_entered_by, 'basis', 'RECOMMENDATION',
        'tool_name', 'mbos.manual_note', 'tool_version', '1',
        'created_at', mbos.utc_iso(p_entered_at), 'inputs_used', jsonb_build_array(jsonb_build_object('ref', head.note_id))));
    INSERT INTO mbos.operator_notes (note_id, category, match, kind, statement, plan_hint, entered_by, entered_at,
                                     basis_of_knowledge, provenance_id, reference_url, review_after, supersedes, retracted)
    VALUES (nid, head.category, head.match, head.kind, head.statement, head.plan_hint, p_entered_by, p_entered_at,
            'retracted: ' || btrim(p_reason), pid, head.reference_url, head.review_after, head.note_id, true);
    PERFORM mbos.append_receipt(jsonb_build_object(
        'type', 'LESSON_RECORDED', 'actor', jsonb_build_object('type', 'human', 'id', p_entered_by),
        'intent', format('operator note retracted: %s', btrim(p_reason)),
        'entity_type', 'operator_note', 'entity_id', nid, 'effect', 'update',
        'idempotency_key', 'operator_note:' || nid, 'provenance_ids', jsonb_build_array(pid),
        'before_state', jsonb_build_object('note_id', head.note_id, 'retracted', false),
        'after_state', jsonb_build_object('category', head.category, 'kind', head.kind, 'supersedes', head.note_id,
                                          'retracted', true),
        'details', jsonb_build_object('kind', 'generic')));
    RETURN nid;
END $$;

-- Folded reader: the latest row of each supersedes chain wins; a retraction head renders retracted = true.
CREATE VIEW mbos.v_operator_notes_current AS
    SELECT n.*,
           (SELECT count(*) FROM mbos.operator_notes o
            WHERE o.note_id <> n.note_id
              AND mbos.operator_note_head(o.note_id) = n.note_id) AS revisions
    FROM mbos.operator_notes n
    WHERE NOT EXISTS (SELECT 1 FROM mbos.operator_notes s WHERE s.supersedes = n.note_id);

-- The flat document Agent 03's valueadd.load_manual_notes() reads: {"notes_format": 1, "notes": [...]}.
-- Pass include_retracted = false to leave retracted notes out entirely (the loader skips them either way).
CREATE FUNCTION mbos.operator_notes_document(p_include_retracted boolean DEFAULT true) RETURNS jsonb
LANGUAGE sql STABLE AS $$
    SELECT jsonb_build_object('notes_format', 1, 'notes', coalesce(jsonb_agg(d ORDER BY entered_at, note_id), '[]'::jsonb))
    FROM (
        SELECT c.entered_at, c.note_id, mbos.jsonb_strip_top_nulls(jsonb_build_object(
            'note_id', c.note_id, 'category', c.category, 'match', c.match, 'kind', c.kind, 'statement', c.statement,
            'plan_hint', c.plan_hint, 'entered_by', c.entered_by, 'entered_at', mbos.utc_iso(c.entered_at),
            'basis_of_knowledge', c.basis_of_knowledge, 'provenance_id', c.provenance_id,
            'reference_url', c.reference_url, 'review_after', c.review_after::text, 'basis', c.basis,
            'retracted', CASE WHEN c.retracted THEN true END)) AS d
        FROM mbos.v_operator_notes_current c
        WHERE p_include_retracted OR NOT c.retracted
    ) x
$$;

-- Roles: the human channel (Operator UI = approver) inserts; everyone else reads.
REVOKE ALL ON mbos.operator_notes, mbos.v_operator_notes_current FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION mbos.nonempty_text_array(jsonb), mbos.valid_note_match(jsonb),
    mbos.operator_notes_before_insert(), mbos.operator_notes_require_receipt(), mbos.record_operator_note(jsonb),
    mbos.operator_note_head(text), mbos.retract_operator_note(text, text, timestamptz, text),
    mbos.operator_notes_document(boolean) FROM PUBLIC;
GRANT SELECT ON mbos.operator_notes, mbos.v_operator_notes_current
    TO agent_read, agent_write, gateway, approver, policy_admin;
GRANT EXECUTE ON FUNCTION mbos.nonempty_text_array(jsonb), mbos.valid_note_match(jsonb), mbos.operator_note_head(text),
    mbos.operator_notes_document(boolean) TO agent_read, agent_write, gateway, approver, policy_admin;
GRANT INSERT ON mbos.operator_notes TO approver;
GRANT EXECUTE ON FUNCTION mbos.operator_notes_before_insert(), mbos.operator_notes_require_receipt(),
    mbos.record_operator_note(jsonb), mbos.retract_operator_note(text, text, timestamptz, text) TO approver;
