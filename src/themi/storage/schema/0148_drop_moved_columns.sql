-- CR7c: the columns whose values moved to member_preferences (0145, 0146) and
-- household_settings (0147) go. Nothing reads them since those migrations.
ALTER TABLE members DROP COLUMN sprint_work_minutes;
ALTER TABLE members DROP COLUMN sprint_break_minutes;
ALTER TABLE members DROP COLUMN body_double_sound;
ALTER TABLE members DROP COLUMN body_double_volume;
ALTER TABLE members DROP COLUMN break_extend_minutes;
ALTER TABLE members DROP COLUMN chart_limit;
ALTER TABLE members DROP COLUMN chart_counts_shared;
ALTER TABLE members DROP COLUMN focus_count;
ALTER TABLE members DROP COLUMN day_budget;
ALTER TABLE members DROP COLUMN done_praise;
ALTER TABLE members DROP COLUMN checkin_reviews;
ALTER TABLE members DROP COLUMN calendar_details;
ALTER TABLE members DROP COLUMN calendar_twins;
ALTER TABLE members DROP COLUMN setup_note;
ALTER TABLE members DROP COLUMN morning_summary;
ALTER TABLE members DROP COLUMN morning_summary_empty;
ALTER TABLE members DROP COLUMN getting_ready_minutes;
ALTER TABLE members DROP COLUMN leave_heads_up;
ALTER TABLE members DROP COLUMN noise_emails;
ALTER TABLE members DROP COLUMN conversation_mode;
ALTER TABLE members DROP COLUMN list_style;
ALTER TABLE family DROP COLUMN takeout_budget_cents;
ALTER TABLE family DROP COLUMN staples;
ALTER TABLE family DROP COLUMN laundry_fresh_hours;
ALTER TABLE family DROP COLUMN laundry_rinse_minutes;
