/*
 * ok-nikke 入口 shim：ok-nikke.exe -> python\pythonw.exe main.py [额外参数]
 *
 * - UAC：manifest 声明 requestAdministrator，子进程继承提权，应用内更新/重启不再二次弹窗。
 * - 便携性：用户只需双击一个 exe，不必知道 python\ 的存在。
 * - 工作目录：框架路径解析（Config.config_file / og.app_path / check_mutex）基于 cwd，这里用 exe 目录强制。
 *
 * 拉起应用后立即退出，不等待子进程、不持有句柄、无控制台窗口，否则会卡住 update.py 等更新流程。
 *
 * 构建：launcher\build.ps1（MinGW 或 MSVC，自动探测）
 */

/* MinGW 的 -municode 已定义这两个宏，加保护避免重定义告警 */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>

#define PATH_BUF 2048  /* 路径缓冲，CreateProcess 上限 32767 */

/* GUI 子系统无控制台，出错只能弹窗 */
static void show_error(const wchar_t *detail)
{
    MessageBoxW(NULL, detail, L"ok-nikke", MB_OK | MB_ICONERROR);
}

static BOOL file_exists(const wchar_t *path)
{
    DWORD attrs = GetFileAttributesW(path);
    return attrs != INVALID_FILE_ATTRIBUTES && !(attrs & FILE_ATTRIBUTE_DIRECTORY);
}

/* out = root \ rel；超长时加 \\?\ 前缀 */
static void join_path(wchar_t *out, const wchar_t *root, const wchar_t *rel)
{
    size_t root_len = lstrlenW(root);
    if (root_len + lstrlenW(rel) + 2 >= MAX_PATH) {
        lstrcpynW(out, L"\\\\?\\", PATH_BUF);
        lstrcatW(out, root);
    } else {
        lstrcpynW(out, root, PATH_BUF);
    }
    if (out[lstrlenW(out) - 1] != L'\\') {
        lstrcatW(out, L"\\");
    }
    lstrcatW(out, rel);
}

/* 取命令行中程序名之后的部分，用于转发 -t/-e 等参数 */
static const wchar_t *extra_arguments(void)
{
    const wchar_t *cmd = GetCommandLineW();
    if (cmd == NULL) {
        return L"";
    }
    const wchar_t *p = cmd;
    while (*p == L' ' || *p == L'\t') {
        p++;
    }
    if (*p == L'"') {
        p++;
        while (*p != L'\0' && *p != L'"') {
            p++;
        }
        if (*p == L'"') {
            p++;
        }
    } else {
        while (*p != L'\0' && *p != L' ' && *p != L'\t') {
            p++;
        }
    }
    while (*p == L' ' || *p == L'\t') {
        p++;
    }
    return p;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE prev_instance, PWSTR cmd_line, int show_cmd)
{
    wchar_t exe[MAX_PATH];
    DWORD len = GetModuleFileNameW(NULL, exe, MAX_PATH);
    if (len == 0 || len >= MAX_PATH) {
        show_error(L"无法获取自身路径，请把程序放在更短的英文路径下再试。");
        return 1;
    }

    /* 包根 = exe 所在目录 */
    wchar_t root[MAX_PATH];
    lstrcpynW(root, exe, MAX_PATH);
    wchar_t *last_slash = wcsrchr(root, L'\\');
    if (last_slash == NULL) {
        show_error(L"自身路径异常，无法确定程序目录。");
        return 1;
    }
    *last_slash = L'\0';

    wchar_t pythonw[PATH_BUF];
    wchar_t main_py[PATH_BUF];
    join_path(pythonw, root, L"python\\pythonw.exe");
    join_path(main_py, root, L"main.py");

    if (!file_exists(pythonw)) {
        show_error(L"未找到 python\\pythonw.exe。\n\n便携包可能解压不完整，请重新解压后再运行。");
        return 2;
    }
    if (!file_exists(main_py)) {
        show_error(L"未找到 main.py。\n\n请确认程序目录下文件完整。");
        return 2;
    }

    /* 命令行："<pythonw>" "<main.py>" <额外参数>；main.py 用绝对路径，使 sys.argv[0] 落在包根 */
    wchar_t command[PATH_BUF * 2];
    lstrcpynW(command, L"\"", PATH_BUF * 2);
    lstrcatW(command, pythonw);
    lstrcatW(command, L"\" \"");
    lstrcatW(command, main_py);
    lstrcatW(command, L"\"");
    const wchar_t *extra = extra_arguments();
    if (extra[0] != L'\0') {
        lstrcatW(command, L" ");
        lstrcatW(command, extra);
    }

    STARTUPINFOW startup;
    PROCESS_INFORMATION process;
    ZeroMemory(&startup, sizeof(startup));
    ZeroMemory(&process, sizeof(process));
    startup.cb = sizeof(startup);

    /* 不继承句柄、不等待、立即关闭句柄：应用独立存活，退出码只表示拉起成功 */
    if (!CreateProcessW(pythonw, command, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, root,
                        &startup, &process)) {
        wchar_t message[512];
        lstrcpynW(message, L"启动失败（错误码 ", 512);
        wchar_t code[16];
        wsprintfW(code, L"%lu", GetLastError());
        lstrcatW(message, code);
        lstrcatW(message, L"）。\n\n可尝试直接运行 python\\pythonw.exe main.py 排查。");
        show_error(message);
        return 3;
    }

    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}
