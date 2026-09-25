#pragma once

#include <string>

enum class SessionApply {
    Applied,
    IgnoredTerminal,
    AlreadyHidden,
};

struct SessionState {
    int opening_index = 0;
    int tip_count = 26;
    bool presented = false;
    bool hidden = false;
    bool finish_requested = false;
    bool direct_runtime = false;
    std::string stage = "preparing";
    bool slow = false;
    int screen_x = 0;
    int screen_y = 0;
    int screen_w = 0;
    int screen_h = 0;
    std::string hidden_reason;
    long long animation_origin_ms = -1;
    int present_count = 0;
};

SessionApply session_present(SessionState& state, int x, int y, int w, int h, long long now_ms);
SessionApply session_stage(SessionState& state, const std::string& stage, bool slow);
SessionApply session_finish(SessionState& state);
SessionApply session_hide(SessionState& state, const std::string& reason);
SessionApply session_dpi(SessionState& state, int x, int y, int w, int h);
SessionApply session_present_failed(SessionState& state);
int session_tip_index(const SessionState& state, long long visible_elapsed_ms);
