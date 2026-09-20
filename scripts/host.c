/*
 * scripts/host.c
 * ==============
 * Native GUI Process Host for Voicer Studio (.venv\Scripts\VoicerStudio.exe).
 * 
 * Ensures the running process in Windows Task Manager is "Voicer Studio"
 * with its official brand icon, product description, and top-level grouping,
 * completely eliminating generic Python process grouping.
 */

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN

#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdbool.h>

typedef int (*Py_Main_t)(int argc, wchar_t **argv);

static bool FileExists(const wchar_t *path) {
    DWORD attr = GetFileAttributesW(path);
    return (attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY));
}

int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, PWSTR pCmdLine, int nCmdShow) {
    wchar_t rootDir[MAX_PATH] = {0};
    wchar_t venvDir[MAX_PATH] = {0};
    wchar_t cfgPath[MAX_PATH] = {0};
    wchar_t pythonHome[MAX_PATH] = {0};
    wchar_t mainScript[MAX_PATH] = {0};
    wchar_t **argv = NULL;
    wchar_t *p = NULL;
    FILE *fp = NULL;
    HMODULE hPy = NULL;
    Py_Main_t py_main = NULL;
    int numArgs = 0;
    int totalArgs = 0;
    int startArg = 1;
    int extraArgs = 0;
    int ret = 0;
    LPWSTR *cmdArgs = NULL;

    // Get executable path (.venv\Scripts\VoicerStudio.exe)
    if (!GetModuleFileNameW(NULL, rootDir, MAX_PATH)) return 1;

    // Strip \VoicerStudio.exe -> .venv\Scripts
    p = wcsrchr(rootDir, L'\\');
    if (p) *p = L'\0';

    // Strip \Scripts -> .venv
    p = wcsrchr(rootDir, L'\\');
    if (p) *p = L'\0';
    lstrcpyW(venvDir, rootDir);

    // Strip \.venv -> project root
    p = wcsrchr(rootDir, L'\\');
    if (p) *p = L'\0';

    // Set working directory to project root
    SetCurrentDirectoryW(rootDir);

    // Read pyvenv.cfg from .venv\pyvenv.cfg
    wsprintfW(cfgPath, L"%s\\pyvenv.cfg", venvDir);
    fp = _wfopen(cfgPath, L"r");
    if (fp) {
        char line[512];
        while (fgets(line, sizeof(line), fp)) {
            if (strncmp(line, "home = ", 7) == 0 || strncmp(line, "home=", 5) == 0) {
                char *val = strchr(line, '=') + 1;
                while (*val == ' ' || *val == '\t') val++;
                char *end = val + strlen(val) - 1;
                while (end > val && (*end == '\r' || *end == '\n' || *end == ' ' || *end == '\t')) {
                    *end = '\0';
                    end--;
                }
                MultiByteToWideChar(CP_UTF8, 0, val, -1, pythonHome, MAX_PATH);
                break;
            }
        }
        fclose(fp);
    }

    // Locate python3*.dll
    if (wcslen(pythonHome) > 0) {
        WIN32_FIND_DATAW fd;
        wchar_t searchPattern[MAX_PATH];
        SetDllDirectoryW(pythonHome);

        wsprintfW(searchPattern, L"%s\\python3*.dll", pythonHome);
        HANDLE hFind = FindFirstFileW(searchPattern, &fd);
        if (hFind != INVALID_HANDLE_VALUE) {
            do {
                if (_wcsicmp(fd.cFileName, L"python3.dll") != 0) {
                    wchar_t dllPath[MAX_PATH];
                    wsprintfW(dllPath, L"%s\\%s", pythonHome, fd.cFileName);
                    hPy = LoadLibraryW(dllPath);
                    if (hPy) break;
                }
            } while (FindNextFileW(hFind, &fd));
            FindClose(hFind);
        }
        if (!hPy) {
            wchar_t dllPath[MAX_PATH];
            wsprintfW(dllPath, L"%s\\python3.dll", pythonHome);
            hPy = LoadLibraryW(dllPath);
        }
    }

    // Fallback search
    if (!hPy) hPy = LoadLibraryW(L"python312.dll");
    if (!hPy) hPy = LoadLibraryW(L"python311.dll");
    if (!hPy) hPy = LoadLibraryW(L"python310.dll");
    if (!hPy) hPy = LoadLibraryW(L"python3.dll");

    if (!hPy) {
        MessageBoxW(
            NULL,
            L"Could not load Python runtime library (python3*.dll).\nPlease ensure Python is properly installed.",
            L"Voicer Studio — Launch Error",
            MB_OK | MB_ICONERROR
        );
        return 1;
    }

    py_main = (Py_Main_t)GetProcAddress(hPy, "Py_Main");
    if (!py_main) {
        MessageBoxW(
            NULL,
            L"Could not locate Py_Main in Python DLL.",
            L"Voicer Studio — Launch Error",
            MB_OK | MB_ICONERROR
        );
        return 1;
    }

    // Absolute path to main.py
    wsprintfW(mainScript, L"%s\\main.py", rootDir);

    cmdArgs = CommandLineToArgvW(GetCommandLineW(), &numArgs);
    
    // Check if mainScript or main.py was already passed
    if (numArgs > 1 && (wcsstr(cmdArgs[1], L"main.py") != NULL)) {
        startArg = 2;
    }

    extraArgs = (numArgs > startArg) ? (numArgs - startArg) : 0;
    totalArgs = 2 + extraArgs;
    argv = (wchar_t **)malloc(sizeof(wchar_t *) * (totalArgs + 1));
    argv[0] = L"VoicerStudio.exe";
    argv[1] = mainScript;
    for (int i = 0; i < extraArgs; i++) {
        argv[2 + i] = cmdArgs[startArg + i];
    }
    argv[totalArgs] = NULL;

    // Run Python application in-process
    ret = py_main(totalArgs, argv);

    if (cmdArgs) LocalFree(cmdArgs);
    free(argv);
    return ret;
}
