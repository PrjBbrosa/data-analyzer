#include "tip_clock.h"

int tip_index_for_elapsed(int initial_index, long long visible_elapsed_ms, int count, int interval_ms) {
    if (count <= 0 || interval_ms <= 0 || initial_index < 0 || initial_index >= count) {
        return -1;
    }
    long long elapsed = visible_elapsed_ms < 0 ? 0 : visible_elapsed_ms;
    long long steps = elapsed / interval_ms;
    long long index = (static_cast<long long>(initial_index) + steps) % count;
    if (index < 0) {
        index += count;
    }
    return static_cast<int>(index);
}

int slow_status_active(long long visible_elapsed_ms, int slow_flag, int slow_after_ms) {
    if (slow_flag) {
        return 1;
    }
    long long elapsed = visible_elapsed_ms < 0 ? 0 : visible_elapsed_ms;
    return elapsed >= slow_after_ms ? 1 : 0;
}
