# -*- coding: utf-8 -*-
"""以管理员身份自启动 —— Class Widgets 2 插件。

通过 Windows 计划任务，让 Class Widgets 2 在用户登录时以管理员身份自启动。
思路来自 ClassIsland 的 StartUpAsAdmin 插件。

本插件不注册桌面组件，只注册一个设置页（``api.ui.register_settings_page``）。
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from ClassWidgets.SDK import CW2Plugin, PluginAPI
from loguru import logger
from PySide6.QtCore import Signal, Slot

try:
    from startupasadmin_config import StartupAsAdminConfig
    import startupasadmin_tasks as tasks
except ImportError:  # pragma: no cover - SDK 一般已把插件目录加入 sys.path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from startupasadmin_config import StartupAsAdminConfig
    import startupasadmin_tasks as tasks

_SETTINGS_ICON = "ic_fluent_shield_20_regular"


class Plugin(CW2Plugin):
    """以管理员身份自启动。"""

    # 计划任务状态变化（设置页据此刷新）
    statusChanged = Signal()

    def __init__(self, api: PluginAPI):
        super().__init__(api)
        self._config = StartupAsAdminConfig()
        self._page = str(Path(__file__).parent / "qml" / "settings.qml")
        self._busy = False
        self._last_result = {"ok": True, "message": ""}

    # ── 生命周期 ────────────────────────────────────────────────

    def on_load(self):
        super().on_load()
        try:
            self.api.config.register_plugin_model(self.pid, self._config)
            logger.info("[startupasadmin] 配置模型注册成功: plugins.configs.{}", self.pid)
        except Exception as e:
            logger.warning("[startupasadmin] 注册配置模型失败: {}", e)

        try:
            self.api.ui.register_settings_page(
                qml_path=self._page,
                title="以管理员身份自启动",
                icon=_SETTINGS_ICON,
            )
            logger.info("[startupasadmin] 设置页注册成功")
        except Exception as e:
            logger.warning("[startupasadmin] 注册设置页失败: {}", e)

    def on_unload(self):
        try:
            self.api.ui.unregister_settings_page(self._page)
        except Exception:
            pass
        super().on_unload()
        logger.info("[startupasadmin] 插件已卸载")

    # ── 内部 ────────────────────────────────────────────────────

    def _task_name(self) -> str:
        name = (self._config.task_name or "").strip()
        return name or tasks.DEFAULT_TASK_NAME

    def _exe(self):
        """目标主程序：优先用户手动指定的路径，其次自动探测。"""
        custom = (self._config.custom_exe or "").strip().strip('"')
        if custom:
            p = Path(custom)
            if p.is_file():
                return p
        return tasks.app_executable()

    def _save(self):
        try:
            self.api.config.save()
        except Exception as e:
            logger.warning("[startupasadmin] 保存配置失败: {}", e)

    # ── 设置页槽 ────────────────────────────────────────────────

    @Slot(result=dict)
    def getStatus(self) -> dict:
        """设置页用的完整状态快照。"""
        exe = self._exe()
        info = tasks.task_status(self._task_name())
        registered = str(info.get("execute") or "")
        up_to_date = False
        if exe is not None and registered:
            try:
                up_to_date = Path(registered).resolve() == Path(exe).resolve()
            except OSError:
                up_to_date = registered.lower() == str(exe).lower()
        return {
            "supported": os.name == "nt",
            "elevated": tasks.is_admin(),
            "appPath": str(exe) if exe is not None else "",
            "appFound": exe is not None,
            "taskName": self._task_name(),
            "exists": bool(info.get("exists")),
            "state": str(info.get("state") or ""),
            "runLevel": str(info.get("runLevel") or ""),
            "registeredExe": registered,
            "upToDate": up_to_date,
            "customExe": self._config.custom_exe or "",
            "error": str(info.get("error") or ""),
        }

    @Slot()
    def requestCreate(self) -> None:
        """创建 / 更新计划任务。放到后台线程，避免等待 UAC 时卡住界面。"""
        self._run_async(self._create_impl)

    @Slot()
    def requestDelete(self) -> None:
        """删除计划任务。同样放到后台线程。"""
        self._run_async(self._delete_impl)

    def _run_async(self, fn):
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._worker, args=(fn,), daemon=True).start()

    def _worker(self, fn):
        try:
            ok, message = fn()
        except Exception as e:
            ok, message = False, f"执行失败：{e}"
            logger.exception("[startupasadmin] 计划任务操作异常")
        self._last_result = {"ok": bool(ok), "message": str(message)}
        self._busy = False
        self.statusChanged.emit()      # 跨线程发射，Qt 会排队到主线程

    def _create_impl(self):
        if os.name != "nt":
            return False, "本插件仅支持 Windows"
        exe = self._exe()
        if exe is None:
            return False, "找不到主程序，请在「高级」里手动指定 Class Widgets 2 的 exe 路径"
        return tasks.create_task(self._task_name(), exe)

    def _delete_impl(self):
        if os.name != "nt":
            return False, "本插件仅支持 Windows"
        return tasks.delete_task(self._task_name())

    @Slot(result=dict)
    def getLastResult(self) -> dict:
        return dict(self._last_result)

    @Slot(result=bool)
    def isBusy(self) -> bool:
        return self._busy

    @Slot(result=dict)
    def refresh(self) -> dict:
        return self.getStatus()

    @Slot(str)
    def setCustomExe(self, path: str) -> None:
        self._config.custom_exe = str(path or "").strip().strip('"')
        self._save()
        self.statusChanged.emit()

    @Slot(str)
    def setTaskName(self, name: str) -> None:
        clean = str(name or "").strip()
        self._config.task_name = clean or tasks.DEFAULT_TASK_NAME
        self._save()
        self.statusChanged.emit()

    @Slot(result=str)
    def getDefaultTaskName(self) -> str:
        return tasks.DEFAULT_TASK_NAME
