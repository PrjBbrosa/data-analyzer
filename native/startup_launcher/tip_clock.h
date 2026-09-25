#pragma once

// Tip rotation from the first successful present. One opening index per session.
int tip_index_for_elapsed(int initial_index, long long visible_elapsed_ms, int count, int interval_ms);

// 1 when the slow-start line should replace the stage line.
int slow_status_active(long long visible_elapsed_ms, int slow_flag, int slow_after_ms);
