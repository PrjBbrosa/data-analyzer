#pragma once

#include <map>
#include <string>
#include <vector>

// argv excludes the executable path. True only for an ordinary GUI launch.
bool should_present_native_panel(
    const std::vector<std::string>& argv,
    const std::map<std::string, std::string>& env);

// Windows command-line quoting for one argument.
std::string quote_windows_argument(const std::string& arg);
