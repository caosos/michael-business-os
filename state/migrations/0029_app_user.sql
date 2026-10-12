-- 0029_app_user.sql — READY_QUEUE D-35 / ADR-0015 P-74-1: accounts. DRY-RUN; no credentials are stored here.
--   * mbos.app_user: one row per person. role is 'owner' or 'member'. Exactly one owner (partial unique index), seeded below
--     (Conway AR 72032, AR, 150 mi, matching today's behavior). Authentication (password hash, sessions) is the UI's concern
--     (P-74-5) and lives outside this table, so no secret ever reaches Postgres rows or receipts from here.
--   * Authority does not widen: this table grants nothing. A member's database session is never a member of owner_channel,
--     approver or any effector role, so every owner-only function (D-24/25/28..31, D-33 ceiling) refuses it by role.
--   * Only owner_channel may INSERT/UPDATE rows; the owner row can never be demoted, deleted or duplicated.
CREATE TABLE mbos.app_user (
    user_id             text PRIMARY KEY DEFAULT mbos.new_id('usr') CHECK (user_id ~ '^usr_[0-9A-HJKMNP-TV-Z]{26}$'),
    handle              text NOT NULL UNIQUE CHECK (handle ~ '^[a-z0-9][a-z0-9_.-]{1,31}$'),
    display_name        text NOT NULL CHECK (btrim(display_name) <> ''),
    role                text NOT NULL CHECK (role IN ('owner', 'member')),
    home_zip            text CHECK (home_zip IS NULL OR home_zip ~ '^[0-9]{5}$'),
    home_state          text CHECK (home_state IS NULL OR home_state ~ '^[A-Z]{2}$'),
    home_lat            numeric(9,6) CHECK (home_lat IS NULL OR home_lat BETWEEN -90 AND 90),
    home_lng            numeric(9,6) CHECK (home_lng IS NULL OR home_lng BETWEEN -180 AND 180),
    default_radius_mi   integer CHECK (default_radius_mi IS NULL OR default_radius_mi BETWEEN 1 AND 3000),
    tz                  text NOT NULL DEFAULT 'America/Chicago',
    status              text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX app_user_one_owner ON mbos.app_user ((true)) WHERE role = 'owner';

CREATE FUNCTION mbos._app_user_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'mbos: app_user rows are never deleted (disable instead)' USING ERRCODE = '42501';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NEW.user_id <> OLD.user_id OR NEW.role <> OLD.role OR NEW.created_at <> OLD.created_at THEN
            RAISE EXCEPTION 'mbos: app_user id, role and created_at are immutable' USING ERRCODE = '42501';
        END IF;
        IF OLD.role = 'owner' AND NEW.status <> 'active' THEN
            RAISE EXCEPTION 'mbos: the owner row cannot be disabled' USING ERRCODE = '42501';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER app_user_guard BEFORE INSERT OR UPDATE OR DELETE ON mbos.app_user FOR EACH ROW EXECUTE FUNCTION mbos._app_user_guard();

INSERT INTO mbos.app_user (handle, display_name, role, home_zip, home_state, default_radius_mi)
VALUES ('michael', 'Michael', 'owner', '72032', 'AR', 150);

GRANT SELECT ON mbos.app_user TO agent_read, agent_write, gateway, approver, policy_admin, owner_channel;
GRANT INSERT, UPDATE ON mbos.app_user TO owner_channel;
