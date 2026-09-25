#include "launch_dispatch.h"

namespace {

std::string env_get(const std::map<std::string, std::string>& env, const std::string& key) {
    auto found = env.find(key);
    if (found == env.end()) {
        return "";
    }
    const std::string& raw = found->second;
    size_t begin = 0;
    size_t end = raw.size();
    while (begin < end && (raw[begin] == ' ' || raw[begin] == '\t')) {
        ++begin;
    }
    while (end > begin && (raw[end - 1] == ' ' || raw[end - 1] == '\t')) {
        --end;
    }
    return raw.substr(begin, end - begin);
}

std::string lower_copy(std::string text) {
    for (char& ch : text) {
        if (ch >= 'A' && ch <= 'Z') {
            ch = static_cast<char>(ch - 'A' + 'a');
        }
    }
    return text;
}

bool falsey_splash(const std::string& value) {
    std::string text = lower_copy(value);
    return text == "0" || text == "false" || text == "off" || text == "no";
}

}  // namespace

bool should_present_native_panel(
    const std::vector<std::string>& argv,
    const std::map<std::string, std::string>& env) {
    if (falsey_splash(env_get(env, "TRACELAB_STARTUP_SPLASH"))) {
        return false;
    }
    std::string backend = lower_copy(env_get(env, "TRACELAB_STARTUP_BACKEND"));
    if (backend.empty()) {
        backend = "auto";
    }
    if (backend != "auto" && backend != "native") {
        return false;
    }
    if (env_get(env, "TRACELAB_LAYOUT_PROBE") == "1") {
        return false;
    }
    if (lower_copy(env_get(env, "QT_QPA_PLATFORM")) == "offscreen") {
        return false;
    }
    for (const std::string& token : argv) {
        if (!token.empty() && token[0] == '-') {
            return false;
        }
    }
    return true;
}

std::string quote_windows_argument(const std::string& arg) {
    if (arg.empty()) {
        return "\"\"";
    }
    bool needs_quotes = arg.find_first_of(" \t\n\v\"") != std::string::npos;
    if (!needs_quotes) {
        return arg;
    }
    std::string out = "\"";
    int backslashes = 0;
    for (char ch : arg) {
        if (ch == '\\') {
            ++backslashes;
            continue;
        }
        if (ch == '"') {
            out.append(static_cast<size_t>(backslashes * 2 + 1), '\\');
            out.push_back('"');
            backslashes = 0;
            continue;
        }
        if (backslashes > 0) {
            out.append(static_cast<size_t>(backslashes), '\\');
            backslashes = 0;
        }
        out.push_back(ch);
    }
    if (backslashes > 0) {
        out.append(static_cast<size_t>(backslashes * 2), '\\');
    }
    out.push_back('"');
    return out;
}
