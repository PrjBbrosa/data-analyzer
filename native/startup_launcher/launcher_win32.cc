// Windows public launcher. Compiled only by tools/build_startup_launcher.ps1.
#include "launch_dispatch.h"
#include "protocol.h"
#include "session_machine.h"
#include "startup_resources.h"
#include "tip_clock.h"

#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <windowsx.h>
#include <objidl.h>
#include <gdiplus.h>
#include <shellapi.h>

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>

#pragma comment(lib, "gdiplus.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "gdi32.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "ole32.lib")

namespace {

constexpr UINT WM_APP_STAGE = WM_APP + 1;
constexpr UINT WM_APP_FINISH = WM_APP + 2;
constexpr UINT WM_APP_EXIT = WM_APP + 3;
constexpr UINT WM_APP_PIPE = WM_APP + 4;
constexpr UINT_PTR kFrameTimer = 1;

struct LaunchState {
    HWND hwnd = nullptr;
    SessionState session;
    ULONGLONG present_tick = 0;
    bool reduced_motion = false;
    bool runtime_started = false;
    bool panel_live = false;
    int exit_code = 0;
    bool exit_known = false;
    HANDLE parent_read = nullptr;
    HANDLE parent_write = nullptr;
    HANDLE child_read = nullptr;
    HANDLE child_write = nullptr;
    HANDLE process = nullptr;
    std::mutex outbound_mu;
    std::vector<std::string> outbound;
    std::wstring runtime_path;
    std::wstring command_line;
    int argc = 0;
    wchar_t** argv = nullptr;
    std::string session_id;
    int dpi = 96;
    double product_scale = 1.0;
    int screen_x = 0;
    int screen_y = 0;
    int screen_w = 0;
    int screen_h = 0;
    bool second_frame_sent = false;
    std::string pending_stage;
    bool pending_slow = false;
    bool pending_stage_valid = false;
    bool probe_enabled = false;
    std::string probe_host;
    std::string probe_port;
    std::string run_id;
};

LaunchState* g_state = nullptr;

std::wstring utf8_to_wide(const std::string& text) {
    if (text.empty()) {
        return L"";
    }
    int size = MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0);
    std::wstring out(static_cast<size_t>(size), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), out.data(), size);
    return out;
}

std::string wide_to_utf8(const std::wstring& text) {
    if (text.empty()) {
        return "";
    }
    int size = WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
    std::string out(static_cast<size_t>(size), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), out.data(), size, nullptr, nullptr);
    return out;
}

std::map<std::string, std::string> current_env() {
    std::map<std::string, std::string> env;
    wchar_t* block = GetEnvironmentStringsW();
    if (block == nullptr) {
        return env;
    }
    for (wchar_t* cursor = block; *cursor != L'\0';) {
        std::wstring line = cursor;
        cursor += line.size() + 1;
        if (line.empty() || line[0] == L'=') {
            continue;
        }
        size_t split = line.find(L'=');
        if (split == std::wstring::npos) {
            continue;
        }
        env[wide_to_utf8(line.substr(0, split))] = wide_to_utf8(line.substr(split + 1));
    }
    FreeEnvironmentStringsW(block);
    return env;
}

std::wstring quote_wide(const std::wstring& arg) {
    return utf8_to_wide(quote_windows_argument(wide_to_utf8(arg)));
}

std::wstring runtime_path_from_module() {
    wchar_t path[MAX_PATH];
    DWORD length = GetModuleFileNameW(nullptr, path, MAX_PATH);
    std::wstring full(path, length);
    size_t slash = full.find_last_of(L"\\/");
    std::wstring dir = slash == std::wstring::npos ? L"" : full.substr(0, slash + 1);
    std::wstring file = slash == std::wstring::npos ? full : full.substr(slash + 1);
    std::wstring stem = file;
    if (stem.size() >= 4) {
        std::wstring ext = stem.substr(stem.size() - 4);
        if (ext == L".exe" || ext == L".EXE") {
            stem = stem.substr(0, stem.size() - 4);
        }
    }
    return dir + stem + L"-runtime.exe";
}

std::wstring build_command_line(const std::wstring& runtime, int argc, wchar_t** argv) {
    std::wstring line = quote_wide(runtime);
    for (int i = 1; i < argc; ++i) {
        line += L" ";
        line += quote_wide(argv[i]);
    }
    return line;
}

std::string make_session_id() {
    unsigned int bytes[4] = {};
    for (unsigned int& word : bytes) {
        rand_s(&word);
    }
    static const char* hex = "0123456789abcdef";
    std::string out;
    out.resize(32);
    for (int i = 0; i < 4; ++i) {
        unsigned int word = bytes[i];
        for (int nibble = 7; nibble >= 0; --nibble) {
            out[static_cast<size_t>(i * 8 + (7 - nibble))] = hex[(word >> (nibble * 4)) & 0xF];
        }
    }
    return out;
}

void queue_outbound(LaunchState& state, const std::string& line) {
    std::lock_guard<std::mutex> lock(state.outbound_mu);
    state.outbound.push_back(line);
}

bool reduced_motion_enabled() {
    BOOL enabled = TRUE;
    if (SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, &enabled, 0)) {
        return enabled == FALSE;
    }
    return false;
}

double product_scale_for(int logical_w, int logical_h) {
    double max_w = logical_w - kStartupWorkAreaMargin;
    double max_h = logical_h - kStartupWorkAreaMargin;
    if (max_w < 160) {
        max_w = 160;
    }
    if (max_h < 160) {
        max_h = 160;
    }
    if (logical_h >= kStartupLargeMinHeight &&
        kStartupCardWidth * 1.5 <= max_w &&
        kStartupCardHeight * 1.5 <= max_h) {
        return 1.5;
    }
    if (kStartupCardWidth <= max_w && kStartupCardHeight <= max_h) {
        return 1.0;
    }
    double fit = max_w / kStartupCardWidth;
    double fit_h = max_h / kStartupCardHeight;
    if (fit_h < fit) {
        fit = fit_h;
    }
    return fit;
}

void choose_screen(LaunchState& state) {
    POINT cursor{};
    GetCursorPos(&cursor);
    HMONITOR monitor = MonitorFromPoint(cursor, MONITOR_DEFAULTTONEAREST);
    MONITORINFO info{};
    info.cbSize = sizeof(info);
    GetMonitorInfoW(monitor, &info);
    UINT dpi_x = 96;
    UINT dpi_y = 96;
    HMODULE shcore = LoadLibraryW(L"shcore.dll");
    if (shcore != nullptr) {
        using GetDpiForMonitorFn = HRESULT(WINAPI*)(HMONITOR, int, UINT*, UINT*);
        auto get_dpi = reinterpret_cast<GetDpiForMonitorFn>(GetProcAddress(shcore, "GetDpiForMonitor"));
        if (get_dpi != nullptr) {
            get_dpi(monitor, 0, &dpi_x, &dpi_y);
        }
        FreeLibrary(shcore);
    }
    state.dpi = static_cast<int>(dpi_x == 0 ? 96 : dpi_x);
    int physical_w = info.rcWork.right - info.rcWork.left;
    int physical_h = info.rcWork.bottom - info.rcWork.top;
    int logical_w = MulDiv(physical_w, 96, state.dpi);
    int logical_h = MulDiv(physical_h, 96, state.dpi);
    state.product_scale = product_scale_for(logical_w, logical_h);
    state.screen_x = info.rcWork.left;
    state.screen_y = info.rcWork.top;
    state.screen_w = physical_w;
    state.screen_h = physical_h;
}

int window_pixel_width(const LaunchState& state) {
    int logical = static_cast<int>(kStartupCardWidth * state.product_scale + 0.5);
    return MulDiv(logical, state.dpi, 96);
}

int window_pixel_height(const LaunchState& state) {
    int logical = static_cast<int>(kStartupCardHeight * state.product_scale + 0.5);
    return MulDiv(logical, state.dpi, 96);
}

const char* stage_label(const SessionState& session, long long elapsed) {
    if (slow_status_active(elapsed, session.slow ? 1 : 0, kStartupSlowAfterMs)) {
        return kStartupSlowStatus;
    }
    for (int i = 0; i < 3; ++i) {
        if (session.stage == kStartupStageIds[i]) {
            return kStartupStageLabels[i];
        }
    }
    return kStartupStageLabels[0];
}

void send_probe(const LaunchState& state, const char* event_name) {
    if (!state.probe_enabled) {
        return;
    }
    SOCKET sock = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (sock == INVALID_SOCKET) {
        return;
    }
    sockaddr_in address{};
    address.sin_family = AF_INET;
    char* port_end = nullptr;
    long port = std::strtol(state.probe_port.c_str(), &port_end, 10);
    if (port <= 0 || port > 65535) {
        closesocket(sock);
        return;
    }
    address.sin_port = htons(static_cast<u_short>(port));
    inet_pton(AF_INET, state.probe_host.c_str(), &address.sin_addr);
    if (connect(sock, reinterpret_cast<sockaddr*>(&address), sizeof(address)) != 0) {
        closesocket(sock);
        return;
    }
    std::ostringstream body;
    body << "{\"role\":\"feedback\",\"event\":\"" << event_name
         << "\",\"run_id\":\"" << state.run_id
         << "\",\"session\":\"" << state.session_id << "\"}\n";
    std::string payload = body.str();
    send(sock, payload.data(), static_cast<int>(payload.size()), 0);
    closesocket(sock);
}

void paint_panel(LaunchState& state) {
    if (state.hwnd == nullptr) {
        return;
    }
    int width = window_pixel_width(state);
    int height = window_pixel_height(state);
    if (width < 1 || height < 1) {
        return;
    }
    HDC screen = GetDC(nullptr);
    HDC memory = CreateCompatibleDC(screen);
    BITMAPINFO info{};
    info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    info.bmiHeader.biWidth = width;
    info.bmiHeader.biHeight = -height;
    info.bmiHeader.biPlanes = 1;
    info.bmiHeader.biBitCount = 32;
    info.bmiHeader.biCompression = BI_RGB;
    void* bits = nullptr;
    HBITMAP bitmap = CreateDIBSection(screen, &info, DIB_RGB_COLORS, &bits, nullptr, 0);
    HGDIOBJ previous = SelectObject(memory, bitmap);
    Gdiplus::Graphics graphics(memory);
    graphics.SetSmoothingMode(Gdiplus::SmoothingModeAntiAlias);
    graphics.SetTextRenderingHint(Gdiplus::TextRenderingHintAntiAlias);
    graphics.Clear(Gdiplus::Color(0, 0, 0, 0));
    float radius = static_cast<float>(13.0 * state.product_scale * state.dpi / 96.0);
    Gdiplus::GraphicsPath card;
    Gdiplus::RectF bounds(0, 0, static_cast<float>(width), static_cast<float>(height));
    card.AddArc(bounds.X, bounds.Y, radius * 2, radius * 2, 180, 90);
    card.AddArc(bounds.GetRight() - radius * 2, bounds.Y, radius * 2, radius * 2, 270, 90);
    card.AddArc(bounds.GetRight() - radius * 2, bounds.GetBottom() - radius * 2, radius * 2, radius * 2, 0, 90);
    card.AddArc(bounds.X, bounds.GetBottom() - radius * 2, radius * 2, radius * 2, 90, 90);
    card.CloseFigure();
    Gdiplus::LinearGradientBrush fill(
        bounds,
        Gdiplus::Color(255, 255, 255, 255),
        Gdiplus::Color(255, 244, 250, 255),
        Gdiplus::LinearGradientModeForwardDiagonal);
    graphics.FillPath(&fill, &card);

    std::wstring family_name = L"Segoe UI";
    for (const char* const* name = kStartupFontCandidates; *name != nullptr; ++name) {
        std::wstring wide_name = utf8_to_wide(*name);
        Gdiplus::FontFamily candidate(wide_name.c_str());
        if (candidate.IsAvailable()) {
            family_name = std::move(wide_name);
            break;
        }
    }
    float scale = static_cast<float>(state.product_scale * state.dpi / 96.0);
    Gdiplus::Font wordmark(family_name.c_str(), 31.0f * scale, Gdiplus::FontStyleBold, Gdiplus::UnitPixel);
    Gdiplus::Font body(family_name.c_str(), 12.0f * scale, Gdiplus::FontStyleRegular, Gdiplus::UnitPixel);
    Gdiplus::Font caption(family_name.c_str(), 11.0f * scale, Gdiplus::FontStyleRegular, Gdiplus::UnitPixel);
    Gdiplus::SolidBrush ink(Gdiplus::Color(255, 34, 58, 88));
    Gdiplus::SolidBrush accent(Gdiplus::Color(255, 25, 118, 233));
    graphics.DrawString(utf8_to_wide(kStartupAppName).c_str(), -1, &wordmark, Gdiplus::PointF(32 * scale, 28 * scale), &ink);
    graphics.DrawString(utf8_to_wide(kStartupAppVersion).c_str(), -1, &caption, Gdiplus::PointF(32 * scale, 68 * scale), &accent);

    long long elapsed = 0;
    if (state.present_tick != 0) {
        elapsed = static_cast<long long>(GetTickCount64() - state.present_tick);
    }
    int tip_index = session_tip_index(state.session, elapsed);
    if (tip_index < 0 || tip_index >= kStartupTipCount) {
        tip_index = 0;
    }
    float breathe = 1.0f;
    if (!state.reduced_motion && kStartupBreathePeriodMs > 0) {
        float phase = static_cast<float>(elapsed % kStartupBreathePeriodMs) / static_cast<float>(kStartupBreathePeriodMs);
        breathe = 0.7f + 0.3f * (0.5f + 0.5f * cosf(phase * 6.2831853f));
    }
    Gdiplus::Pen spectrum(Gdiplus::Color(static_cast<BYTE>(180 * breathe), 23, 182, 223), 1.2f * scale);
    for (int row = 0; row < kStartupSpectrumRows; ++row) {
        std::vector<Gdiplus::PointF> points;
        points.reserve(static_cast<size_t>(kStartupSpectrumSamples));
        for (int sample = 0; sample < kStartupSpectrumSamples; sample += 2) {
            int offset = row * kStartupSpectrumSamples + sample;
            float x = kStartupSpectrumX[offset] * (static_cast<float>(width) / 640.0f);
            float y = 100.0f * scale + kStartupSpectrumY[offset] * (180.0f * scale / 184.0f);
            points.push_back(Gdiplus::PointF(x, y));
        }
        if (points.size() > 1) {
            graphics.DrawLines(&spectrum, points.data(), static_cast<INT>(points.size()));
        }
    }
    const char* label = stage_label(state.session, elapsed);
    Gdiplus::Font status_font(family_name.c_str(), 12.0f * scale, Gdiplus::FontStyleBold, Gdiplus::UnitPixel);
    graphics.DrawString(utf8_to_wide(label).c_str(), -1, &status_font, Gdiplus::PointF(32 * scale, 300 * scale), &ink);
    graphics.DrawString(
        utf8_to_wide(kStartupTipTitles[tip_index]).c_str(),
        -1,
        &status_font,
        Gdiplus::PointF(32 * scale, 340 * scale),
        &accent);
    graphics.DrawString(
        utf8_to_wide(kStartupTipBodies[tip_index]).c_str(),
        -1,
        &body,
        Gdiplus::PointF(32 * scale, 366 * scale),
        &ink);
    graphics.DrawString(utf8_to_wide(kStartupCreditLeft).c_str(), -1, &caption, Gdiplus::PointF(32 * scale, static_cast<float>(height) - 28 * scale), &ink);

    POINT origin{state.screen_x + (state.screen_w - width) / 2, state.screen_y + (state.screen_h - height) / 2};
    SIZE size{width, height};
    POINT source{0, 0};
    BLENDFUNCTION blend{AC_SRC_OVER, 0, 255, AC_SRC_ALPHA};
    UpdateLayeredWindow(state.hwnd, screen, &origin, &size, memory, &source, 0, &blend, ULW_ALPHA);
    SelectObject(memory, previous);
    DeleteObject(bitmap);
    DeleteDC(memory);
    ReleaseDC(nullptr, screen);
}

void hide_panel(LaunchState& state, const char* reason) {
    if (!state.panel_live) {
        session_hide(state.session, reason);
        return;
    }
    KillTimer(state.hwnd, kFrameTimer);
    ShowWindow(state.hwnd, SW_HIDE);
    state.panel_live = false;
    session_hide(state.session, reason);
    queue_outbound(
        state,
        format_protocol_line(state.session_id, 2, "hidden", "", false, reason));
}

bool create_pipes(LaunchState& state) {
    SECURITY_ATTRIBUTES security{};
    security.nLength = sizeof(security);
    security.bInheritHandle = TRUE;
    if (!CreatePipe(&state.parent_read, &state.child_write, &security, 0)) {
        return false;
    }
    if (!CreatePipe(&state.child_read, &state.parent_write, &security, 0)) {
        return false;
    }
    SetHandleInformation(state.parent_read, HANDLE_FLAG_INHERIT, 0);
    SetHandleInformation(state.parent_write, HANDLE_FLAG_INHERIT, 0);
    return true;
}

void set_native_env(const LaunchState& state, bool install) {
    if (!install) {
        SetEnvironmentVariableW(L"TRACELAB_NATIVE_SPLASH_PROTOCOL", nullptr);
        SetEnvironmentVariableW(L"TRACELAB_NATIVE_SPLASH_SESSION", nullptr);
        SetEnvironmentVariableW(L"TRACELAB_NATIVE_SPLASH_READ", nullptr);
        SetEnvironmentVariableW(L"TRACELAB_NATIVE_SPLASH_WRITE", nullptr);
        return;
    }
    SetEnvironmentVariableW(L"TRACELAB_NATIVE_SPLASH_PROTOCOL", L"1");
    SetEnvironmentVariableW(L"TRACELAB_NATIVE_SPLASH_SESSION", utf8_to_wide(state.session_id).c_str());
    std::wstring read_handle = std::to_wstring(reinterpret_cast<uintptr_t>(state.child_read));
    std::wstring write_handle = std::to_wstring(reinterpret_cast<uintptr_t>(state.child_write));
    SetEnvironmentVariableW(L"TRACELAB_NATIVE_SPLASH_READ", read_handle.c_str());
    SetEnvironmentVariableW(L"TRACELAB_NATIVE_SPLASH_WRITE", write_handle.c_str());
}

DWORD WINAPI runtime_thread(LPVOID param) {
    LaunchState& state = *static_cast<LaunchState*>(param);
    std::wstring command = state.command_line;
    std::vector<wchar_t> mutable_command(command.begin(), command.end());
    mutable_command.push_back(L'\0');
    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof(startup);
    startup.StartupInfo.dwFlags = STARTF_USESHOWWINDOW;
    startup.StartupInfo.wShowWindow = SW_SHOWNORMAL;
    SIZE_T bytes = 0;
    InitializeProcThreadAttributeList(nullptr, 1, 0, &bytes);
    startup.lpAttributeList = static_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(HeapAlloc(GetProcessHeap(), 0, bytes));
    HANDLE inherited[2] = {state.child_read, state.child_write};
    BOOL handles_ready = FALSE;
    if (startup.lpAttributeList != nullptr &&
        InitializeProcThreadAttributeList(startup.lpAttributeList, 1, 0, &bytes) &&
        UpdateProcThreadAttribute(
            startup.lpAttributeList,
            0,
            PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            inherited,
            sizeof(inherited),
            nullptr,
            nullptr)) {
        handles_ready = TRUE;
    }
    set_native_env(state, true);
    PROCESS_INFORMATION process{};
    DWORD flags = CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT | CREATE_BREAKAWAY_FROM_JOB;
    BOOL created = FALSE;
    if (handles_ready) {
        created = CreateProcessW(
            state.runtime_path.c_str(),
            mutable_command.data(),
            nullptr,
            nullptr,
            TRUE,
            flags,
            nullptr,
            nullptr,
            &startup.StartupInfo,
            &process);
    }
    if (!created) {
        flags = CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT;
        created = CreateProcessW(
            state.runtime_path.c_str(),
            mutable_command.data(),
            nullptr,
            nullptr,
            TRUE,
            flags,
            nullptr,
            nullptr,
            &startup.StartupInfo,
            &process);
    }
    set_native_env(state, false);
    if (startup.lpAttributeList != nullptr) {
        DeleteProcThreadAttributeList(startup.lpAttributeList);
        HeapFree(GetProcessHeap(), 0, startup.lpAttributeList);
    }
    if (!created) {
        PostMessageW(state.hwnd, WM_APP_EXIT, 1, 0);
        return 0;
    }
    state.process = process.hProcess;
    CloseHandle(process.hThread);
    CloseHandle(state.child_read);
    CloseHandle(state.child_write);
    state.child_read = nullptr;
    state.child_write = nullptr;
    std::string buffer;
    while (WaitForSingleObject(process.hProcess, 0) == WAIT_TIMEOUT) {
        DWORD available = 0;
        if (PeekNamedPipe(state.parent_read, nullptr, 0, nullptr, &available, nullptr) && available > 0) {
            std::string chunk(available, '\0');
            DWORD read = 0;
            if (ReadFile(state.parent_read, chunk.data(), available, &read, nullptr) && read > 0) {
                buffer.append(chunk.data(), read);
                size_t newline = 0;
                while ((newline = buffer.find('\n')) != std::string::npos) {
                    std::string line = buffer.substr(0, newline);
                    buffer.erase(0, newline + 1);
                    ProtocolMessage message = parse_protocol_line(line);
                    if (!message.ok || message.session != state.session_id) {
                        continue;
                    }
                    if (message.type == "stage") {
                        {
                            std::lock_guard<std::mutex> lock(state.outbound_mu);
                            state.pending_stage = message.stage;
                            state.pending_slow = message.slow;
                            state.pending_stage_valid = true;
                        }
                        PostMessageW(state.hwnd, WM_APP_STAGE, 0, 0);
                    } else if (message.type == "finish") {
                        PostMessageW(state.hwnd, WM_APP_FINISH, 0, 0);
                    }
                }
            }
        }
        std::vector<std::string> pending;
        {
            std::lock_guard<std::mutex> lock(state.outbound_mu);
            pending.swap(state.outbound);
        }
        for (const std::string& line : pending) {
            std::string framed = line;
            framed.push_back('\n');
            DWORD written = 0;
            WriteFile(state.parent_write, framed.data(), static_cast<DWORD>(framed.size()), &written, nullptr);
        }
        Sleep(10);
    }
    DWORD code = 1;
    GetExitCodeProcess(process.hProcess, &code);
    PostMessageW(state.hwnd, WM_APP_EXIT, code, 0);
    return 0;
}

void start_runtime(LaunchState& state) {
    if (state.runtime_started) {
        return;
    }
    state.runtime_started = true;
    if (!create_pipes(state)) {
        state.exit_code = 1;
        state.exit_known = true;
        PostMessageW(state.hwnd, WM_APP_EXIT, 1, 0);
        return;
    }
    {
        std::ostringstream presented;
        presented << "{\"v\":1,\"session\":\"" << state.session_id
                  << "\",\"seq\":1,\"type\":\"presented\",\"screen\":["
                  << state.screen_x << "," << state.screen_y << ","
                  << state.screen_w << "," << state.screen_h << "]}";
        queue_outbound(state, presented.str());
    }
    HANDLE thread = CreateThread(nullptr, 0, runtime_thread, &state, 0, nullptr);
    if (thread != nullptr) {
        CloseHandle(thread);
    }
}

LRESULT CALLBACK panel_wndproc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
    LaunchState* state = g_state;
    switch (message) {
    case WM_TIMER:
        if (state != nullptr && state->panel_live) {
            paint_panel(*state);
            if (!state->second_frame_sent) {
                state->second_frame_sent = true;
                send_probe(*state, "native_second_frame");
            }
        }
        return 0;
    case WM_APP_STAGE:
        if (state != nullptr && !state->session.hidden) {
            std::string stage;
            bool slow = false;
            bool valid = false;
            {
                std::lock_guard<std::mutex> lock(state->outbound_mu);
                valid = state->pending_stage_valid;
                stage = state->pending_stage;
                slow = state->pending_slow;
            }
            if (valid) {
                session_stage(state->session, stage, slow);
            }
            paint_panel(*state);
        }
        return 0;
    case WM_APP_FINISH:
        if (state != nullptr) {
            if (state->session.hidden) {
                queue_outbound(*state, format_protocol_line(state->session_id, 2, "hidden", "", false, state->session.hidden_reason.c_str()));
            } else {
                session_finish(state->session);
                hide_panel(*state, "finish_close");
            }
        }
        return 0;
    case WM_CLOSE:
        if (state != nullptr) {
            hide_panel(*state, "user_close");
        }
        return 0;
    case WM_APP_EXIT:
        if (state != nullptr) {
            state->exit_code = static_cast<int>(wparam);
            state->exit_known = true;
            if (state->panel_live && state->exit_code != 0) {
                MessageBoxW(hwnd, L"TraceLab 未能完成启动。", L"TraceLab", MB_OK | MB_ICONERROR | MB_SETFOREGROUND);
            }
            hide_panel(*state, state->session.hidden ? state->session.hidden_reason.c_str() : "never_shown");
            PostQuitMessage(0);
        }
        return 0;
    default:
        break;
    }
    return DefWindowProcW(hwnd, message, wparam, lparam);
}

int passthrough(const std::wstring& runtime, int argc, wchar_t** argv) {
    std::wstring command = build_command_line(runtime, argc, argv);
    std::vector<wchar_t> mutable_command(command.begin(), command.end());
    mutable_command.push_back(L'\0');
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION process{};
    DWORD flags = CREATE_UNICODE_ENVIRONMENT | CREATE_BREAKAWAY_FROM_JOB;
    if (!CreateProcessW(runtime.c_str(), mutable_command.data(), nullptr, nullptr, TRUE, flags, nullptr, nullptr, &startup, &process)) {
        flags = CREATE_UNICODE_ENVIRONMENT;
        if (!CreateProcessW(runtime.c_str(), mutable_command.data(), nullptr, nullptr, TRUE, flags, nullptr, nullptr, &startup, &process)) {
            return 1;
        }
    }
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(process.hProcess, &code);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return static_cast<int>(code);
}

bool enable_dpi_awareness() {
    HMODULE user32 = GetModuleHandleW(L"user32.dll");
    if (user32 == nullptr) {
        return false;
    }
    using SetContextFn = BOOL(WINAPI*)(HANDLE);
    auto set_context = reinterpret_cast<SetContextFn>(GetProcAddress(user32, "SetProcessDpiAwarenessContext"));
    if (set_context != nullptr) {
        return set_context(reinterpret_cast<HANDLE>(-4)) == TRUE;  // PER_MONITOR_AWARE_V2
    }
    SetProcessDPIAware();
    return true;
}

}  // namespace

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int) {
    enable_dpi_awareness();
    int argc = 0;
    wchar_t** argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    std::vector<std::string> args;
    for (int i = 1; i < argc; ++i) {
        args.push_back(wide_to_utf8(argv[i]));
    }
    std::wstring runtime = runtime_path_from_module();
    if (!should_present_native_panel(args, current_env())) {
        int code = passthrough(runtime, argc, argv);
        LocalFree(argv);
        return code;
    }
    LaunchState state;
    g_state = &state;
    state.argc = argc;
    state.argv = argv;
    state.runtime_path = runtime;
    state.command_line = build_command_line(runtime, argc, argv);
    state.session_id = make_session_id();
    unsigned int tip_word = 0;
    rand_s(&tip_word);
    state.session.opening_index = static_cast<int>(tip_word % static_cast<unsigned int>(kStartupTipCount));
    state.session.tip_count = kStartupTipCount;
    state.reduced_motion = reduced_motion_enabled();
    auto env = current_env();
    if (env["TRACELAB_STARTUP_TIMING"] == "1" && !env["TRACELAB_STARTUP_PROBE_HOST"].empty()) {
        state.probe_enabled = true;
        state.probe_host = env["TRACELAB_STARTUP_PROBE_HOST"];
        state.probe_port = env["TRACELAB_STARTUP_PROBE_PORT"];
        state.run_id = env["TRACELAB_STARTUP_RUN_ID"];
        WSADATA wsa{};
        WSAStartup(MAKEWORD(2, 2), &wsa);
    }
    choose_screen(state);
    WNDCLASSW window_class{};
    window_class.lpfnWndProc = panel_wndproc;
    window_class.hInstance = instance;
    window_class.lpszClassName = L"TraceLabStartupLauncher";
    RegisterClassW(&window_class);
    int width = window_pixel_width(state);
    int height = window_pixel_height(state);
    state.hwnd = CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
        window_class.lpszClassName,
        L"TraceLab",
        WS_POPUP,
        state.screen_x,
        state.screen_y,
        width,
        height,
        nullptr,
        nullptr,
        instance,
        nullptr);
    Gdiplus::GdiplusStartupInput gdiplus_input;
    ULONG_PTR gdiplus_token = 0;
    Gdiplus::GdiplusStartup(&gdiplus_token, &gdiplus_input, nullptr);
    if (state.hwnd == nullptr) {
        session_present_failed(state.session);
        int code = passthrough(runtime, argc, argv);
        Gdiplus::GdiplusShutdown(gdiplus_token);
        LocalFree(argv);
        return code;
    }
    state.panel_live = true;
    session_present(state.session, state.screen_x, state.screen_y, state.screen_w, state.screen_h, 0);
    state.present_tick = GetTickCount64();
    paint_panel(state);
    send_probe(state, "native_first_present");
    SetTimer(state.hwnd, kFrameTimer, kStartupFrameIntervalMs, nullptr);
    ShowWindow(state.hwnd, SW_SHOWNOACTIVATE);
    start_runtime(state);
    MSG message;
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    if (state.process != nullptr) {
        CloseHandle(state.process);
    }
    if (state.parent_read != nullptr) {
        CloseHandle(state.parent_read);
    }
    if (state.parent_write != nullptr) {
        CloseHandle(state.parent_write);
    }
    Gdiplus::GdiplusShutdown(gdiplus_token);
    LocalFree(argv);
    return state.exit_known ? state.exit_code : 0;
}
