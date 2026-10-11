#include "protocol.h"

#include "json_value.h"

#include <climits>
#include <cmath>
#include <sstream>

namespace {

bool known_type(const std::string& type) {
    return type == "stage" || type == "finish" || type == "presented" ||
           type == "hidden" || type == "diagnostic";
}

bool finite_int(double value, int& out) {
    if (!std::isfinite(value)) {
        return false;
    }
    if (value < static_cast<double>(INT_MIN) || value > static_cast<double>(INT_MAX)) {
        return false;
    }
    out = static_cast<int>(value);
    return true;
}

std::string escape_json(const std::string& text) {
    std::string out;
    out.reserve(text.size() + 2);
    out.push_back('"');
    for (unsigned char ch : text) {
        if (ch == '"' || ch == '\\') {
            out.push_back('\\');
            out.push_back(static_cast<char>(ch));
        } else if (ch == '\n') {
            out += "\\n";
        } else if (ch < 0x20) {
            out += " ";
        } else {
            out.push_back(static_cast<char>(ch));
        }
    }
    out.push_back('"');
    return out;
}

}  // namespace

ProtocolMessage parse_protocol_line(const std::string& line) {
    ProtocolMessage message;
    if (line.size() > static_cast<size_t>(kProtocolMaxBytes)) {
        message.error = "frame exceeds limit";
        return message;
    }
    if (line.find('{') == std::string::npos) {
        message.error = "not json";
        return message;
    }
    JsonParse parsed = parse_json(line);
    if (!parsed.ok || parsed.value.type != Json::Object) {
        message.error = parsed.ok ? "frame must be an object" : parsed.error;
        return message;
    }
    const Json* version = parsed.value.find("v");
    const Json* session = parsed.value.find("session");
    const Json* seq = parsed.value.find("seq");
    const Json* type = parsed.value.find("type");
    if (version == nullptr || version->type != Json::Number ||
        session == nullptr || session->type != Json::String || session->text.empty() ||
        seq == nullptr || seq->type != Json::Number ||
        type == nullptr || type->type != Json::String) {
        message.error = "missing protocol fields";
        return message;
    }
    if (!finite_int(version->number, message.version)) {
        message.error = "protocol number out of range";
        return message;
    }
    if (message.version != kProtocolVersion) {
        message.error = "unsupported protocol version";
        return message;
    }
    if (!known_type(type->text)) {
        message.error = "unknown message type";
        return message;
    }
    message.session = session->text;
    if (!finite_int(seq->number, message.seq)) {
        message.error = "protocol number out of range";
        return message;
    }
    message.type = type->text;
    if (const Json* stage = parsed.value.find("stage")) {
        if (stage->type == Json::String) {
            message.stage = stage->text;
        }
    }
    if (const Json* slow = parsed.value.find("slow")) {
        if (slow->type == Json::Bool) {
            message.slow = slow->boolean;
        }
    }
    if (const Json* reason = parsed.value.find("reason")) {
        if (reason->type == Json::String) {
            message.reason = reason->text;
        }
    }
    if (const Json* screen = parsed.value.find("screen")) {
        if (screen->type == Json::Array && screen->array.size() == 4) {
            bool numbers = true;
            for (int i = 0; i < 4; ++i) {
                if (screen->array[static_cast<size_t>(i)].type != Json::Number) {
                    numbers = false;
                    break;
                }
                int coord = 0;
                if (!finite_int(screen->array[static_cast<size_t>(i)].number, coord)) {
                    numbers = false;
                    break;
                }
                message.screen[i] = coord;
            }
            message.has_screen = numbers;
        }
    }
    if (message.type == "stage" && message.stage.empty()) {
        message.error = "stage message needs a stage";
        return message;
    }
    message.ok = true;
    return message;
}

bool protocol_buffer_append(std::string& buffer, const char* data, size_t size) {
    if (size == 0) {
        return buffer.size() <= static_cast<size_t>(kProtocolBufferCap);
    }
    if (data == nullptr || size > static_cast<size_t>(kProtocolBufferCap) ||
        buffer.size() > static_cast<size_t>(kProtocolBufferCap) - size) {
        return false;
    }
    buffer.append(data, size);
    return true;
}

std::string format_protocol_line(
    const std::string& session,
    int seq,
    const std::string& type,
    const std::string& stage,
    bool slow,
    const std::string& reason) {
    std::ostringstream out;
    out << "{\"v\":" << kProtocolVersion
        << ",\"session\":" << escape_json(session)
        << ",\"seq\":" << seq
        << ",\"type\":" << escape_json(type);
    if (!stage.empty()) {
        out << ",\"stage\":" << escape_json(stage);
    }
    if (type == "stage") {
        out << ",\"slow\":" << (slow ? "true" : "false");
    }
    if (!reason.empty()) {
        out << ",\"reason\":" << escape_json(reason);
    }
    out << "}";
    return out.str();
}
