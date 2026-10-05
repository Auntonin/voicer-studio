/*
 * scripts/launcher.c
 * ==================
 * Native Windows Zero-Config GUI Bootstrapper & Launcher for Voicer Studio.
 * 
 * Features:
 * 1. 100% Native Windows GUI (Subsystem: Windows, zero console window).
 * 2. 100% Non-Admin / User Space: Self-contained in ./.venv or ./runtime/python and ./runtime/bin without UAC elevation.
 * 3. Modern Adobe Studio Dark Setup & Splash GUI with progress bar, percentage, and live activity logs.
 * 4. Universal Multi-Environment Setup Workflow:
 *    - Auto-detect existing .venv, system Python (3.10-3.13), or standalone Embeddable Python fallback.
 *    - Standalone static FFmpeg & FFprobe setup with local PATH discovery and mirror fallback.
 *    - Hardware-aware PyTorch setup (NVIDIA CUDA 12.1 vs CPU fallback).
 *    - Pre-upgraded pip, setuptools, and wheel for error-free binary wheel resolution.
 *    - Automated pip requirements installation with timeout resilience and staged fallback.
 *    - Real-time install.log file logging and precise error diagnostics on failure.
 *    - Dedicated "View Log" button on failure to open install.log directly.
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

// UI Theme Palette Constants (Adobe / Dark Studio)
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

// Window & Control IDs
#define WM_APP_PROGRESS     (WM_APP + 101)
#define WM_APP_STATUS       (WM_APP + 102)
#define WM_APP_DONE         (WM_APP + 103)
#define WM_APP_ERROR        (WM_APP + 104)

#define IDC_BTN_CANCEL      2001
#define IDC_BTN_RETRY       2002
#define IDC_BTN_LOG         2003

#define WIN_WIDTH           580
#define WIN_HEIGHT          360

// URLs for Standalone Non-Admin Setup
#define URL_PYTHON_EMBED    L"https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
#define URL_GET_PIP         L"https://bootstrap.pypa.io/get-pip.py"
#define URL_FFMPEG_ZIP      L"https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
#define URL_FFMPEG_GYAN     L"https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

// Global State
typedef struct {
    HWND hwnd;
    HINSTANCE hInstance;
    wchar_t exeDir[MAX_PATH];
    wchar_t runnerExe[MAX_PATH];
    wchar_t mainScript[MAX_PATH];
    wchar_t installLogPath[MAX_PATH];
    PWSTR pCmdLine;
    
    // UI dynamic states
    int progressPct;
    wchar_t stageTitle[256];
    wchar_t statusDetail[512];
    wchar_t currentPackage[256];
    bool isError;
    wchar_t errorMsg[1024];
    wchar_t lastErrorDetail[1024];
    bool isDone;
    bool shouldCancel;
    bool hasNvidiaGpu;
    
    HANDLE hWorkerThread;
} AppState;

static AppState g_App;

// Helper File / Directory Utilities
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

static void LogInstallA(const char *msg) {
    if (!g_App.installLogPath[0]) return;
    FILE *fp = _wfopen(g_App.installLogPath, L"a");
    if (fp) {
        SYSTEMTIME st;
        GetLocalTime(&st);
        fprintf(fp, "[%04d-%02d-%02d %02d:%02d:%02d] %s\n",
                st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond, msg);
        fflush(fp);
        fclose(fp);
    }
}

static void LogInstallW(const wchar_t *msg) {
    char buf[2048];
    WideCharToMultiByte(CP_UTF8, 0, msg, -1, buf, sizeof(buf), NULL, NULL);
    LogInstallA(buf);
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

// Hardware & GPU Detection
static bool DetectNvidiaGpu(void) {
    if (GetFileAttributesW(L"C:\\Windows\\System32\\nvcuda.dll") != INVALID_FILE_ATTRIBUTES) return true;
    if (GetFileAttributesW(L"C:\\Windows\\System32\\nvidia-smi.exe") != INVALID_FILE_ATTRIBUTES) return true;
    wchar_t found[MAX_PATH];
    if (SearchPathW(NULL, L"nvidia-smi.exe", NULL, MAX_PATH, found, NULL) > 0) return true;
    return false;
}

// Fast Environment Readiness Check
static bool CheckEnvironmentReady(const wchar_t *exeDir, wchar_t *outRunner, wchar_t *outMainPy) {
    wsprintfW(outMainPy, L"%s\\main.py", exeDir);
    if (!FileExists(outMainPy)) return false;

    // 1. Primary: Self-contained runtime (./runtime/python)
    wchar_t runtimePythonw[MAX_PATH];
    wchar_t runtimePython[MAX_PATH];
    wchar_t runtimePySide[MAX_PATH];

    wsprintfW(runtimePythonw, L"%s\\runtime\\python\\pythonw.exe", exeDir);
    wsprintfW(runtimePython, L"%s\\runtime\\python\\python.exe", exeDir);
    wsprintfW(runtimePySide, L"%s\\runtime\\python\\Lib\\site-packages\\PySide6", exeDir);

    if ((FileExists(runtimePythonw) || FileExists(runtimePython)) && DirectoryExists(runtimePySide)) {
        wcscpy(outRunner, FileExists(runtimePythonw) ? runtimePythonw : runtimePython);
        return true;
    }

    // 2. Secondary: Virtual environment (./.venv)
    wchar_t venvHost[MAX_PATH];
    wchar_t venvPythonw[MAX_PATH];
    wchar_t venvPython[MAX_PATH];
    wchar_t venvPySide[MAX_PATH];

    wsprintfW(venvHost, L"%s\\.venv\\Scripts\\VoicerStudio.exe", exeDir);
    wsprintfW(venvPythonw, L"%s\\.venv\\Scripts\\pythonw.exe", exeDir);
    wsprintfW(venvPython, L"%s\\.venv\\Scripts\\python.exe", exeDir);
    wsprintfW(venvPySide, L"%s\\.venv\\Lib\\site-packages\\PySide6", exeDir);

    if (FileExists(venvHost) && DirectoryExists(venvPySide)) {
        wcscpy(outRunner, venvHost);
        return true;
    } else if (FileExists(venvPythonw) && DirectoryExists(venvPySide)) {
        wcscpy(outRunner, venvPythonw);
        return true;
    } else if (FileExists(venvPython) && DirectoryExists(venvPySide)) {
        wcscpy(outRunner, venvPython);
        return true;
    }

    return false;
}

// Dynamic Environment Injected Application Launch
static int LaunchVoicerStudio(const wchar_t *exeDir, const wchar_t *runner, const wchar_t *mainScript, PWSTR pCmdLine) {
    // Setup Process PATH to include local runtime tools
    wchar_t oldPath[32768] = {0};
    wchar_t newPath[32768] = {0};
    GetEnvironmentVariableW(L"PATH", oldPath, 32768);

    wsprintfW(newPath, L"%s\\.venv\\Scripts;%s\\runtime\\bin;%s\\runtime\\python;%s\\runtime\\python\\Scripts;%s\\tools\\ffmpeg\\bin;%s",
              exeDir, exeDir, exeDir, exeDir, exeDir, oldPath);
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
        MessageBoxW(NULL, errMsg, L"Voicer Studio Launch Error", MB_OK | MB_ICONERROR);
        return 1;
    }

    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    return 0;
}

// Silent Subprocess Execution with Real-time Logging and Error Capture
typedef void (*LineOutputCallback)(const char *line, void *userData);

static bool RunCommandSilent(const wchar_t *exeDir, const wchar_t *cmdLine, LineOutputCallback cb, void *userData, DWORD timeoutMs) {
    LogInstallW(L"--------------------------------------------------");
    LogInstallW(L"[EXEC]");
    LogInstallW(cmdLine);

    SECURITY_ATTRIBUTES sa;
    sa.nLength = sizeof(SECURITY_ATTRIBUTES);
    sa.bInheritHandle = TRUE;
    sa.lpSecurityDescriptor = NULL;

    HANDLE hReadPipe = NULL, hWritePipe = NULL;
    if (!CreatePipe(&hReadPipe, &hWritePipe, &sa, 0)) {
        LogInstallW(L"[ERROR] Failed to create communication pipe");
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
        LogInstallW(L"[ERROR] CreateProcessW failed to start executable");
        return false;
    }

    char buffer[1024];
    DWORD bytesRead = 0;
    char lineBuffer[1024] = {0};
    int linePos = 0;

    FILE *fpLog = _wfopen(g_App.installLogPath, L"a");

    while (ReadFile(hReadPipe, buffer, sizeof(buffer) - 1, &bytesRead, NULL) && bytesRead > 0) {
        if (g_App.shouldCancel) break;

        buffer[bytesRead] = '\0';
        for (DWORD i = 0; i < bytesRead; i++) {
            char c = buffer[i];
            if (c == '\r' || c == '\n') {
                if (linePos > 0) {
                    lineBuffer[linePos] = '\0';
                    if (fpLog) {
                        fprintf(fpLog, "%s\n", lineBuffer);
                        fflush(fpLog);
                    }
                    if (strstr(lineBuffer, "ERROR:") || strstr(lineBuffer, "Error:") ||
                        strstr(lineBuffer, "Exception:") || strstr(lineBuffer, "ReadTimeoutError") ||
                        strstr(lineBuffer, "timed out") || strstr(lineBuffer, "No space left") ||
                        strstr(lineBuffer, "PermissionError") || strstr(lineBuffer, "Access is denied") ||
                        strstr(lineBuffer, "Microsoft Visual C++")) {
                        MultiByteToWideChar(CP_UTF8, 0, lineBuffer, -1, g_App.lastErrorDetail, 1024);
                    }
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
        if (fpLog) {
            fprintf(fpLog, "%s\n", lineBuffer);
            fflush(fpLog);
        }
        if (strstr(lineBuffer, "ERROR:") || strstr(lineBuffer, "Error:") ||
            strstr(lineBuffer, "Exception:") || strstr(lineBuffer, "ReadTimeoutError") ||
            strstr(lineBuffer, "timed out") || strstr(lineBuffer, "No space left") ||
            strstr(lineBuffer, "PermissionError") || strstr(lineBuffer, "Access is denied") ||
            strstr(lineBuffer, "Microsoft Visual C++")) {
            MultiByteToWideChar(CP_UTF8, 0, lineBuffer, -1, g_App.lastErrorDetail, 1024);
        }
        if (cb) cb(lineBuffer, userData);
    }

    if (fpLog) fclose(fpLog);

    CloseHandle(hReadPipe);
    WaitForSingleObject(pi.hProcess, timeoutMs);

    DWORD exitCode = 1;
    GetExitCodeProcess(pi.hProcess, &exitCode);
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);

    wchar_t exitMsg[64];
    wsprintfW(exitMsg, L"[EXIT CODE: %lu]", exitCode);
    LogInstallW(exitMsg);

    return (exitCode == 0);
}

// System Python Discovery on Windows 10
static bool FindWorkingSystemPython(const wchar_t *exeDir, wchar_t *outPyPath) {
    wchar_t candidate[MAX_PATH] = {0};

    // 1. Check PATH python.exe (excluding WindowsApps redirector)
    if (SearchPathW(NULL, L"python.exe", NULL, MAX_PATH, candidate, NULL) > 0) {
        if (wcsstr(candidate, L"WindowsApps") == NULL) {
            wchar_t testCmd[MAX_PATH + 128];
            wsprintfW(testCmd, L"\"%s\" -c \"import sys; sys.exit(0 if sys.version_info >= (3, 10) and sys.maxsize > 2**32 else 1)\"", candidate);
            if (RunCommandSilent(exeDir, testCmd, NULL, NULL, 6000)) {
                lstrcpyW(outPyPath, candidate);
                return true;
            }
        }
    }

    // 2. Check py.exe launcher
    wchar_t pyLauncher[MAX_PATH];
    if (SearchPathW(NULL, L"py.exe", NULL, MAX_PATH, pyLauncher, NULL) > 0) {
        const wchar_t *versions[] = { L"-3.12", L"-3.11", L"-3.10", L"-3" };
        for (int i = 0; i < 4; i++) {
            wchar_t testCmd[MAX_PATH + 128];
            wsprintfW(testCmd, L"\"%s\" %s -c \"import sys; sys.exit(0 if sys.version_info >= (3, 10) and sys.maxsize > 2**32 else 1)\"", pyLauncher, versions[i]);
            if (RunCommandSilent(exeDir, testCmd, NULL, NULL, 6000)) {
                wsprintfW(outPyPath, L"\"%s\" %s", pyLauncher, versions[i]);
                return true;
            }
        }
    }

    // 3. Check LocalAppData python directories
    wchar_t localAppData[MAX_PATH] = {0};
    if (GetEnvironmentVariableW(L"LOCALAPPDATA", localAppData, MAX_PATH) > 0) {
        const wchar_t *relPaths[] = {
            L"\\Programs\\Python\\Python312\\python.exe",
            L"\\Programs\\Python\\Python311\\python.exe",
            L"\\Programs\\Python\\Python310\\python.exe"
        };
        for (int i = 0; i < 3; i++) {
            wchar_t fullPath[MAX_PATH];
            wsprintfW(fullPath, L"%s%s", localAppData, relPaths[i]);
            if (FileExists(fullPath)) {
                wchar_t testCmd[MAX_PATH + 128];
                wsprintfW(testCmd, L"\"%s\" -c \"import sys; sys.exit(0 if sys.version_info >= (3, 10) and sys.maxsize > 2**32 else 1)\"", fullPath);
                if (RunCommandSilent(exeDir, testCmd, NULL, NULL, 6000)) {
                    lstrcpyW(outPyPath, fullPath);
                    return true;
                }
            }
        }
    }

    // 4. Check Root C:\Python paths
    const wchar_t *rootPaths[] = {
        L"C:\\Python312\\python.exe",
        L"C:\\Python311\\python.exe",
        L"C:\\Python310\\python.exe"
    };
    for (int i = 0; i < 3; i++) {
        if (FileExists(rootPaths[i])) {
            wchar_t testCmd[MAX_PATH + 128];
            wsprintfW(testCmd, L"\"%s\" -c \"import sys; sys.exit(0 if sys.version_info >= (3, 10) and sys.maxsize > 2**32 else 1)\"", rootPaths[i]);
            if (RunCommandSilent(exeDir, testCmd, NULL, NULL, 6000)) {
                lstrcpyW(outPyPath, rootPaths[i]);
                return true;
            }
        }
    }

    return false;
}

// Native WinINet HTTPS Downloader
typedef void (*DownloadProgressCallback)(int percent, uint64_t downloadedBytes, uint64_t totalBytes, void *userData);

static bool DownloadFileWinINet(const wchar_t *url, const wchar_t *destFile, DownloadProgressCallback cb, void *userData) {
    HINTERNET hInternet = InternetOpenW(L"VoicerStudio-Bootstrapper/1.1", INTERNET_OPEN_TYPE_PRECONFIG, NULL, NULL, 0);
    if (!hInternet) return false;

    DWORD flags = INTERNET_FLAG_RELOAD | INTERNET_FLAG_NO_CACHE_WRITE | INTERNET_FLAG_SECURE | INTERNET_FLAG_IGNORE_CERT_CN_INVALID | INTERNET_FLAG_IGNORE_CERT_DATE_INVALID;
    HINTERNET hUrl = InternetOpenUrlW(hInternet, url, NULL, 0, flags, 0);
    if (!hUrl) {
        hUrl = InternetOpenUrlW(hInternet, url, NULL, 0, INTERNET_FLAG_RELOAD | INTERNET_FLAG_NO_CACHE_WRITE, 0);
    }

    if (!hUrl) {
        InternetCloseHandle(hInternet);
        return false;
    }

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

// Native ZIP Extraction Utility
static bool ExtractZip(const wchar_t *exeDir, const wchar_t *zipPath, const wchar_t *destDir) {
    CreateDirRecursive(destDir);

    // 1. Try Windows built-in tar.exe (fastest, native on Windows 10/11)
    wchar_t tarCmd[2048];
    wsprintfW(tarCmd, L"tar.exe -xf \"%s\" -C \"%s\"", zipPath, destDir);
    if (RunCommandSilent(exeDir, tarCmd, NULL, NULL, 60000)) {
        return true;
    }

    // 2. Fallback: PowerShell Expand-Archive
    wchar_t psCmd[4096];
    wsprintfW(psCmd, L"powershell.exe -NoProfile -ExecutionPolicy Bypass -Command \"Expand-Archive -LiteralPath '%s' -DestinationPath '%s' -Force\"", zipPath, destDir);
    return RunCommandSilent(exeDir, psCmd, NULL, NULL, 120000);
}

// Patch python311._pth Cleanly for Embeddable Runtime
static bool PatchPythonPth(const wchar_t *pythonDir) {
    WIN32_FIND_DATAW fd;
    wchar_t pattern[MAX_PATH];
    wsprintfW(pattern, L"%s\\python*._pth", pythonDir);

    HANDLE hFind = FindFirstFileW(pattern, &fd);
    if (hFind == INVALID_HANDLE_VALUE) return false;

    wchar_t pthPath[MAX_PATH];
    wsprintfW(pthPath, L"%s\\%s", pythonDir, fd.cFileName);
    FindClose(hFind);

    FILE *fp = _wfopen(pthPath, L"w");
    if (!fp) return false;

    const char *pthConfig =
        "python311.zip\r\n"
        ".\r\n"
        "..\r\n"
        ".\\Lib\r\n"
        ".\\Lib\\site-packages\r\n"
        "import site\r\n";
    fwrite(pthConfig, 1, strlen(pthConfig), fp);
    fclose(fp);

    wchar_t libDir[MAX_PATH];
    wsprintfW(libDir, L"%s\\Lib", pythonDir);
    CreateDirRecursive(libDir);

    wchar_t sitePkg[MAX_PATH];
    wsprintfW(sitePkg, L"%s\\Lib\\site-packages", pythonDir);
    CreateDirRecursive(sitePkg);

    return true;
}

// UI Status & Progress Event Notifiers
static void NotifyProgress(int pct, const wchar_t *stage, const wchar_t *detail) {
    g_App.progressPct = max(0, min(100, pct));
    if (stage) lstrcpynW(g_App.stageTitle, stage, 256);
    if (detail) lstrcpynW(g_App.statusDetail, detail, 512);
    PostMessageW(g_App.hwnd, WM_APP_PROGRESS, (WPARAM)g_App.progressPct, 0);
}

static void NotifyErrorWithContext(const wchar_t *stage, const wchar_t *fallbackMsg) {
    g_App.isError = true;
    wchar_t formatted[1024] = {0};

    if (g_App.lastErrorDetail[0] != L'\0') {
        if (wcsstr(g_App.lastErrorDetail, L"ReadTimeoutError") || wcsstr(g_App.lastErrorDetail, L"timed out")) {
            wsprintfW(formatted,
                L"%s\n\n"
                L"สาเหตุ: การเชื่อมต่อเครือข่ายหมดเวลา (Network Timeout)\n"
                L"รายละเอียด: %s\n\n"
                L"คำแนะนำ: กรุณาตรวจสอบอินเทอร์เน็ตแล้วกด 'ลองใหม่' หรือกด 'เปิดดู Log'",
                stage, g_App.lastErrorDetail);
        } else if (wcsstr(g_App.lastErrorDetail, L"No space left") || wcsstr(g_App.lastErrorDetail, L"disk full")) {
            wsprintfW(formatted,
                L"%s\n\n"
                L"สาเหตุ: พื้นที่บนดิสก์ไม่เพียงพอสำหรับการติดตั้ง\n\n"
                L"คำแนะนำ: กรุณาเพิ่มพื้นที่ว่างในไดรฟ์แล้วกดปุ่ม 'ลองใหม่'",
                stage);
        } else if (wcsstr(g_App.lastErrorDetail, L"Access is denied") || wcsstr(g_App.lastErrorDetail, L"PermissionError")) {
            wsprintfW(formatted,
                L"%s\n\n"
                L"สาเหตุ: สิทธิ์การเขียนไฟล์ถูกปฏิเสธ (Permission Denied)\n\n"
                L"คำแนะนำ: ตรวจสอบสิทธิ์ของโฟลเดอร์ หรือย้ายโปรเจกต์ไปยังโฟลเดอร์ผู้ใช้",
                stage);
        } else {
            wsprintfW(formatted,
                L"%s\n\n"
                L"ข้อผิดพลาด: %s\n\n"
                L"คำแนะนำ: สามารถกดปุ่ม 'เปิดดู Log' เพื่อดูสาเหตุฉบับเต็ม หรือกด 'ลองใหม่'",
                stage, g_App.lastErrorDetail);
        }
    } else if (g_App.currentPackage[0] != L'\0') {
        wsprintfW(formatted,
            L"%s\n\n"
            L"แพ็กเกจที่พบปัญหา: %s\n\n"
            L"คำแนะนำ: กรุณาตรวจสอบอินเทอร์เน็ต แล้วกด 'ลองใหม่' หรือกด 'เปิดดู Log'",
            stage, g_App.currentPackage);
    } else {
        wsprintfW(formatted,
            L"%s\n\n"
            L"%s\n\n"
            L"คำแนะนำ: กดปุ่ม 'เปิดดู Log' เพื่อดูรายละเอียดข้อผิดพลาด",
            stage, fallbackMsg ? fallbackMsg : L"การติดตั้งไม่สำเร็จ");
    }

    lstrcpynW(g_App.errorMsg, formatted, 1024);
    LogInstallW(L"[SETUP ERROR ENCOUNTERED]");
    LogInstallW(g_App.errorMsg);
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

    // Track collecting / installing package name
    if (wcsstr(wLine, L"Collecting ") != NULL) {
        lstrcpynW(g_App.currentPackage, wLine + 11, 256);
        wchar_t *paren = wcschr(g_App.currentPackage, L'(');
        if (paren) *paren = L'\0';
        wchar_t *space = wcschr(g_App.currentPackage, L' ');
        if (space) *space = L'\0';
    }

    // Filter noise and update UI detail
    if (wcsstr(wLine, L"Downloading") || wcsstr(wLine, L"Installing") || wcsstr(wLine, L"Collecting")) {
        NotifyProgress(g_App.progressPct, NULL, wLine);
    }
}

// Background Setup Worker Thread (Universal Multi-Environment Execution)
static unsigned __stdcall SetupWorkerThread(void *arg) {
    wchar_t *exeDir = g_App.exeDir;
    wchar_t runtimeDir[MAX_PATH];
    wchar_t pythonDir[MAX_PATH];
    wchar_t binDir[MAX_PATH];
    wchar_t downloadsDir[MAX_PATH];
    wchar_t venvDir[MAX_PATH];

    wsprintfW(runtimeDir, L"%s\\runtime", exeDir);
    wsprintfW(pythonDir, L"%s\\runtime\\python", exeDir);
    wsprintfW(binDir, L"%s\\runtime\\bin", exeDir);
    wsprintfW(downloadsDir, L"%s\\runtime\\downloads", exeDir);
    wsprintfW(venvDir, L"%s\\.venv", exeDir);

    CreateDirRecursive(runtimeDir);
    CreateDirRecursive(binDir);
    CreateDirRecursive(downloadsDir);

    LogInstallW(L"==================================================");
    LogInstallW(L"Voicer Studio Setup Started");
    LogInstallW(exeDir);

    g_App.hasNvidiaGpu = DetectNvidiaGpu();
    if (g_App.hasNvidiaGpu) {
        LogInstallW(L"GPU Status: NVIDIA GPU with CUDA Detected");
    } else {
        LogInstallW(L"GPU Status: No NVIDIA GPU detected (CPU mode)");
    }

    // ── STEP 1: Determine Python Environment (Universal Multi-Format Support) ───
    wchar_t targetPython[MAX_PATH] = {0};
    wchar_t venvPython[MAX_PATH];
    wchar_t embedPython[MAX_PATH];
    wsprintfW(venvPython, L"%s\\Scripts\\python.exe", venvDir);
    wsprintfW(embedPython, L"%s\\python.exe", pythonDir);

    // Case 1A: Existing .venv in project
    if (FileExists(venvPython)) {
        LogInstallW(L"Using existing virtual environment (.venv)");
        lstrcpyW(targetPython, venvPython);
    }
    // Case 1B: Existing runtime/python embeddable
    else if (FileExists(embedPython)) {
        LogInstallW(L"Using existing runtime/python environment");
        lstrcpyW(targetPython, embedPython);
    }
    // Case 1C: System Python detected on Windows 10 -> Create .venv
    else {
        wchar_t sysPy[MAX_PATH];
        if (FindWorkingSystemPython(exeDir, sysPy)) {
            NotifyProgress(8, L"กำลังเตรียม Virtual Environment...", L"พบ Python ในระบบ กำลังสร้าง .venv สำหรับ Voicer Studio...");
            LogInstallW(L"Found system Python. Creating virtual environment (.venv)...");
            LogInstallW(sysPy);

            wchar_t cmdVenv[MAX_PATH * 2];
            wsprintfW(cmdVenv, L"%s -m venv \"%s\"", sysPy, venvDir);
            if (RunCommandSilent(exeDir, cmdVenv, NULL, NULL, 60000) && FileExists(venvPython)) {
                LogInstallW(L"Successfully initialized .venv from system Python");
                lstrcpyW(targetPython, venvPython);
            } else {
                LogInstallW(L"Failed to create .venv from system Python, falling back to standalone embeddable Python");
            }
        }

        // Case 1D: Standalone Embeddable Python fallback (Zero-install, Non-Admin)
        if (targetPython[0] == L'\0') {
            CreateDirRecursive(pythonDir);
            NotifyProgress(10, L"กำลังเตรียม Python Environment...", L"กำลังดาวน์โหลด Python 3.11 Embeddable (Non-Admin Runtime)...");
            LogInstallW(L"Downloading standalone Python 3.11 embeddable package...");

            wchar_t zipPython[MAX_PATH];
            wsprintfW(zipPython, L"%s\\python-embed.zip", downloadsDir);

            if (!DownloadFileWinINet(URL_PYTHON_EMBED, zipPython, OnDownloadProgress, (void*)L"ดาวน์โหลด Python 3.11")) {
                NotifyErrorWithContext(L"ไม่สามารถดาวน์โหลด Python Embeddable Package ได้", L"กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ต");
                return 1;
            }

            NotifyProgress(20, L"กำลังเตรียม Python Environment...", L"กำลังแตกไฟล์ Python Runtime เข้าสู่โฟลเดอร์ runtime/python...");
            LogInstallW(L"Extracting Python embeddable...");
            if (!ExtractZip(exeDir, zipPython, pythonDir)) {
                NotifyErrorWithContext(L"ไม่สามารถแตกไฟล์ Python Package ได้", L"กรุณาตรวจสอบพื้นที่ว่างในดิสก์");
                return 1;
            }
            DeleteFileW(zipPython);

            if (!PatchPythonPth(pythonDir)) {
                NotifyErrorWithContext(L"ไม่สามารถปรับแต่งไฟล์ python311._pth ได้", L"เกิดข้อผิดพลาดในการกำหนดค่า site-packages");
                return 1;
            }

            lstrcpyW(targetPython, embedPython);
        }
    }

    // ── STEP 2: Ensure PIP & Build Tools (pip, setuptools, wheel) ───────────────
    if (wcsstr(targetPython, L"runtime\\python") != NULL) {
        wchar_t pipExe[MAX_PATH];
        wsprintfW(pipExe, L"%s\\Scripts\\pip.exe", pythonDir);
        if (!FileExists(pipExe)) {
            NotifyProgress(25, L"กำลังติดตั้งระบบจัดการแพ็กเกจ (pip)...", L"กำลังดาวน์โหลด get-pip.py...");
            LogInstallW(L"Downloading get-pip.py...");

            wchar_t getPipScript[MAX_PATH];
            wsprintfW(getPipScript, L"%s\\get-pip.py", downloadsDir);

            if (!DownloadFileWinINet(URL_GET_PIP, getPipScript, OnDownloadProgress, (void*)L"ดาวน์โหลด get-pip.py")) {
                NotifyErrorWithContext(L"ไม่สามารถดาวน์โหลด get-pip.py ได้", L"กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ต");
                return 1;
            }

            NotifyProgress(32, L"กำลังติดตั้งระบบจัดการแพ็กเกจ (pip)...", L"กำลังรัน get-pip.py (Standalone User-Space)...");
            wchar_t cmdPip[2048];
            wsprintfW(cmdPip, L"\"%s\" \"%s\" --no-warn-script-location", targetPython, getPipScript);

            if (!RunCommandSilent(exeDir, cmdPip, OnPipOutput, NULL, 180000)) {
                NotifyErrorWithContext(L"การติดตั้ง pip เบื้องต้นล้มเหลว", L"กรุณาลองใหม่อีกครั้ง");
                return 1;
            }
            DeleteFileW(getPipScript);
        }
    }

    NotifyProgress(35, L"กำลังอัปเกรดเครื่องมือแพ็กเกจ (pip, setuptools, wheel)...", L"กำลังเตรียมความพร้อมเครื่องมือติดตั้งไลบรารี...");
    LogInstallW(L"Upgrading pip, setuptools, and wheel...");
    wchar_t cmdUpTools[2048];
    wsprintfW(cmdUpTools, L"\"%s\" -m pip install --upgrade pip setuptools wheel --no-warn-script-location --no-input --prefer-binary --retries 5", targetPython);
    RunCommandSilent(exeDir, cmdUpTools, OnPipOutput, NULL, 180000);

    // ── STEP 3: Standalone Static FFmpeg & FFprobe ──────────────────────────────
    wchar_t ffmpegExe[MAX_PATH];
    wsprintfW(ffmpegExe, L"%s\\ffmpeg.exe", binDir);

    if (!FileExists(ffmpegExe)) {
        NotifyProgress(42, L"กำลังตรวจสอบระบบเสียง FFmpeg...", L"กำลังค้นหา FFmpeg ในเครื่อง...");
        wchar_t sysFfmpeg[MAX_PATH];
        bool copiedSysFfmpeg = false;

        if (SearchPathW(NULL, L"ffmpeg.exe", NULL, MAX_PATH, sysFfmpeg, NULL) > 0) {
            LogInstallW(L"Found existing FFmpeg in system PATH. Copying to runtime/bin...");
            CopyFileW(sysFfmpeg, ffmpegExe, FALSE);
            wchar_t sysFfprobe[MAX_PATH];
            if (SearchPathW(NULL, L"ffprobe.exe", NULL, MAX_PATH, sysFfprobe, NULL) > 0) {
                wchar_t binFfprobe[MAX_PATH];
                wsprintfW(binFfprobe, L"%s\\ffprobe.exe", binDir);
                CopyFileW(sysFfprobe, binFfprobe, FALSE);
            }
            copiedSysFfmpeg = true;
        }

        if (!copiedSysFfmpeg) {
            NotifyProgress(45, L"กำลังติดตั้งระบบเสียง FFmpeg...", L"กำลังดาวน์โหลด Standalone FFmpeg & FFprobe...");
            wchar_t ffmpegZip[MAX_PATH];
            wsprintfW(ffmpegZip, L"%s\\ffmpeg.zip", downloadsDir);

            bool dlOk = DownloadFileWinINet(URL_FFMPEG_ZIP, ffmpegZip, OnDownloadProgress, (void*)L"ดาวน์โหลด FFmpeg Static Build");
            if (!dlOk) {
                dlOk = DownloadFileWinINet(URL_FFMPEG_GYAN, ffmpegZip, OnDownloadProgress, (void*)L"ดาวน์โหลด FFmpeg Release Mirror");
            }

            if (dlOk) {
                NotifyProgress(52, L"กำลังติดตั้งระบบเสียง FFmpeg...", L"กำลังแตกไฟล์ FFmpeg Codecs เข้าสู่ runtime/bin...");
                wchar_t ffmpegTempDir[MAX_PATH];
                wsprintfW(ffmpegTempDir, L"%s\\ffmpeg_temp", downloadsDir);
                CreateDirRecursive(ffmpegTempDir);

                if (ExtractZip(exeDir, ffmpegZip, ffmpegTempDir)) {
                    wchar_t psCopyCmd[4096];
                    wsprintfW(psCopyCmd, L"powershell.exe -NoProfile -Command \"Get-ChildItem -Path '%s' -Recurse -Filter 'ffmpeg.exe' | Copy-Item -Destination '%s' -Force; Get-ChildItem -Path '%s' -Recurse -Filter 'ffprobe.exe' | Copy-Item -Destination '%s' -Force\"",
                              ffmpegTempDir, binDir, ffmpegTempDir, binDir);
                    RunCommandSilent(exeDir, psCopyCmd, NULL, NULL, 30000);
                }
                DeleteFileW(ffmpegZip);
            }
        }
    }

    wchar_t legacyToolsBin[MAX_PATH];
    wsprintfW(legacyToolsBin, L"%s\\tools\\ffmpeg\\bin", exeDir);
    CreateDirRecursive(legacyToolsBin);
    if (FileExists(ffmpegExe)) {
        wchar_t legacyFfmpeg[MAX_PATH];
        wsprintfW(legacyFfmpeg, L"%s\\ffmpeg.exe", legacyToolsBin);
        if (!FileExists(legacyFfmpeg)) CopyFileW(ffmpegExe, legacyFfmpeg, FALSE);
    }

    // ── STEP 4: Install PyTorch (CUDA 12.1 or CPU Fallback) ─────────────────────
    wchar_t cmdCheckTorch[1024];
    wsprintfW(cmdCheckTorch, L"\"%s\" -c \"import torch, torchaudio, torchvision\"", targetPython);
    bool torchReady = RunCommandSilent(exeDir, cmdCheckTorch, NULL, NULL, 15000);

    if (!torchReady) {
        bool torchInstalled = false;
        if (g_App.hasNvidiaGpu) {
            NotifyProgress(55, L"กำลังติดตั้ง PyTorch (NVIDIA CUDA 12.1)...", L"กำลังดาวน์โหลด PyTorch สำหรับเร่งความเร็ว GPU NVIDIA...");
            LogInstallW(L"Installing PyTorch with CUDA 12.1 support...");

            wchar_t cmdTorch[2048];
            wsprintfW(cmdTorch, L"\"%s\" -m pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu121 --prefer-binary --default-timeout 180 --retries 5 --no-warn-script-location --no-input", targetPython);
            if (RunCommandSilent(exeDir, cmdTorch, OnPipOutput, NULL, 1200000)) {
                torchInstalled = true;
            } else {
                LogInstallW(L"CUDA PyTorch installation failed. Falling back to CPU version...");
            }
        }

        if (!torchInstalled) {
            NotifyProgress(58, L"กำลังติดตั้ง PyTorch (โหมด CPU)...", L"กำลังติดตั้ง PyTorch รุ่น CPU...");
            LogInstallW(L"Installing PyTorch CPU version...");

            wchar_t cmdTorchCpu[2048];
            wsprintfW(cmdTorchCpu, L"\"%s\" -m pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cpu --prefer-binary --default-timeout 180 --retries 5 --no-warn-script-location --no-input", targetPython);
            if (!RunCommandSilent(exeDir, cmdTorchCpu, OnPipOutput, NULL, 1200000)) {
                NotifyErrorWithContext(L"การติดตั้ง PyTorch ไม่สำเร็จ", L"ไม่สามารถดาวน์โหลด PyTorch ได้ กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ต");
                return 1;
            }
        }
    } else {
        LogInstallW(L"PyTorch already installed and operational.");
    }

    // ── STEP 5: Install Requirements (requirements.txt) ────────────────────────
    wchar_t reqFile[MAX_PATH];
    wsprintfW(reqFile, L"%s\\requirements.txt", exeDir);

    if (FileExists(reqFile)) {
        NotifyProgress(72, L"กำลังติดตั้งไลบรารี AI และส่วนประกอบโปรแกรม...", L"กำลังติดตั้งไลบรารีจาก requirements.txt (PySide6, Whisper, Audio Separator)...");
        LogInstallW(L"Installing project requirements from requirements.txt...");

        const wchar_t *extraUrl = g_App.hasNvidiaGpu ? L"https://download.pytorch.org/whl/cu121" : L"https://download.pytorch.org/whl/cpu";
        wchar_t cmdInstall[4096];
        wsprintfW(cmdInstall, L"\"%s\" -m pip install -r \"%s\" --extra-index-url %s --prefer-binary --default-timeout 180 --retries 5 --no-warn-script-location --no-input",
                  targetPython, reqFile, extraUrl);

        g_App.progressPct = 78;
        if (!RunCommandSilent(exeDir, cmdInstall, OnPipOutput, NULL, 1200000)) {
            LogInstallW(L"Batch requirements install failed. Attempting staged fallback installation...");

            // Fallback Stage 1: Core GUI & Multimedia
            NotifyProgress(82, L"กำลังติดตั้งไลบรารีพื้นฐาน (Fallback Stage 1)...", L"กำลังติดตั้ง PySide6 และชุดคำสั่งเสียงหลัก...");
            wchar_t cmdStage1[2048];
            wsprintfW(cmdStage1, L"\"%s\" -m pip install PySide6>=6.7.0 ffmpeg-python>=0.2.0 pydub>=0.25.0 requests pillow soundfile librosa numpy scipy tqdm keyring --prefer-binary --retries 5 --no-warn-script-location --no-input", targetPython);
            RunCommandSilent(exeDir, cmdStage1, OnPipOutput, NULL, 600000);

            // Fallback Stage 2: AI Modules
            NotifyProgress(88, L"กำลังติดตั้งโมเดล AI (Fallback Stage 2)...", L"กำลังติดตั้ง faster-whisper, pyannote.audio, audio-separator, demucs...");
            wchar_t cmdStage2[2048];
            wsprintfW(cmdStage2, L"\"%s\" -m pip install faster-whisper>=1.0.0 pyannote.audio>=3.1.0 audio-separator>=0.20.0 demucs>=4.0.0 opencv-python>=4.8.0 --extra-index-url %s --prefer-binary --retries 5 --no-warn-script-location --no-input", targetPython, extraUrl);

            if (!RunCommandSilent(exeDir, cmdStage2, OnPipOutput, NULL, 900000)) {
                NotifyErrorWithContext(L"การติดตั้งไลบรารีจาก requirements.txt ไม่สมบูรณ์", L"กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ต");
                return 1;
            }
        }
    }

    // ── STEP 6: Finalization ──────────────────────────────────────────────────
    EnsureSettingsExist(exeDir);
    NotifyProgress(100, L"การติดตั้งเสร็จสมบูรณ์!", L"กำลังเริ่มโปรแกรม Voicer Studio...");
    LogInstallW(L"Voicer Studio installation finished successfully!");
    Sleep(400);

    NotifyDone();
    return 0;
}

// Native Win32 Custom GUI Rendering & Window Procedure
static LRESULT CALLBACK SetupWndProc(HWND hwnd, UINT uMsg, WPARAM wParam, LPARAM lParam) {
    switch (uMsg) {
        case WM_CREATE: {
            BOOL darkMode = TRUE;
            DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, &darkMode, sizeof(darkMode));

            // Log Button (Hidden initially)
            CreateWindowW(
                L"BUTTON", L"เปิดดู Log (View Log)",
                WS_CHILD | BS_PUSHBUTTON | BS_FLAT,
                WIN_WIDTH - 420, WIN_HEIGHT - 60, 140, 32,
                hwnd, (HMENU)IDC_BTN_LOG, g_App.hInstance, NULL
            );

            // Retry Button (Hidden initially)
            CreateWindowW(
                L"BUTTON", L"ลองใหม่ (Retry)",
                WS_CHILD | BS_PUSHBUTTON | BS_FLAT,
                WIN_WIDTH - 270, WIN_HEIGHT - 60, 120, 32,
                hwnd, (HMENU)IDC_BTN_RETRY, g_App.hInstance, NULL
            );

            // Cancel / Close Button
            CreateWindowW(
                L"BUTTON", L"ยกเลิก (Cancel)",
                WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON | BS_FLAT,
                WIN_WIDTH - 140, WIN_HEIGHT - 60, 120, 32,
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
                g_App.lastErrorDetail[0] = L'\0';
                ShowWindow(GetDlgItem(hwnd, IDC_BTN_RETRY), SW_HIDE);
                ShowWindow(GetDlgItem(hwnd, IDC_BTN_LOG), SW_HIDE);
                SetWindowTextW(GetDlgItem(hwnd, IDC_BTN_CANCEL), L"ยกเลิก (Cancel)");
                InvalidateRect(hwnd, NULL, FALSE);
                g_App.hWorkerThread = (HANDLE)_beginthreadex(NULL, 0, SetupWorkerThread, NULL, 0, NULL);
            } else if (wmId == IDC_BTN_LOG) {
                wchar_t logPath[MAX_PATH];
                wsprintfW(logPath, L"%s\\install.log", g_App.exeDir);
                ShellExecuteW(hwnd, L"open", logPath, NULL, NULL, SW_SHOWNORMAL);
            }
            return 0;
        }

        case WM_APP_PROGRESS: {
            InvalidateRect(hwnd, NULL, FALSE);
            return 0;
        }

        case WM_APP_DONE: {
            wchar_t runner[MAX_PATH];
            wchar_t mainPy[MAX_PATH];
            if (CheckEnvironmentReady(g_App.exeDir, runner, mainPy)) {
                LaunchVoicerStudio(g_App.exeDir, runner, mainPy, g_App.pCmdLine);
            }
            PostQuitMessage(0);
            return 0;
        }

        case WM_APP_ERROR: {
            ShowWindow(GetDlgItem(hwnd, IDC_BTN_LOG), SW_SHOW);
            EnableWindow(GetDlgItem(hwnd, IDC_BTN_LOG), TRUE);

            ShowWindow(GetDlgItem(hwnd, IDC_BTN_RETRY), SW_SHOW);
            EnableWindow(GetDlgItem(hwnd, IDC_BTN_RETRY), TRUE);

            SetWindowTextW(GetDlgItem(hwnd, IDC_BTN_CANCEL), L"ปิด (Close)");
            InvalidateRect(hwnd, NULL, FALSE);
            return 0;
        }

        case WM_PAINT: {
            PAINTSTRUCT ps;
            HDC hdc = BeginPaint(hwnd, &ps);

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
                RECT rcStage = { 30, 105, rcClient.right - 30, 133 };
                DrawTextW(memDC, L"การติดตั้งพบข้อผิดพลาด", -1, &rcStage, DT_SINGLELINE | DT_LEFT);
            } else {
                SetTextColor(memDC, COLOR_TEXT_PRIMARY);
                RECT rcStage = { 30, 105, rcClient.right - 100, 133 };
                DrawTextW(memDC, g_App.stageTitle[0] ? g_App.stageTitle : L"กำลังเริ่มต้นระบบ...", -1, &rcStage, DT_SINGLELINE | DT_LEFT);

                wchar_t pctText[32];
                wsprintfW(pctText, L"%d%%", g_App.progressPct);
                RECT rcPct = { rcClient.right - 90, 105, rcClient.right - 30, 133 };
                DrawTextW(memDC, pctText, -1, &rcPct, DT_SINGLELINE | DT_RIGHT);
            }

            // 6. Progress Bar Track & Indicator
            int pbX = 30;
            int pbY = 142;
            int pbW = rcClient.right - 60;
            int pbH = 10;

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
                RECT rcErr = { 30, 165, rcClient.right - 30, WIN_HEIGHT - 72 };
                DrawTextW(memDC, g_App.errorMsg, -1, &rcErr, DT_WORDBREAK | DT_LEFT);
            } else {
                SetTextColor(memDC, COLOR_TEXT_DIM);
                RECT rcDetail = { 30, 165, rcClient.right - 30, WIN_HEIGHT - 72 };
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

// Application Entry Point
int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, PWSTR pCmdLine, int nCmdShow) {
    g_App.hInstance = hInstance;
    g_App.pCmdLine = pCmdLine;

    // Get executable directory
    if (!GetModuleFileNameW(NULL, g_App.exeDir, MAX_PATH)) return 1;
    wchar_t *lastSlash = wcsrchr(g_App.exeDir, L'\\');
    if (lastSlash) *lastSlash = L'\0';

    SetCurrentDirectoryW(g_App.exeDir);
    wsprintfW(g_App.installLogPath, L"%s\\install.log", g_App.exeDir);
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
