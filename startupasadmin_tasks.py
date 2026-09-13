# -*- coding: utf-8 -*-
"""startupasadmin_tasks.py — 用 Windows 计划任务让 Class Widgets 2 以管理员身份自启动。

思路与 ClassIsland 的 StartUpAsAdmin 插件一致：创建一个"最高权限运行"的登录触发器
计划任务。创建 / 删除这类任务本身就需要管理员权限，所以通过 UAC 提权执行，
再用一个临时结果文件把提权进程的结果回传（提权进程无法回传 stdout）。

查询任务状态不需要提权。
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path
from typing import Optional, Tuple

try:
    from loguru import logger
except ImportError:  # 应用外（例如单独测试）时降级到标准库
    import logging

    logger = logging.getLogger("startupasadmin")

DEFAULT_TASK_NAME = "ClassWidgets2-StartUpAsAdmin"

# 打包发行版的主程序可执行文件名（注意第一个含空格）
_APP_EXE_NAMES = ("Class Widgets 2.exe", "ClassWidgets2.exe", "ClassWidgets.exe")

_IS_WINDOWS = os.name == "nt"

# UAC 被用户取消时的 ShellExecute 错误码
_ERROR_CANCELLED = 1223


# ── 路径探测 ────────────────────────────────────────────────────────


def app_root() -> Optional[Path]:
    """主程序根目录：<根>/plugins/<插件 id>/task_manager.py 往上找到 plugins 的上一层。"""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name.lower() == "plugins":
            return parent.parent
    # 退回：<根>/plugins/<id>/ 往上三层
    try:
        return here.parents[2]
    except IndexError:
        return None


def app_executable() -> Optional[Path]:
    """定位主程序 exe。找不到返回 None。"""
    # 1) 打包运行时，sys.executable 就是主程序本身
    exe = Path(sys.executable)
    if _IS_WINDOWS and exe.suffix.lower() == ".exe" and "python" not in exe.name.lower():
        if exe.is_file():
            return exe

    # 2) 已知文件名
    root = app_root()
    if root is None or not root.is_dir():
        return None
    for name in _APP_EXE_NAMES:
        p = root / name
        if p.is_file():
            return p

    # 3) 兜底：根目录下名字里带 class 的 exe
    for p in sorted(root.glob("*.exe")):
        if "class" in p.name.lower():
            return p
    return None


def is_admin() -> bool:
    """当前进程是否已提权。"""
    if not _IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ── PowerShell 辅助 ─────────────────────────────────────────────────


def _ps_quote(s) -> str:
    """转成 PowerShell 单引号字符串（内部单引号翻倍）。"""
    return "'" + str(s).replace("'", "''") + "'"


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "gbk", "mbcs"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run_powershell(script: str, timeout: int = 60) -> Tuple[bool, str]:
    """非提权地执行一段 PowerShell，返回 (是否成功, 输出)。"""
    if not _IS_WINDOWS:
        return False, "仅支持 Windows"
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, timeout=timeout, creationflags=_no_window(),
        )
    except Exception as e:
        return False, f"调用 PowerShell 失败: {e}"
    out = _decode(proc.stdout).strip()
    err = _decode(proc.stderr).strip()
    if proc.returncode != 0 and not out:
        return False, err or f"PowerShell 退出码 {proc.returncode}"
    return True, out


# ── 提权执行 ────────────────────────────────────────────────────────

_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SW_SHOWNORMAL = 1


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def _shell_execute_ex(verb: str, file: str, params: str,
                      timeout_ms: int) -> Tuple[bool, int]:
    """ShellExecuteExW + 等待结束，返回 (是否已启动, 退出码或错误码)。"""
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    sei = _SHELLEXECUTEINFOW()
    sei.cbSize = ctypes.sizeof(_SHELLEXECUTEINFOW)
    sei.fMask = _SEE_MASK_NOCLOSEPROCESS
    sei.lpVerb = verb
    sei.lpFile = file
    sei.lpParameters = params
    sei.lpDirectory = None
    sei.nShow = _SW_SHOWNORMAL

    if not shell32.ShellExecuteExW(ctypes.byref(sei)):
        return False, ctypes.get_last_error()

    handle = sei.hProcess
    if not handle:
        return True, 0
    try:
        kernel32.WaitForSingleObject(handle, timeout_ms)
        code = wintypes.DWORD(0)
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return True, int(code.value)
    finally:
        kernel32.CloseHandle(handle)


def _run_elevated_script(body: str, timeout_ms: int = 300_000) -> Tuple[bool, str]:
    """把 PowerShell 脚本写到临时文件，提权执行，并从结果文件回读输出。

    body 里用 __OUT__ 占位表示结果文件路径。
    """
    if not _IS_WINDOWS:
        return False, "仅支持 Windows"

    tag = f"cw2_startupasadmin_{os.getpid()}"
    out_file = Path(tempfile.gettempdir()) / f"{tag}.out"
    ps1_file = Path(tempfile.gettempdir()) / f"{tag}.ps1"
    for f in (out_file, ps1_file):
        try:
            f.unlink()
        except OSError:
            pass

    script = (
        "$ErrorActionPreference = 'Stop'\n"
        "$result = 'ERR: 脚本未产生结果'\n"
        "try {\n"
        + body.replace("__OUT__", _ps_quote(str(out_file)))
        + "\n} catch {\n"
        "    $result = 'ERR: ' + $_.Exception.Message\n"
        "}\n"
        f"$result | Out-File -FilePath {_ps_quote(str(out_file))} -Encoding utf8\n"
        "if ($result -like 'OK*') { exit 0 } else { exit 1 }\n"
    )

    try:
        ps1_file.write_text(script, encoding="utf-8-sig")
    except OSError as e:
        return False, f"写入临时脚本失败: {e}"

    params = f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{ps1_file}"'
    launched, code = _shell_execute_ex("runas", "powershell.exe", params, timeout_ms)

    if not launched:
        if code == _ERROR_CANCELLED:
            return False, "已取消管理员授权（UAC）"
        return False, f"提权执行失败（错误码 {code}）"

    message = ""
    try:
        if out_file.is_file():
            message = out_file.read_text(encoding="utf-8-sig", errors="replace").strip()
    except OSError:
        pass

    if code != 0:
        return False, message or f"提权进程退出码 {code}"
    return True, "OK"


# ── 计划任务操作 ────────────────────────────────────────────────────

_QUERY_TMPL = """
$ErrorActionPreference = 'SilentlyContinue'
$t = Get-ScheduledTask -TaskName __NAME__
if ($null -eq $t) {
    Write-Output '{"exists":false}'
    exit 0
}
$o = [pscustomobject]@{
    exists    = $true
    state     = [string]$t.State
    runLevel  = [string]$t.Principal.RunLevel
    execute   = [string]$t.Actions[0].Execute
    arguments = [string]$t.Actions[0].Arguments
}
Write-Output ($o | ConvertTo-Json -Compress)
"""


def task_status(task_name: str) -> dict:
    """查询计划任务状态。返回 dict，键：exists / state / runLevel / execute / error。"""
    ok, out = _run_powershell(_QUERY_TMPL.replace("__NAME__", _ps_quote(task_name)))
    if not ok:
        return {"exists": False, "error": out}
    line = ""
    for candidate in out.splitlines():
        candidate = candidate.strip()
        if candidate.startswith("{"):
            line = candidate
            break
    if not line:
        return {"exists": False, "error": "无法解析计划任务查询结果"}
    try:
        data = json.loads(line)
        if not isinstance(data, dict):
            raise ValueError("非对象")
        return data
    except Exception as e:
        return {"exists": False, "error": f"解析失败: {e}"}


_CREATE_BODY = """
    $exe = __EXE__
    if (-not (Test-Path -LiteralPath $exe)) {
        $result = 'ERR: 主程序文件不存在：' + $exe
    } else {
        $action = New-ScheduledTaskAction -Execute $exe
        $trigger = New-ScheduledTaskTrigger -AtLogOn
        $user = ('{0}\\{1}' -f $env:USERDOMAIN, $env:USERNAME)
        $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
                    -DontStopIfGoingOnBatteries -StartWhenAvailable
        Register-ScheduledTask -TaskName __NAME__ -Action $action -Trigger $trigger `
            -Principal $principal -Settings $settings -Force | Out-Null
        $result = 'OK'
    }
"""

_DELETE_BODY = """
    $existing = Get-ScheduledTask -TaskName __NAME__ -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
        $result = 'OK'
    } else {
        Unregister-ScheduledTask -TaskName __NAME__ -Confirm:$false
        $result = 'OK'
    }
"""


def create_task(task_name: str, exe_path) -> Tuple[bool, str]:
    """创建（或更新）以最高权限在登录时启动的计划任务。会弹 UAC。"""
    body = (_CREATE_BODY
            .replace("__EXE__", _ps_quote(str(exe_path)))
            .replace("__NAME__", _ps_quote(task_name)))
    ok, message = _run_elevated_script(body)
    if ok:
        logger.info(f"[startupasadmin] 计划任务已创建/更新: {task_name} -> {exe_path}")
        return True, "计划任务已创建：登录后将自动以管理员身份启动"
    logger.warning(f"[startupasadmin] 创建计划任务失败: {message}")
    return False, message


def delete_task(task_name: str) -> Tuple[bool, str]:
    """删除计划任务。会弹 UAC。"""
    body = _DELETE_BODY.replace("__NAME__", _ps_quote(task_name))
    ok, message = _run_elevated_script(body)
    if ok:
        logger.info(f"[startupasadmin] 计划任务已删除: {task_name}")
        return True, "计划任务已删除"
    logger.warning(f"[startupasadmin] 删除计划任务失败: {message}")
    return False, message
