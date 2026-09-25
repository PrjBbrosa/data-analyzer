#include "session_machine.h"

#include "tip_clock.h"

SessionApply session_present(SessionState& state, int x, int y, int w, int h, long long now_ms) {
    if (state.presented || state.hidden || state.direct_runtime) {
        return SessionApply::IgnoredTerminal;
    }
    state.presented = true;
    state.present_count += 1;
    state.screen_x = x;
    state.screen_y = y;
    state.screen_w = w;
    state.screen_h = h;
    state.animation_origin_ms = now_ms;
    return SessionApply::Applied;
}

SessionApply session_stage(SessionState& state, const std::string& stage, bool slow) {
    if (state.hidden || state.finish_requested || state.direct_runtime) {
        return SessionApply::IgnoredTerminal;
    }
    state.stage = stage;
    state.slow = slow;
    return SessionApply::Applied;
}

SessionApply session_finish(SessionState& state) {
    if (state.hidden) {
        state.finish_requested = true;
        return SessionApply::AlreadyHidden;
    }
    if (state.finish_requested) {
        return SessionApply::IgnoredTerminal;
    }
    state.finish_requested = true;
    return SessionApply::Applied;
}

SessionApply session_hide(SessionState& state, const std::string& reason) {
    if (state.hidden) {
        return SessionApply::IgnoredTerminal;
    }
    state.hidden = true;
    state.hidden_reason = reason;
    return SessionApply::Applied;
}

SessionApply session_dpi(SessionState& state, int x, int y, int w, int h) {
    if (!state.presented || state.hidden) {
        return SessionApply::IgnoredTerminal;
    }
    int opening = state.opening_index;
    long long origin = state.animation_origin_ms;
    state.screen_x = x;
    state.screen_y = y;
    state.screen_w = w;
    state.screen_h = h;
    state.opening_index = opening;
    state.animation_origin_ms = origin;
    return SessionApply::Applied;
}

SessionApply session_present_failed(SessionState& state) {
    if (state.presented || state.hidden) {
        return SessionApply::IgnoredTerminal;
    }
    state.direct_runtime = true;
    return SessionApply::Applied;
}

int session_tip_index(const SessionState& state, long long visible_elapsed_ms) {
    return tip_index_for_elapsed(state.opening_index, visible_elapsed_ms, state.tip_count, 5000);
}
