#pragma once

#include <string>

static const int kProtocolMaxBytes = 4096;
static const int kProtocolVersion = 1;

struct ProtocolMessage {
    bool ok = false;
    std::string error;
    int version = 0;
    std::string session;
    int seq = 0;
    std::string type;
    std::string stage;
    bool slow = false;
    std::string reason;
    int screen[4] = {0, 0, 0, 0};
    bool has_screen = false;
};

ProtocolMessage parse_protocol_line(const std::string& line);
std::string format_protocol_line(
    const std::string& session,
    int seq,
    const std::string& type,
    const std::string& stage,
    bool slow,
    const std::string& reason);
