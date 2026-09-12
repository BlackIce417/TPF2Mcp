local M = {}

-- This template is replaced by tools/install-mod.ps1 at installation time.
-- Manual installations must set an absolute Windows path with forward slashes.
M.bridge_dir = ""
M.schema_version = 1
M.snapshot_refresh_interval_seconds = 2
-- Game-script update callbacks can be much more frequent than Bridge work.
M.bridge_poll_interval_updates = 5
-- Phase 11 safety boundary: writes are off unless a dedicated test save
-- explicitly enables them in the generated installation config.
M.allow_write_operations = false
M.allowed_operations = {}

return M
