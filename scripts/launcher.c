/*
 * scripts/launcher.c
 * ==================
 * Native Windows Zero-Config GUI Bootstrapper & Launcher for Voicer Studio.
 * 
 * Features:
 * 1. 100% Native Windows GUI (Subsystem: Windows, zero console window).
 * 2. 100% Non-Admin / User Space: Self-contained in ./runtime/python and ./runtime/bin without UAC elevation.
 * 3. Modern Adobe Studio Dark Setup & Splash GUI with progress bar, percentage, and live activity logs.
 * 4. Automated Zero-Config Setup Workflow on first launch:
 *    - Self-contained Python 3.11 Embeddable runtime download & extraction.
 *    - python311._pth patching for site-packages support.
 *    - Standalone pip bootstrap via get-pip.py.
 *    - Standalone static FFmpeg & FFprobe setup.
 *    - Automated pip requirements installation without scary console popups.
 * 5. Instant Startup (< 1ms) on subsequent runs once runtime is ready.
 * 6. Dynamic PATH & PYTHONHOME environment injection.
 */

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN

#include <windows.h>
#include <commctrl.h>
#include <shellapi.h>
#include <shlwapi.h>
#include <wininet.h>
#include <dwmapi.h>
#include <stdio.h>
#include <stdbool.h>
#include <stdint.h>
#include <process.h>

#pragma comment(lib, "wininet.lib")
#pragma comment(lib, "shlwapi.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "gdi32.lib")
#pragma comment(lib, "comctl32.lib")
#pragma comment(lib, "dwmapi.lib")
#pragma comment(lib, "ole32.lib")

// ── UI Theme Palette Constants (Adobe / Dark Studio) ─────────────────────────
#define COLOR_BG_PRIMARY    RGB(37, 37, 37)     // #252525
#define COLOR_BG_PANEL      RGB(45, 45, 45)     // #2D2D2D
#define COLOR_BG_INPUT      RGB(30, 30, 30)     // #1E1E1E
#define COLOR_BORDER        RGB(66, 66, 66)     // #424242
#define COLOR_ACCENT_BLUE   RGB(20, 115, 230)   // #1473E6
#define COLOR_TEXT_PRIMARY  RGB(240, 240, 240) // #F0F0F0
#define COLOR_TEXT_MUTED    RGB(160, 160, 160) // #A0A0A0
#define COLOR_TEXT_DIM      RGB(120, 120, 120) // #787878
#define COLOR_STATUS_ERR    RGB(224, 93, 93)   // #E05D5D
#define COLOR_STATUS_OK     RGB(34, 160, 91)   // #22A05B

// ── Window & Control IDs ──────────────────────────────────────────────────────
#define WM_APP_PROGRESS     (WM_APP + 101)
#define WM_APP_STATUS       (WM_APP + 102)
#define WM_APP_DONE         (WM_APP + 103)
#define WM_APP_ERROR        (WM_APP + 104)

#define IDC_BTN_CANCEL      2001
#define IDC_BTN_RETRY       2002

#define WIN_WIDTH           580
#define WIN_HEIGHT          360

// ── URLs for Standalone Non-Admin Setup ───────────────────────────────────────
#define URL_PYTHON_EMBED    L"https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
#define URL_GET_PIP         L"https://bootstrap.pypa.io/get-pip.py"
#define URL_FFMPEG_ZIP      L"https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
#define URL_FFMPEG_GYAN     L"https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

// ── Global State ─────────────────────────────────────────────────────────────
typedef struct {
    HWND hwnd;
    HINSTANCE hInstance;
    wchar_t exeDir[MAX_PATH];
    wchar_t runnerExe[MAX_PATH];
    wchar_t mainScript[MAX_PATH];
    PWSTR pCmdLine;
    
    // UI dynamic states
    int progressPct;
    wchar_t stageTitle[256];
    wchar_t statusDetail[512];
    bool isError;
    wchar_t errorMsg[512];
    bool isDone;
    bool shouldCancel;
    
    HANDLE hWorkerThread;
} AppState;

static AppState g_App;

// ── Helper File / Directory Utilities ─────────────────────────────────────────
static bool FileExists(const wchar_t *path) {
    DWORD attr = GetFileAttributesW(path);
    return (attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY));
}

static bool DirectoryExists(const wchar_t *path) {
    DWORD attr = GetFileAttributesW(path);
    return (attr != INVALID_FILE_ATTRIBUTES && (attr & FILE_ATTRIBUTE_DIRECTORY));
}

static void CreateDirRecursive(const wchar_t *path) {
    wchar_t temp[MAX_PATH];
    wchar_t *pos = NULL;
    lstrcpynW(temp, path, MAX_PATH);
    for (pos = temp + 3; *pos; pos++) {
        if (*pos == L'\\' || *pos == L'/') {
            *pos = L'\0';
            CreateDirectoryW(temp, NULL);
            *pos = L'\\';
        }
    }
    CreateDirectoryW(temp, NULL);
}

static void EnsureSettingsExist(const wchar_t *exeDir) {
    wchar_t settingsPath[MAX_PATH];
    wsprintfW(settingsPath, L"%s\\settings.json", exeDir);

    if (!FileExists(settingsPath)) {
        wchar_t examplePath[MAX_PATH];
        wsprintfW(examplePath, L"%s\\settings.example.json", exeDir);
        if (FileExists(examplePath)) {
            CopyFileW(examplePath, settingsPath, TRUE);
        } else {
            wsprintfW(examplePath, L"%s\\scripts\\settings.example.json", exeDir);
            if (FileExists(examplePath)) {
                CopyFileW(examplePath, settingsPath, TRUE);
            }
        }
    }
}

// ── Fast Environment Readiness Check ──────────────────────────────────────────
static bool CheckEnvironmentReady(const wchar_t *exeDir, wchar_t *outRunner, wchar_t *outMainPy) {
    wsprintfW(outMainPy, L"%s\\main.py", exeDir);
    if (!FileExists(outMainPy)) return false;

    // 1. Primary: Self-contained runtime (./runtime/python)
    wchar_t runtimePythonw[MAX_PATH];
    wchar_t runtimePython[MAX_PATH];
    wchar_t runtimePySide[MAX_PATH];
    wchar_t runtimeFFmpeg[MAX_PATH];

    wsprintfW(runtimePythonw, L"%s\\runtime\\python\\pythonw.exe", exeDir);
    wsprintfW(runtimePython, L"%s\\runtime\\python\\python.exe", exeDir);
    wsprintfW(runtimePySide, L"%s\\runtime\\python\\Lib\\site-packages\\PySide6", exeDir);
    wsprintfW(runtimeFFmpeg, L"%s\\runtime\\bin\\ffmpeg.exe", exeDir);

    if ((FileExists(runtimePythonw) || FileExists(runtimePython)) && DirectoryExists(runtimePySide)) {
        wcscpy(outRunner, FileExists(runtimePythonw) ? runtimePythonw : runtimePython);
        return true;
    }

    // 2. Secondary / Legacy: Virtual environment (./.venv)
    wchar_t venvHost[MAX_PATH];
    wchar_t venvPythonw[MAX_PATH];
    wchar_t venvPySide[MAX_PATH];

    wsprintfW(venvHost, L"%s\\.venv\\Scripts\\VoicerStudio.exe", exeDir);
    wsprintfW(venvPythonw, L"%s\\.venv\\Scripts\\pythonw.exe", exeDir);
    wsprintfW(venvPySide, L"%s\\.venv\\Lib\\site-packages\\PySide6", exeDir);

    if (FileExists(venvHost) && DirectoryExists(venvPySide)) {
        wcscpy(outRunner, venvHost);
        return true;
    } else if (FileExists(venvPythonw) && DirectoryExists(venvPySide)) {
        wcscpy(outRunner, venvPythonw);
        return true;
    }

    return false;
}

// ── Dynamic Environment Injected Application Launch ───────────────────────────
static int LaunchVoicerStudio(const wchar_t *exeDir, const wchar_t *runner, const wchar_t *mainScript, PWSTR pCmdLine) {
    // 1. Setup Process PATH to include local runtime tools
    wchar_t oldPath[32768] = {0};
    wchar_t newPath[32768] = {0};
    GetEnvironmentVariableW(L"PATH", oldPath, 32768);

    wsprintfW(newPath, L"%s\\runtime\\bin;%s\\runtime\\python;%s\\runtime\\python\\Scripts;%s\\tools\\ffmpeg\\bin;%s",
              exeDir, exeDir, exeDir, exeDir, oldPath);
    SetEnvironmentVariableW(L"PATH", newPath);

    // Set PYTHONHOME for embeddable python if running from runtime\python
    if (wcsstr(runner, L"runtime\\python") != NULL) {
        wchar_t pyHome[MAX_PATH];
        wsprintfW(pyHome, L"%s\\runtime\\python", exeDir);
        SetEnvironmentVariableW(L"PYTHONHOME", pyHome);
    }

    wchar_t cmdLine[4096];
    if (pCmdLine && wcslen(pCmdLine) > 0) {
        wsprintfW(cmdLine, L"\"%s\" \"%s\" %s", runner, mainScript, pCmdLine);
    } else {
        wsprintfW(cmdLine, L"\"%s\" \"%s\"", runner, mainScript);
    }

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_SHOWNORMAL;
    ZeroMemory(&pi, sizeof(pi));

    BOOL success = CreateProcessW(
        runner,
        cmdLine,
        NULL,
        NULL,
        FALSE,
        CREATE_BREAKAWAY_FROM_JOB,
        NULL,
        exeDir,
        &si,
        &pi
    );

    if (!success) {
        success = CreateProcessW(
            runner,
            cmdLine,
            NULL,
            NULL,
            FALSE,
            0,
            NULL,
            exeDir,
            &si,
            &pi
        );
    }

    if (!success) {
        DWORD err = GetLastError();
        wchar_t errMsg[512];
        wsprintfW(errMsg, L"Failed to start Voicer Studio.\nWindows Error Code: %lu\n\nTarget: %s", err, runner);
        MessageBoxW(NULL, errMsg, L"Voicer Studio — Launch Error", MB_OK | MB_ICONERROR);
        return 1;
    }

    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    return 0;
}

// ── Silent Subprocess Execution with Piping ───────────────────────────────────
typedef void (*LineOutputCallback)(const char *line, void *userData);

static bool RunCommandSilent(const wchar_t *exeDir, const wchar_t *cmdLine, LineOutputCallback cb, void *userData, DWORD timeoutMs) {
    SECURITY_ATTRIBUTES sa;
    sa.nLength = sizeof(SECURITY_ATTRIBUTES);
    sa.bInheritHandle = TRUE;
    sa.lpSecurityDescriptor = NULL;

    HANDLE hReadPipe = NULL, hWritePipe = NULL;
    if (!CreatePipe(&hReadPipe, &hWritePipe, &sa, 0)) {
        return false;
    }
    SetHandleInformation(hReadPipe, HANDLE_FLAG_INHERIT, 0);

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW | STARTF_USESTDHANDLES;
    si.wShowWindow = SW_HIDE;
    si.hStdOutput = hWritePipe;
    si.hStdError = hWritePipe;
    ZeroMemory(&pi, sizeof(pi));

    wchar_t cmdMutable[4096];
    lstrcpynW(cmdMutable, cmdLine, 4096);

    BOOL created = CreateProcessW(
        NULL,
        cmdMutable,
        NULL,
        NULL,
        TRUE,
        CREATE_NO_WINDOW,
        NULL,
        exeDir,
        &si,
        &pi
    );

    CloseHandle(hWritePipe);

    if (!created) {
        CloseHandle(hReadPipe);
        return false;
    }

    char buffer[1024];
    DWORD bytesRead = 0;
    char lineBuffer[1024] = {0};
    int linePos = 0;

    while (ReadFile(hReadPipe, buffer, sizeof(buffer) - 1, &bytesRead, NULL) && bytesRead > 0) {
        buffer[bytesRead] = '\0';
        for (DWORD i = 0; i < bytesRead; i++) {
            char c = buffer[i];
            if (c == '\r' || c == '\n') {
                if (linePos > 0) {
                    lineBuffer[linePos] = '\0';
                    if (cb) cb(lineBuffer, userData);
                    linePos = 0;
                }
            } else if (linePos < sizeof(lineBuffer) - 2) {
                lineBuffer[linePos++] = c;
            }
        }
    }

    if (linePos > 0) {
        lineBuffer[linePos] = '\0';
        if (cb) cb(lineBuffer, userData);
    }

    CloseHandle(hReadPipe);
    WaitForSingleObject(pi.hProcess, timeoutMs);

    DWORD exitCode = 1;
    GetExitCodeProcess(pi.hProcess, &exitCode);
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);

    return (exitCode == 0);
}

// ── Native WinINet HTTPS Downloader ──────────────────────────────────────────
typedef void (*DownloadProgressCallback)(int percent, uint64_t downloadedBytes, uint64_t totalBytes, void *userData);

static bool DownloadFileWinINet(const wchar_t *url, const wchar_t *destFile, DownloadProgressCallback cb, void *userData) {
    HINTERNET hInternet = InternetOpenW(L"VoicerStudio-Bootstrapper/1.1", INTERNET_OPEN_TYPE_PRECONFIG, NULL, NULL, 0);
    if (!hInternet) return false;

    DWORD flags = INTERNET_FLAG_RELOAD | INTERNET_FLAG_NO_CACHE_WRITE | INTERNET_FLAG_SECURE | INTERNET_FLAG_IGNORE_CERT_CN_INVALID | INTERNET_FLAG_IGNORE_CERT_DATE_INVALID;
    HINTERNET hUrl = InternetOpenUrlW(hInternet, url, NULL, 0, flags, 0);
    if (!hUrl) {
        // Fallback without strict SSL flags
        hUrl = InternetOpenUrlW(hInternet, url, NULL, 0, INTERNET_FLAG_RELOAD | INTERNET_FLAG_NO_CACHE_WRITE, 0);
    }

    if (!hUrl) {
        InternetCloseHandle(hInternet);
        return false;
    }

    // Get Content-Length
    DWORD contentLength = 0;
    DWORD lengthSize = sizeof(contentLength);
    DWORD headerIndex = 0;
    HttpQueryInfoW(hUrl, HTTP_QUERY_CONTENT_LENGTH | HTTP_QUERY_FLAG_NUMBER, &contentLength, &lengthSize, &headerIndex);

    FILE *fp = _wfopen(destFile, L"wb");
    if (!fp) {
        InternetCloseHandle(hUrl);
        InternetCloseHandle(hInternet);
        return false;
    }

    BYTE buffer[16384];
    DWORD bytesRead = 0;
    uint64_t totalRead = 0;
    int lastPct = -1;

    while (InternetReadFile(hUrl, buffer, sizeof(buffer), &bytesRead) && bytesRead > 0) {
        if (g_App.shouldCancel) {
            fclose(fp);
            InternetCloseHandle(hUrl);
            InternetCloseHandle(hInternet);
            DeleteFileW(destFile);
            return false;
        }

        fwrite(buffer, 1, bytesRead, fp);
        totalRead += bytesRead;

        if (contentLength > 0) {
            int pct = (int)((totalRead * 100) / contentLength);
            if (pct != lastPct) {
                lastPct = pct;
                if (cb) cb(pct, totalRead, contentLength, userData);
            }
        } else {
            if (cb) cb(-1, totalRead, 0, userData);
        }
    }

    fclose(fp);
    InternetCloseHandle(hUrl);
    InternetCloseHandle(hInternet);
    return true;
}

// ── Native ZIP Extraction Utility ────────────────────────────────────────────
static bool ExtractZip(const wchar_t *exeDir, const wchar_t *zipPath, const wchar_t *destDir) {
    CreateDirRecursive(destDir);

    // 1. Try Windows built-in tar.exe (fastest, available on Windows 10/11)
    wchar_t tarCmd[2048];
    wsprintfW(tarCmd, L"tar.exe -xf \"%s\" -C \"%s\"", zipPath, destDir);
    if (RunCommandSilent(exeDir, tarCmd, NULL, NULL, 60000)) {
        return true;
    }

    // 2. Fallback: PowerShell Expand-Archive (built-in Windows)
    wchar_t psCmd[4096];
    wsprintfW(psCmd, L"powershell.exe -NoProfile -ExecutionPolicy Bypass -Command \"Expand-Archive -LiteralPath '%s' -DestinationPath '%s' -Force\"", zipPath, destDir);
    return RunCommandSilent(exeDir, psCmd, NULL, NULL, 120000);
}

// ── Patch python311._pth ─────────────────────────────────────────────────────
static bool PatchPythonPth(const wchar_t *pythonDir) {
    WIN32_FIND_DATAW fd;
    wchar_t pattern[MAX_PATH];
    wsprintfW(pattern, L"%s\\python*._pth", pythonDir);

    HANDLE hFind = FindFirstFileW(pattern, &fd);
    if (hFind == INVALID_HANDLE_VALUE) return false;

    wchar_t pthPath[MAX_PATH];
    wsprintfW(pthPath, L"%s\\%s", pythonDir, fd.cFileName);
    FindClose(hFind);

    FILE *fp = _wfopen(pthPath, L"r");
    if (!fp) return false;

    char content[4096] = {0};
    size_t len = fread(content, 1, sizeof(content) - 1, fp);
    fclose(fp);
    content[len] = '\0';

    // Uncomment import site and add site-packages + parent directory
    char newContent[8192] = {0};
    char *line = strtok(content, "\r\n");
    while (line) {
        if (strcmp(line, "#import site") == 0 || strcmp(line, "# import site") == 0) {
            strcat(newContent, "import site\r\n");
        } else {
            strcat(newContent, line);
            strcat(newContent, "\r\n");
        }
        line = strtok(NULL, "\r\n");
    }

    if (strstr(newContent, "Lib\\site-packages") == NULL) {
        strcat(newContent, ".\\Lib\\site-packages\r\n");
        strcat(newContent, "..\r\n");
        strcat(newContent, "import site\r\n");
    }

    fp = _wfopen(pthPath, L"w");
    if (!fp) return false;
    fwrite(newContent, 1, strlen(newContent), fp);
    fclose(fp);

    // Ensure Lib/site-packages directory exists
    wchar_t sitePkg[MAX_PATH];
    wsprintfW(sitePkg, L"%s\\Lib\\site-packages", pythonDir);
    CreateDirRecursive(sitePkg);

    return true;
}

// ── UI Status & Progress Event Notifiers ───────────────────────────────────────
static void NotifyProgress(int pct, const wchar_t *stage, const wchar_t *detail) {
    g_App.progressPct = max(0, min(100, pct));
    if (stage) lstrcpynW(g_App.stageTitle, stage, 256);
    if (detail) lstrcpynW(g_App.statusDetail, detail, 512);
    PostMessageW(g_App.hwnd, WM_APP_PROGRESS, (WPARAM)g_App.progressPct, 0);
}

static void NotifyError(const wchar_t *msg) {
    g_App.isError = true;
    lstrcpynW(g_App.errorMsg, msg, 512);
    PostMessageW(g_App.hwnd, WM_APP_ERROR, 0, 0);
}

static void NotifyDone() {
    g_App.isDone = true;
    PostMessageW(g_App.hwnd, WM_APP_DONE, 0, 0);
}

static void OnDownloadProgress(int percent, uint64_t readB, uint64_t totalB, void *userData) {
    const wchar_t *prefix = (const wchar_t*)userData;
    wchar_t detail[256];
    if (totalB > 0) {
        double mbRead = (double)readB / (1024.0 * 1024.0);
        double mbTotal = (double)totalB / (1024.0 * 1024.0);
        wsprintfW(detail, L"%s (%.1f / %.1f MB - %d%%)", prefix, mbRead, mbTotal, percent);
    } else {
        double mbRead = (double)readB / (1024.0 * 1024.0);
        wsprintfW(detail, L"%s (%.1f MB)", prefix, mbRead);
    }
    NotifyProgress(g_App.progressPct, NULL, detail);
}

static void OnPipOutput(const char *line, void *userData) {
    wchar_t wLine[512];
    MultiByteToWideChar(CP_UTF8, 0, line, -1, wLine, 512);
    
    // Filter noise and update UI detail
    if (wcsstr(wLine, L"Downloading") || wcsstr(wLine, L"Installing") || wcsstr(wLine, L"Collecting")) {
        NotifyProgress(g_App.progressPct, NULL, wLine);
    }
}

// ── Background Setup Worker Thread ────────────────────────────────────────────
static unsigned __stdcall SetupWorkerThread(void *arg) {
    wchar_t *exeDir = g_App.exeDir;
    wchar_t runtimeDir[MAX_PATH];
    wchar_t pythonDir[MAX_PATH];
    wchar_t binDir[MAX_PATH];
    wchar_t downloadsDir[MAX_PATH];

    wsprintfW(runtimeDir, L"%s\\runtime", exeDir);
    wsprintfW(pythonDir, L"%s\\runtime\\python", exeDir);
    wsprintfW(binDir, L"%s\\runtime\\bin", exeDir);
    wsprintfW(downloadsDir, L"%s\\runtime\\downloads", exeDir);

    CreateDirRecursive(runtimeDir);
    CreateDirRecursive(pythonDir);
    CreateDirRecursive(binDir);
    CreateDirRecursive(downloadsDir);

    // ── STEP 1: Python Embeddable ─────────────────────────────────────────────
    wchar_t pythonExe[MAX_PATH];
    wsprintfW(pythonExe, L"%s\\python.exe", pythonDir);

    if (!FileExists(pythonExe)) {
        NotifyProgress(5, L"กำลังเตรียม Python Environment...", L"กำลังดาวน์โหลด Python 3.11 Embeddable (Non-Admin Runtime)...");
        
        wchar_t zipPython[MAX_PATH];
        wsprintfW(zipPython, L"%s\\python-embed.zip", downloadsDir);

        if (!DownloadFileWinINet(URL_PYTHON_EMBED, zipPython, OnDownloadProgress, (void*)L"ดาวน์โหลด Python 3.11")) {
            NotifyError(L"ไม่สามารถดาวน์โหลด Python Embeddable Package ได้ กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ต");
            return 1;
        }

        NotifyProgress(20, L"กำลังเตรียม Python Environment...", L"กำลังแตกไฟล์ Python Runtime เข้าสู่โฟลเดอร์โปรเจกต์...");
        if (!ExtractZip(exeDir, zipPython, pythonDir)) {
            NotifyError(L"ไม่สามารถแตกไฟล์ Python Package ได้");
            return 1;
        }
        DeleteFileW(zipPython);

        // Patch python311._pth
        if (!PatchPythonPth(pythonDir)) {
            NotifyError(L"ไม่สามารถปรับแต่งไฟล์ python311._pth เพื่อเปิดใช้งาน site-packages ได้");
            return 1;
        }
    }

    // ── STEP 2: Bootstrap PIP ─────────────────────────────────────────────────
    wchar_t pipExe[MAX_PATH];
    wsprintfW(pipExe, L"%s\\Scripts\\pip.exe", pythonDir);

    if (!FileExists(pipExe)) {
        NotifyProgress(25, L"กำลังติดตั้งระบบจัดการแพ็กเกจ (pip)...", L"กำลังดาวน์โหลด get-pip.py...");
        
        wchar_t getPipScript[MAX_PATH];
        wsprintfW(getPipScript, L"%s\\get-pip.py", downloadsDir);

        if (!DownloadFileWinINet(URL_GET_PIP, getPipScript, OnDownloadProgress, (void*)L"ดาวน์โหลด get-pip.py")) {
            NotifyError(L"ไม่สามารถดาวน์โหลด get-pip.py ได้");
            return 1;
        }

        NotifyProgress(35, L"กำลังติดตั้งระบบจัดการแพ็กเกจ (pip)...", L"กำลังรัน get-pip.py (Standalone User-Space)...");
        wchar_t cmdPip[2048];
        wsprintfW(cmdPip, L"\"%s\" \"%s\" --no-warn-script-location", pythonExe, getPipScript);

        if (!RunCommandSilent(exeDir, cmdPip, OnPipOutput, NULL, 180000)) {
            NotifyError(L"การติดตั้ง pip ล้มเหลว กรุณาลองใหม่อีกครั้ง");
            return 1;
        }
        DeleteFileW(getPipScript);
    }

    // ── STEP 3: Standalone Static FFmpeg ───────────────────────────────────────
    wchar_t ffmpegExe[MAX_PATH];
    wsprintfW(ffmpegExe, L"%s\\ffmpeg.exe", binDir);

    if (!FileExists(ffmpegExe)) {
        NotifyProgress(45, L"กำลังติดตั้งระบบเสียง FFmpeg...", L"กำลังดาวน์โหลด Standalone FFmpeg & FFprobe...");

        wchar_t ffmpegZip[MAX_PATH];
        wsprintfW(ffmpegZip, L"%s\\ffmpeg.zip", downloadsDir);

        bool dlOk = DownloadFileWinINet(URL_FFMPEG_ZIP, ffmpegZip, OnDownloadProgress, (void*)L"ดาวน์โหลด FFmpeg Static Build");
        if (!dlOk) {
            dlOk = DownloadFileWinINet(URL_FFMPEG_GYAN, ffmpegZip, OnDownloadProgress, (void*)L"ดาวน์โหลด FFmpeg Release Mirror");
        }

        if (dlOk) {
            NotifyProgress(55, L"กำลังติดตั้งระบบเสียง FFmpeg...", L"กำลังแตกไฟล์ FFmpeg Codecs เข้าสู่ runtime/bin...");
            wchar_t ffmpegTempDir[MAX_PATH];
            wsprintfW(ffmpegTempDir, L"%s\\ffmpeg_temp", downloadsDir);
            CreateDirRecursive(ffmpegTempDir);

            if (ExtractZip(exeDir, ffmpegZip, ffmpegTempDir)) {
                // Search for ffmpeg.exe recursively inside extracted directory
                wchar_t searchPattern[MAX_PATH];
                wsprintfW(searchPattern, L"%s\\*ffmpeg.exe", ffmpegTempDir);
                
                // Copy binaries to runtime/bin
                wchar_t psCopyCmd[4096];
                wsprintfW(psCopyCmd, L"powershell.exe -NoProfile -Command \"Get-ChildItem -Path '%s' -Recurse -Filter 'ffmpeg.exe' | Copy-Item -Destination '%s' -Force; Get-ChildItem -Path '%s' -Recurse -Filter 'ffprobe.exe' | Copy-Item -Destination '%s' -Force\"",
                          ffmpegTempDir, binDir, ffmpegTempDir, binDir);
                RunCommandSilent(exeDir, psCopyCmd, NULL, NULL, 30000);
            }
            DeleteFileW(ffmpegZip);
        }
    }

    // Copy to tools/ffmpeg/bin for backward compatibility if present
    wchar_t legacyToolsBin[MAX_PATH];
    wsprintfW(legacyToolsBin, L"%s\\tools\\ffmpeg\\bin", exeDir);
    CreateDirRecursive(legacyToolsBin);
    if (FileExists(ffmpegExe)) {
        wchar_t legacyFfmpeg[MAX_PATH];
        wsprintfW(legacyFfmpeg, L"%s\\ffmpeg.exe", legacyToolsBin);
        if (!FileExists(legacyFfmpeg)) CopyFileW(ffmpegExe, legacyFfmpeg, FALSE);
    }

    // ── STEP 4: Install Dependencies (requirements.txt) ──────────────────────
    wchar_t reqFile[MAX_PATH];
    wsprintfW(reqFile, L"%s\\requirements.txt", exeDir);

    if (FileExists(reqFile)) {
        NotifyProgress(65, L"กำลังติดตั้งไลบรารี AI และส่วนประกอบโปรแกรม...", L"กำลังติดตั้งไลบรารีจาก requirements.txt (PySide6, Whisper, PyTorch)...");
        
        wchar_t cmdInstall[4096];
        wsprintfW(cmdInstall, L"\"%s\" -m pip install -r \"%s\" --no-warn-script-location --no-input", pythonExe, reqFile);

        g_App.progressPct = 70;
        if (!RunCommandSilent(exeDir, cmdInstall, OnPipOutput, NULL, 600000)) {
            NotifyError(L"การติดตั้งไลบรารีจาก requirements.txt ไม่สมบูรณ์ กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ต");
            return 1;
        }
    }

    // ── STEP 5: Finalization ──────────────────────────────────────────────────
    EnsureSettingsExist(exeDir);
    NotifyProgress(100, L"การติดตั้งเสร็จสมบูรณ์!", L"กำลังเริ่มโปรแกรม Voicer Studio...");
    Sleep(400);

    NotifyDone();
    return 0;
}

// ── Native Win32 Custom GUI Rendering & Window Procedure ─────────────────────
static LRESULT CALLBACK SetupWndProc(HWND hwnd, UINT uMsg, WPARAM wParam, LPARAM lParam) {
    switch (uMsg) {
        case WM_CREATE: {
            // Apply Modern Dark Window Frame via DWM
            BOOL darkMode = TRUE;
            DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, &darkMode, sizeof(darkMode));

            // Create Cancel / Close Button
            CreateWindowW(
                L"BUTTON", L"ยกเลิก (Cancel)",
                WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON | BS_FLAT,
                WIN_WIDTH - 150, WIN_HEIGHT - 65, 120, 32,
                hwnd, (HMENU)IDC_BTN_CANCEL, g_App.hInstance, NULL
            );
            return 0;
        }

        case WM_COMMAND: {
            int wmId = LOWORD(wParam);
            if (wmId == IDC_BTN_CANCEL) {
                if (g_App.isError || g_App.isDone) {
                    PostQuitMessage(0);
                } else {
                    int choice = MessageBoxW(hwnd, L"ต้องการยกเลิกการติดตั้งใช่หรือไม่?", L"Voicer Studio Setup", MB_YESNO | MB_ICONQUESTION);
                    if (choice == IDYES) {
                        g_App.shouldCancel = true;
                        PostQuitMessage(0);
                    }
                }
            } else if (wmId == IDC_BTN_RETRY) {
                g_App.isError = false;
                g_App.shouldCancel = false;
                EnableWindow(GetDlgItem(hwnd, IDC_BTN_RETRY), FALSE);
                ShowWindow(GetDlgItem(hwnd, IDC_BTN_RETRY), SW_HIDE);
                g_App.hWorkerThread = (HANDLE)_beginthreadex(NULL, 0, SetupWorkerThread, NULL, 0, NULL);
            }
            return 0;
        }

        case WM_APP_PROGRESS: {
            InvalidateRect(hwnd, NULL, FALSE);
            return 0;
        }

        case WM_APP_DONE: {
            // Launch main application and close bootstrapper
            wchar_t runner[MAX_PATH];
            wchar_t mainPy[MAX_PATH];
            if (CheckEnvironmentReady(g_App.exeDir, runner, mainPy)) {
                LaunchVoicerStudio(g_App.exeDir, runner, mainPy, g_App.pCmdLine);
            }
            PostQuitMessage(0);
            return 0;
        }

        case WM_APP_ERROR: {
            InvalidateRect(hwnd, NULL, FALSE);
            
            // Show Retry Button
            HWND btnRetry = GetDlgItem(hwnd, IDC_BTN_RETRY);
            if (!btnRetry) {
                btnRetry = CreateWindowW(
                    L"BUTTON", L"ลองใหม่ (Retry)",
                    WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON | BS_FLAT,
                    WIN_WIDTH - 280, WIN_HEIGHT - 65, 120, 32,
                    hwnd, (HMENU)IDC_BTN_RETRY, g_App.hInstance, NULL
                );
            } else {
                ShowWindow(btnRetry, SW_SHOW);
                EnableWindow(btnRetry, TRUE);
            }
            
            SetWindowTextW(GetDlgItem(hwnd, IDC_BTN_CANCEL), L"ปิด (Close)");
            return 0;
        }

        case WM_PAINT: {
            PAINTSTRUCT ps;
            HDC hdc = BeginPaint(hwnd, &ps);

            // Double Buffering
            RECT rcClient;
            GetClientRect(hwnd, &rcClient);
            HDC memDC = CreateCompatibleDC(hdc);
            HBITMAP memBM = CreateCompatibleBitmap(hdc, rcClient.right, rcClient.bottom);
            HBITMAP oldBM = (HBITMAP)SelectObject(memDC, memBM);

            // 1. Background Fill
            HBRUSH brBg = CreateSolidBrush(COLOR_BG_PRIMARY);
            FillRect(memDC, &rcClient, brBg);
            DeleteObject(brBg);

            // 2. Top Header Card
            RECT rcHeader = { 0, 0, rcClient.right, 80 };
            HBRUSH brPanel = CreateSolidBrush(COLOR_BG_PANEL);
            FillRect(memDC, &rcHeader, brPanel);
            DeleteObject(brPanel);

            // Header Border Line
            HPEN penBorder = CreatePen(PS_SOLID, 1, COLOR_BORDER);
            HPEN oldPen = (HPEN)SelectObject(memDC, penBorder);
            MoveToEx(memDC, 0, 80, NULL);
            LineTo(memDC, rcClient.right, 80);
            SelectObject(memDC, oldPen);
            DeleteObject(penBorder);

            // 3. Draw App Icon
            HICON hAppIcon = (HICON)LoadImageW(g_App.hInstance, MAKEINTRESOURCEW(1), IMAGE_ICON, 44, 44, LR_DEFAULTCOLOR);
            if (hAppIcon) {
                DrawIconEx(memDC, 24, 18, hAppIcon, 44, 44, 0, NULL, DI_NORMAL);
                DestroyIcon(hAppIcon);
            }

            // 4. Header Titles
            SetBkMode(memDC, TRANSPARENT);
            HFONT fontTitle = CreateFontW(22, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
            HFONT fontSub = CreateFontW(14, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
            HFONT fontStage = CreateFontW(17, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
            HFONT fontDetail = CreateFontW(13, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");

            HFONT oldFont = (HFONT)SelectObject(memDC, fontTitle);
            SetTextColor(memDC, COLOR_TEXT_PRIMARY);
            RECT rcTitle = { 80, 16, rcClient.right - 20, 42 };
            DrawTextW(memDC, L"Voicer Studio", -1, &rcTitle, DT_SINGLELINE | DT_LEFT);

            SelectObject(memDC, fontSub);
            SetTextColor(memDC, COLOR_TEXT_MUTED);
            RECT rcSub = { 80, 42, rcClient.right - 20, 68 };
            DrawTextW(memDC, L"Standalone Desktop Setup & Environment Bootstrapper", -1, &rcSub, DT_SINGLELINE | DT_LEFT);

            // 5. Stage Title & Percentage
            SelectObject(memDC, fontStage);
            if (g_App.isError) {
                SetTextColor(memDC, COLOR_STATUS_ERR);
                RECT rcStage = { 30, 110, rcClient.right - 30, 138 };
                DrawTextW(memDC, L"การติดตั้งพบข้อผิดพลาด", -1, &rcStage, DT_SINGLELINE | DT_LEFT);
            } else {
                SetTextColor(memDC, COLOR_TEXT_PRIMARY);
                RECT rcStage = { 30, 110, rcClient.right - 100, 138 };
                DrawTextW(memDC, g_App.stageTitle[0] ? g_App.stageTitle : L"กำลังเริ่มต้นระบบ...", -1, &rcStage, DT_SINGLELINE | DT_LEFT);

                wchar_t pctText[32];
                wsprintfW(pctText, L"%d%%", g_App.progressPct);
                RECT rcPct = { rcClient.right - 90, 110, rcClient.right - 30, 138 };
                DrawTextW(memDC, pctText, -1, &rcPct, DT_SINGLELINE | DT_RIGHT);
            }

            // 6. Progress Bar Track & Indicator
            int pbX = 30;
            int pbY = 150;
            int pbW = rcClient.right - 60;
            int pbH = 12;

            RECT rcTrack = { pbX, pbY, pbX + pbW, pbY + pbH };
            HBRUSH brTrack = CreateSolidBrush(COLOR_BG_INPUT);
            FillRect(memDC, &rcTrack, brTrack);
            DeleteObject(brTrack);

            HPEN penPb = CreatePen(PS_SOLID, 1, COLOR_BORDER);
            SelectObject(memDC, penPb);
            Rectangle(memDC, pbX, pbY, pbX + pbW, pbY + pbH);
            DeleteObject(penPb);

            if (!g_App.isError && g_App.progressPct > 0) {
                int fillW = ((pbW - 2) * g_App.progressPct) / 100;
                if (fillW > 0) {
                    RECT rcFill = { pbX + 1, pbY + 1, pbX + 1 + fillW, pbY + pbH - 1 };
                    HBRUSH brFill = CreateSolidBrush(COLOR_ACCENT_BLUE);
                    FillRect(memDC, &rcFill, brFill);
                    DeleteObject(brFill);
                }
            }

            // 7. Status Detail Log / Error Message
            SelectObject(memDC, fontDetail);
            if (g_App.isError) {
                SetTextColor(memDC, COLOR_STATUS_ERR);
                RECT rcErr = { 30, 180, rcClient.right - 30, 270 };
                DrawTextW(memDC, g_App.errorMsg, -1, &rcErr, DT_WORDBREAK | DT_LEFT);
            } else {
                SetTextColor(memDC, COLOR_TEXT_DIM);
                RECT rcDetail = { 30, 180, rcClient.right - 30, 270 };
                DrawTextW(memDC, g_App.statusDetail, -1, &rcDetail, DT_WORDBREAK | DT_LEFT);
            }

            // Cleanup GDI objects
            SelectObject(memDC, oldFont);
            DeleteObject(fontTitle);
            DeleteObject(fontSub);
            DeleteObject(fontStage);
            DeleteObject(fontDetail);

            BitBlt(hdc, 0, 0, rcClient.right, rcClient.bottom, memDC, 0, 0, SRCCOPY);
            SelectObject(memDC, oldBM);
            DeleteObject(memBM);
            DeleteDC(memDC);

            EndPaint(hwnd, &ps);
            return 0;
        }

        case WM_DESTROY: {
            PostQuitMessage(0);
            return 0;
        }
    }
    return DefWindowProcW(hwnd, uMsg, wParam, lParam);
}

// ── Application Entry Point ───────────────────────────────────────────────────
int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, PWSTR pCmdLine, int nCmdShow) {
    g_App.hInstance = hInstance;
    g_App.pCmdLine = pCmdLine;

    // Get executable directory
    if (!GetModuleFileNameW(NULL, g_App.exeDir, MAX_PATH)) return 1;
    wchar_t *lastSlash = wcsrchr(g_App.exeDir, L'\\');
    if (lastSlash) *lastSlash = L'\0';

    SetCurrentDirectoryW(g_App.exeDir);
    EnsureSettingsExist(g_App.exeDir);

    // ── 1. FAST CHECK: If runtime is already functional, launch immediately ────
    if (CheckEnvironmentReady(g_App.exeDir, g_App.runnerExe, g_App.mainScript)) {
        return LaunchVoicerStudio(g_App.exeDir, g_App.runnerExe, g_App.mainScript, pCmdLine);
    }

    // ── 2. ZERO-CONFIG SETUP GUI: First run or missing components ─────────────
    INITCOMMONCONTROLSEX icex;
    icex.dwSize = sizeof(INITCOMMONCONTROLSEX);
    icex.dwICC = ICC_PROGRESS_CLASS | ICC_STANDARD_CLASSES;
    InitCommonControlsEx(&icex);

    WNDCLASSEXW wc;
    ZeroMemory(&wc, sizeof(wc));
    wc.cbSize = sizeof(WNDCLASSEXW);
    wc.style = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc = SetupWndProc;
    wc.hInstance = hInstance;
    wc.hIcon = (HICON)LoadImageW(hInstance, MAKEINTRESOURCEW(1), IMAGE_ICON, 0, 0, LR_DEFAULTSIZE | LR_SHARED);
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)GetStockObject(BLACK_BRUSH);
    wc.lpszClassName = L"VoicerStudioSetupClass";
    RegisterClassExW(&wc);

    // Center setup window on screen
    int scrW = GetSystemMetrics(SM_CXSCREEN);
    int scrH = GetSystemMetrics(SM_CYSCREEN);
    int posX = (scrW - WIN_WIDTH) / 2;
    int posY = (scrH - WIN_HEIGHT) / 2;

    g_App.hwnd = CreateWindowExW(
        WS_EX_APPWINDOW,
        L"VoicerStudioSetupClass",
        L"Voicer Studio Setup",
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_VISIBLE,
        posX, posY, WIN_WIDTH, WIN_HEIGHT,
        NULL, NULL, hInstance, NULL
    );

    if (!g_App.hwnd) return 1;

    // Start background setup worker thread
    g_App.hWorkerThread = (HANDLE)_beginthreadex(NULL, 0, SetupWorkerThread, NULL, 0, NULL);

    // Standard Win32 message loop
    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    if (g_App.hWorkerThread) {
        CloseHandle(g_App.hWorkerThread);
    }

    return 0;
}
