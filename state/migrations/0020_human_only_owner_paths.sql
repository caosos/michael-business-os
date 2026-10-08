-- D-24: close the agent_write exemption in 0019's _require_human_owner.
--   set_mission, capital_fund, capital_withdraw, set_campaign and cancel_campaign now require actor.type = human with a
--   non-empty id for EVERY session, including agent_write members such as the real mbos_dbos login. No legitimate agent
--   use exists (workflows never fund capital, set missions or edit campaigns; ruling R14).
--   record_outcome is unchanged: it keeps its own 0018 rule (agent_write sessions may still record agent outcomes).

CREATE OR REPLACE FUNCTION mbos._require_human_owner(p_actor jsonb, p_what text) RETURNS void
LANGUAGE plpgsql STABLE AS $$
BEGIN
    IF p_actor->>'type' IS DISTINCT FROM 'human' OR coalesce(btrim(p_actor->>'id'), '') = '' THEN
        RAISE EXCEPTION 'mbos: role % may % only as a human (actor.type human with an id), got actor %',
            session_user, p_what, p_actor USING ERRCODE = '42501';
    END IF;
END $$;
