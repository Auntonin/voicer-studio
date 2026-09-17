/*
 * launcher.c
 * ==========
 * Native Windows GUI Launcher for Voicer Studio.
 * Compiles to VoicerStudio.exe (subsystem: windows) with embedded icon and version info.
 * Zero console flashing, auto-environment check, one-click bootstrapper.
 */

#define UNICODE
#define _UNICODE
#define WIN32_LEAN_AND_MEAN

#include <windows.h>
#include <shellapi.h>
#include <shlwapi.h>
#include <stdio.h>
#include <stdbool.h>

#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "shlwapi.lib")

static bool FileExists(const wchar_t *path) {
    DWORD attr = GetFileAttributesW(path);
    return (attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY));
}

static bool DirectoryExists(const wchar_t *path) {
    DWORD attr = GetFileAttributesW(path);
    return (attr != INVALID_FILE_ATTRIBUTES && (attr & FILE_ATTRIBUTE_DIRECTORY));
}

static bool FindSystemPython(wchar_t *outPath, DWORD maxLen) {
    // Search PATH for python.exe
    return SearchPathW(NULL, L"python.exe", NULL, maxLen, outPath, NULL) > 0;
}

int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, PWSTR pCmdLine, int nCmdShow) {
    wchar_t exeDir[MAX_PATH];
    if (!GetModuleFileNameW(NULL, exeDir, MAX_PATH)) {
        return 1;
    }

    // Strip executable name to get directory
    wchar_t *lastSlash = wcsrchr(exeDir, L'\\');
    if (lastSlash) {
        *lastSlash = L'\0';
    }

    // Set current working directory to the application folder
    SetCurrentDirectoryW(exeDir);

    wchar_t venvPython[MAX_PATH];
    swprintf(venvPython, MAX_PATH, L"%s\\.venv\\Scripts\\pythonw.exe", exeDir);

    wchar_t mainScript[MAX_PATH];
    swprintf(mainScript, MAX_PATH, L"%s\\main.py", exeDir);

    // ── Scenario A: Virtual environment and main.py exist (Standard Launch) ──
    if (FileExists(venvPython) && FileExists(mainScript)) {
        wchar_t cmdLine[2048];
        if (pCmdLine && wcslen(pCmdLine) > 0) {
            swprintf(cmdLine, 2048, L"\"%s\" \"%s\" %s", venvPython, mainScript, pCmdLine);
        } else {
            swprintf(cmdLine, 2048, L"\"%s\" \"%s\"", venvPython, mainScript);
        }

        STARTUPINFOW si;
        PROCESS_INFORMATION pi;
        ZeroMemory(&si, sizeof(si));
        si.cb = sizeof(si);
        si.dwFlags = STARTF_USESHOWWINDOW;
        si.wShowWindow = SW_SHOWNORMAL;
        ZeroMemory(&pi, sizeof(pi));

        // Launch pythonw directly as detached GUI process
        BOOL success = CreateProcessW(
            venvPython,
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
            // Fallback without breakaway flag
            success = CreateProcessW(
                venvPython,
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

        if (success) {
            CloseHandle(pi.hProcess);
            CloseHandle(pi.hThread);
            return 0;
        } else {
            DWORD err = GetLastError();
            wchar_t errMsg[256];
            swprintf(errMsg, 256, L"Failed to start Voicer Studio.\nWindows Error Code: %lu", err);
            MessageBoxW(NULL, errMsg, L"Voicer Studio — Launch Error", MB_OK | MB_ICONERROR);
            return 1;
        }
    }

    // ── Scenario B: Setup is needed ──
    wchar_t sysPython[MAX_PATH] = {0};
    bool hasPython = FindSystemPython(sysPython, MAX_PATH);

    if (!hasPython) {
        int choice = MessageBoxW(
            NULL,
            L"Voicer Studio requires Python 3.10 or higher.\n\n"
            L"Python was not found on your computer.\n"
            L"Click OK to open the official Python download page.",
            L"Voicer Studio — Python Required",
            MB_OKCANCEL | MB_ICONWARNING | MB_TOPMOST
        );

        if (choice == IDOK) {
            ShellExecuteW(NULL, L"open", L"https://www.python.org/downloads/", NULL, NULL, SW_SHOWNORMAL);
        }
        return 1;
    }

    // Python is available, offer to run setup
    int choice = MessageBoxW(
        NULL,
        L"Voicer Studio environment is not set up yet.\n\n"
        L"Would you like to run the automated setup now?\n"
        L"(This will configure the environment and install dependencies)",
        L"Voicer Studio — Initial Setup",
        MB_YESNO | MB_ICONINFORMATION | MB_TOPMOST
    );

    if (choice == IDYES) {
        wchar_t setupBat[MAX_PATH];
        swprintf(setupBat, MAX_PATH, L"%s\\setup.bat", exeDir);

        if (FileExists(setupBat)) {
            // Run setup.bat in a visible terminal window so user can see initial progress
            ShellExecuteW(NULL, L"open", setupBat, NULL, exeDir, SW_SHOWNORMAL);
        } else {
            MessageBoxW(
                NULL,
                L"setup.bat not found in application directory.",
                L"Voicer Studio — Error",
                MB_OK | MB_ICONERROR
            );
        }
    }

    return 0;
}
