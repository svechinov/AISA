-- Run once against existing DB if `projects` already existed before `is_archived` was added.
ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT FALSE;
