# -*- coding: utf-8 -*-
"""startupasadmin_config.py — 以管理员身份自启动的配置模型。

配置经官方插件配置通道持久化，存放于
``configs.json -> plugins.configs.com.classwidgets.startupasadmin``。

模块名刻意加插件前缀，避免与其它插件的 ``config.py`` 在顶层命名空间冲突。
"""

from __future__ import annotations

from ClassWidgets.SDK import ConfigBaseModel


class StartupAsAdminConfig(ConfigBaseModel):
    """以管理员身份自启动配置。"""

    # 计划任务名（Windows 任务计划程序里显示的名字）
    task_name: str = "ClassWidgets2-StartUpAsAdmin"

    # 手动指定主程序 exe；留空则自动探测
    custom_exe: str = ""
