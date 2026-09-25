#include "json_value.h"
#include "launch_dispatch.h"
#include "protocol.h"
#include "session_machine.h"
#include "tip_clock.h"

#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

namespace {

int g_failures = 0;

void expect(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << "FAIL " << message << "\n";
        ++g_failures;
    }
}

void check_protocol_and_session() {
    std::string stage = format_protocol_line("sess", 1, "stage", "loading_components", false, "");
    ProtocolMessage parsed = parse_protocol_line(stage);
    expect(parsed.ok, "stage frame");
    expect(parsed.stage == "loading_components", "stage name");
    expect(!parsed.slow, "stage not slow");

    std::string huge(kProtocolMaxBytes + 1, 'x');
    expect(!parse_protocol_line(huge).ok, "oversize frame");
    expect(!parse_protocol_line("stage loading_components").ok, "substring is not a frame");
    expect(!parse_protocol_line("{\"v\":1,\"session\":\"s\",\"seq\":1,\"type\":\"nope\"}").ok,
           "unknown type");

    JsonParse escaped = parse_json("{\"text\":\"a\\\\b\\\"c\\u4e2d\"}");
    expect(escaped.ok, "escaped json");
    expect(escaped.value.find("text") != nullptr && escaped.value.find("text")->text == "a\\b\"c中",
           "escape decode");

    SessionState state;
    state.opening_index = 4;
    state.tip_count = 26;
    expect(session_present(state, 10, 20, 800, 600, 1000) == SessionApply::Applied, "present");
    expect(state.animation_origin_ms == 1000, "origin frozen");
    expect(session_present(state, 1, 1, 1, 1, 9999) == SessionApply::IgnoredTerminal, "second present");
    expect(state.screen_x == 10 && state.animation_origin_ms == 1000, "present not reset");
    expect(session_stage(state, "preparing_workspace", false) == SessionApply::Applied, "stage");
    expect(state.opening_index == 4, "stage keeps tip");
    expect(session_dpi(state, 30, 40, 900, 700) == SessionApply::Applied, "dpi");
    expect(state.opening_index == 4 && state.animation_origin_ms == 1000, "dpi keeps clocks");
    expect(state.screen_w == 900, "dpi updates screen");
    expect(session_tip_index(state, 4999) == 4, "tip before interval");
    expect(session_tip_index(state, 5000) == 5, "tip at interval");
    expect(session_finish(state) == SessionApply::Applied, "finish");
    expect(session_stage(state, "preparing", false) == SessionApply::IgnoredTerminal, "stage after finish");
    expect(session_hide(state, "finish_close") == SessionApply::Applied, "hide");
    expect(session_finish(state) == SessionApply::AlreadyHidden, "finish after hide");
    expect(state.hidden_reason == "finish_close", "reason kept");
    expect(session_hide(state, "user_close") == SessionApply::IgnoredTerminal, "no revive");
    expect(state.hidden_reason == "finish_close", "reason not replaced");

    SessionState early;
    expect(session_hide(early, "user_close") == SessionApply::Applied, "user hide");
    expect(session_finish(early) == SessionApply::AlreadyHidden, "finish sees user hide");
    expect(early.present_count == 0, "user hide did not present again");

    SessionState failed;
    expect(session_present_failed(failed) == SessionApply::Applied, "present failed");
    expect(session_present(failed, 0, 0, 1, 1, 0) == SessionApply::IgnoredTerminal,
           "no panel after present failure");

    expect(quote_windows_argument("plain") == "plain", "plain quote");
    expect(quote_windows_argument("a b") == "\"a b\"", "space quote");
    std::string quoted = quote_windows_argument("a\\b\"c");
    expect(quoted == "\"a\\b\\\"c\"", "quote escapes got [" + quoted + "]");
    expect(quote_windows_argument("trail\\") == "trail\\", "unquoted trailing slash");
    expect(quote_windows_argument("a b\\") == "\"a b\\\\\"", "quoted trailing slash");
}

void check_fixture(const std::string& path) {
    std::ifstream input(path);
    std::stringstream buffer;
    buffer << input.rdbuf();
    JsonParse parsed = parse_json(buffer.str());
    expect(parsed.ok, std::string("fixture json ") + parsed.error);
    if (!parsed.ok) {
        return;
    }
    const Json* tips = parsed.value.find("tips");
    const Json* panels = parsed.value.find("panels");
    expect(tips != nullptr && tips->type == Json::Array, "tips array");
    expect(panels != nullptr && panels->type == Json::Array, "panels array");
    if (tips != nullptr) {
        for (const Json& row : tips->array) {
            int initial = static_cast<int>(row.find("initial")->number);
            long long elapsed = static_cast<long long>(row.find("elapsed")->number);
            int expect_index = static_cast<int>(row.find("expect")->number);
            int actual = tip_index_for_elapsed(initial, elapsed, 26, 5000);
            expect(actual == expect_index, "tip fixture");
        }
    }
    if (panels != nullptr) {
        for (const Json& row : panels->array) {
            std::vector<std::string> argv;
            for (const Json& arg : row.find("argv")->array) {
                argv.push_back(arg.text);
            }
            std::map<std::string, std::string> env;
            const Json* env_object = row.find("env");
            if (env_object != nullptr) {
                for (const auto& item : env_object->object) {
                    env[item.first] = item.second.text;
                }
            }
            bool expect_panel = row.find("expect")->boolean;
            bool actual = should_present_native_panel(argv, env);
            expect(actual == expect_panel, "panel fixture");
        }
    }
}

}  // namespace

int main(int argc, char** argv) {
    check_protocol_and_session();
    if (argc > 1) {
        check_fixture(argv[1]);
    } else {
        expect(false, "fixture path");
    }
    if (g_failures != 0) {
        std::cerr << g_failures << " failure(s)\n";
        return 1;
    }
    std::cout << "ok\n";
    return 0;
}
