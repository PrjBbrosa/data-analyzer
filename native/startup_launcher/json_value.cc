#include "json_value.h"

const Json* Json::find(const std::string& key) const {
    if (type != Object) {
        return nullptr;
    }
    for (const auto& item : object) {
        if (item.first == key) {
            return &item.second;
        }
    }
    return nullptr;
}

namespace {

struct Parser {
    const std::string& text;
    size_t index = 0;
    std::string error;

    explicit Parser(const std::string& input) : text(input) {}

    bool fail(const std::string& message) {
        error = message;
        return false;
    }

    void skip() {
        while (index < text.size() && (text[index] == ' ' || text[index] == '\t' ||
                                        text[index] == '\n' || text[index] == '\r')) {
            ++index;
        }
    }

    bool parse_value(Json& out) {
        skip();
        if (index >= text.size()) {
            return fail("unexpected end");
        }
        char ch = text[index];
        if (ch == '{') {
            return parse_object(out);
        }
        if (ch == '[') {
            return parse_array(out);
        }
        if (ch == '"') {
            return parse_string(out);
        }
        if (ch == 't' || ch == 'f') {
            return parse_bool(out);
        }
        if (ch == 'n') {
            return parse_null(out);
        }
        if (ch == '-' || (ch >= '0' && ch <= '9')) {
            return parse_number(out);
        }
        return fail("invalid value");
    }

    bool parse_object(Json& out) {
        ++index;
        out.type = Json::Object;
        skip();
        if (index < text.size() && text[index] == '}') {
            ++index;
            return true;
        }
        while (index < text.size()) {
            Json key;
            if (!parse_string(key)) {
                return false;
            }
            skip();
            if (index >= text.size() || text[index] != ':') {
                return fail("expected colon");
            }
            ++index;
            Json value;
            if (!parse_value(value)) {
                return false;
            }
            out.object.emplace_back(key.text, std::move(value));
            skip();
            if (index < text.size() && text[index] == ',') {
                ++index;
                skip();
                continue;
            }
            if (index < text.size() && text[index] == '}') {
                ++index;
                return true;
            }
            return fail("expected comma or object end");
        }
        return fail("unterminated object");
    }

    bool parse_array(Json& out) {
        ++index;
        out.type = Json::Array;
        skip();
        if (index < text.size() && text[index] == ']') {
            ++index;
            return true;
        }
        while (index < text.size()) {
            Json value;
            if (!parse_value(value)) {
                return false;
            }
            out.array.push_back(std::move(value));
            skip();
            if (index < text.size() && text[index] == ',') {
                ++index;
                skip();
                continue;
            }
            if (index < text.size() && text[index] == ']') {
                ++index;
                return true;
            }
            return fail("expected comma or array end");
        }
        return fail("unterminated array");
    }

    bool parse_string(Json& out) {
        if (index >= text.size() || text[index] != '"') {
            return fail("expected string");
        }
        ++index;
        out.type = Json::String;
        out.text.clear();
        while (index < text.size()) {
            char ch = text[index++];
            if (ch == '"') {
                return true;
            }
            if (ch == '\\') {
                if (index >= text.size()) {
                    return fail("bad escape");
                }
                char esc = text[index++];
                if (esc == '"' || esc == '\\' || esc == '/') {
                    out.text.push_back(esc);
                } else if (esc == 'b') {
                    out.text.push_back('\b');
                } else if (esc == 'f') {
                    out.text.push_back('\f');
                } else if (esc == 'n') {
                    out.text.push_back('\n');
                } else if (esc == 'r') {
                    out.text.push_back('\r');
                } else if (esc == 't') {
                    out.text.push_back('\t');
                } else if (esc == 'u') {
                    if (index + 4 > text.size()) {
                        return fail("short unicode escape");
                    }
                    int code = 0;
                    for (int i = 0; i < 4; ++i) {
                        char hex = text[index++];
                        code <<= 4;
                        if (hex >= '0' && hex <= '9') {
                            code += hex - '0';
                        } else if (hex >= 'a' && hex <= 'f') {
                            code += hex - 'a' + 10;
                        } else if (hex >= 'A' && hex <= 'F') {
                            code += hex - 'A' + 10;
                        } else {
                            return fail("bad unicode escape");
                        }
                    }
                    if (code < 0x80) {
                        out.text.push_back(static_cast<char>(code));
                    } else if (code < 0x800) {
                        out.text.push_back(static_cast<char>(0xC0 | (code >> 6)));
                        out.text.push_back(static_cast<char>(0x80 | (code & 0x3F)));
                    } else {
                        out.text.push_back(static_cast<char>(0xE0 | (code >> 12)));
                        out.text.push_back(static_cast<char>(0x80 | ((code >> 6) & 0x3F)));
                        out.text.push_back(static_cast<char>(0x80 | (code & 0x3F)));
                    }
                } else {
                    return fail("unknown escape");
                }
            } else if (static_cast<unsigned char>(ch) < 0x20) {
                return fail("raw control in string");
            } else {
                out.text.push_back(ch);
            }
        }
        return fail("unterminated string");
    }

    bool consume_literal(const char* literal) {
        for (size_t i = 0; literal[i] != '\0'; ++i) {
            if (index >= text.size() || text[index] != literal[i]) {
                return false;
            }
            ++index;
        }
        return true;
    }

    bool parse_bool(Json& out) {
        out.type = Json::Bool;
        if (text[index] == 't') {
            if (!consume_literal("true")) {
                return fail("expected true");
            }
            out.boolean = true;
            return true;
        }
        if (!consume_literal("false")) {
            return fail("expected false");
        }
        out.boolean = false;
        return true;
    }

    bool parse_null(Json& out) {
        if (!consume_literal("null")) {
            return fail("expected null");
        }
        out.type = Json::Null;
        return true;
    }

    bool parse_number(Json& out) {
        size_t start = index;
        if (text[index] == '-') {
            ++index;
        }
        if (index >= text.size() || text[index] < '0' || text[index] > '9') {
            return fail("bad number");
        }
        if (text[index] == '0') {
            ++index;
        } else {
            while (index < text.size() && text[index] >= '0' && text[index] <= '9') {
                ++index;
            }
        }
        if (index < text.size() && text[index] == '.') {
            ++index;
            if (index >= text.size() || text[index] < '0' || text[index] > '9') {
                return fail("bad fraction");
            }
            while (index < text.size() && text[index] >= '0' && text[index] <= '9') {
                ++index;
            }
        }
        if (index < text.size() && (text[index] == 'e' || text[index] == 'E')) {
            ++index;
            if (index < text.size() && (text[index] == '+' || text[index] == '-')) {
                ++index;
            }
            if (index >= text.size() || text[index] < '0' || text[index] > '9') {
                return fail("bad exponent");
            }
            while (index < text.size() && text[index] >= '0' && text[index] <= '9') {
                ++index;
            }
        }
        try {
            out.number = std::stod(text.substr(start, index - start));
        } catch (...) {
            return fail("number overflow");
        }
        out.type = Json::Number;
        return true;
    }
};

}  // namespace

JsonParse parse_json(const std::string& text) {
    Parser parser(text);
    JsonParse result;
    if (!parser.parse_value(result.value)) {
        result.ok = false;
        result.error = (parser.error.empty() ? "invalid json" : parser.error) +
                       " @" + std::to_string(parser.index);
        return result;
    }
    parser.skip();
    if (parser.index != text.size()) {
        result.ok = false;
        result.error = "trailing data";
        return result;
    }
    result.ok = true;
    return result;
}
