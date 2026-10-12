-- 0032_site_feed_access_mode.sql — READY_QUEUE D-38: add access_mode 'site_feed' to mbos.source_registry.
--   site_feed = the publisher's own pages, robots/crawl-delay respected, auction EVENTS only, no lots. DRY-RUN.
ALTER TABLE mbos.source_registry DROP CONSTRAINT source_registry_access_mode_check;
ALTER TABLE mbos.source_registry ADD CONSTRAINT source_registry_access_mode_check
    CHECK (access_mode IN ('api', 'alert_email', 'manual', 'excluded', 'site_feed'));
