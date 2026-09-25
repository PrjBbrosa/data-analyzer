#pragma once

#include <string>
#include <utility>
#include <vector>

struct Json {
    enum Type { Null, Bool, Number, String, Array, Object };
    Type type = Null;
    bool boolean = false;
    double number = 0;
    std::string text;
    std::vector<Json> array;
    std::vector<std::pair<std::string, Json>> object;

    const Json* find(const std::string& key) const;
};

struct JsonParse {
    bool ok = false;
    std::string error;
    Json value;
};

JsonParse parse_json(const std::string& text);
