import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import RinUI
import ClassWidgets.Plugins

/*!
    以管理员身份自启动 —— 设置页。

    通过 Windows 计划任务，让 Class Widgets 2 在登录时以管理员身份自启动。
    创建 / 删除任务需要管理员权限，后端会在后台线程里提权执行，
    完成后发 statusChanged，这里据此刷新状态并显示结果。
*/

PluginPage {
    id: page
    pluginId: "com.classwidgets.startupasadmin"
    title: qsTr("以管理员身份自启动")

    property var info: ({})
    property bool busy: false
    property string resultText: ""
    property bool resultOk: true

    Component.onCompleted: Qt.callLater(reload)
    onBackendChanged: { if (backend) Qt.callLater(reload) }

    Connections {
        target: backend
        function onStatusChanged() {
            page.busy = false
            var r = backend ? backend.getLastResult() : null
            if (r && r.message) {
                page.resultOk = r.ok === true
                page.resultText = String(r.message)
            }
            page.reload()
        }
    }

    function reload() {
        if (!backend) return
        var s = backend.getStatus()
        if (s) info = s
    }

    function stateText() {
        if (info.supported === false) return qsTr("当前系统不支持（仅 Windows）")
        if (info.appFound === false) return qsTr("未找到主程序")
        if (info.exists !== true) return qsTr("尚未创建计划任务")
        if (info.upToDate !== true) return qsTr("已创建，但指向的程序已变化，建议更新")
        return qsTr("已就绪：登录时将自动以管理员身份启动")
    }

    function stateColor() {
        if (info.supported === false || info.appFound === false) return "#E05B5B"
        if (info.exists !== true || info.upToDate !== true) return "#D28B59"
        return "#46CEA3"
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 16

        SettingCard {
            Layout.fillWidth: true
            title: qsTr("计划任务状态")
            description: qsTr("计划任务会在你登录 Windows 时，以最高权限启动 Class Widgets 2。")

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6

                RowLayout {
                    spacing: 8
                    Rectangle {
                        width: 10
                        height: 10
                        radius: 5
                        color: page.stateColor()
                    }
                    Text {
                        text: page.stateText()
                        font.bold: true
                    }
                }

                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: qsTr("任务名称：") + (page.info.taskName || "")
                }

                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: qsTr("主程序：") + (page.info.appPath || qsTr("未找到"))
                }

                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    visible: page.info.exists === true
                    text: qsTr("已注册的路径：") + (page.info.registeredExe || "")
                          + (page.info.runLevel ? qsTr("（运行级别 ") + page.info.runLevel + qsTr("）") : "")
                }

                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    visible: page.info.appFound === false
                    color: "#E05B5B"
                    text: qsTr("没能自动找到主程序，请在下方「高级」里手动指定 Class Widgets 2 的 exe 路径。")
                }
            }
        }

        // 注册前的绿色提醒：主程序自带的开机自启动必须先关掉，
        // 否则登录时会同时被主程序和计划任务拉起两次
        SettingCard {
            Layout.fillWidth: true
            title: qsTr("注册前请先关闭主程序的开机自启动")
            description: qsTr("两者同时开启会导致登录时重复启动。")

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6

                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    color: "#46CEA3"
                    font.bold: true
                    text: qsTr("请关闭主程序的开机自启动后再注册计划任务")
                }
            }
        }

        RowLayout {
            spacing: 12

            Button {
                text: page.busy ? qsTr("处理中…") : qsTr("创建 / 更新计划任务")
                enabled: !page.busy
                onClicked: {
                    page.busy = true
                    page.resultText = ""
                    if (backend) backend.requestCreate()
                }
            }

            Button {
                text: qsTr("删除计划任务")
                enabled: !page.busy && page.info.exists === true
                onClicked: {
                    page.busy = true
                    page.resultText = ""
                    if (backend) backend.requestDelete()
                }
            }

            Button {
                text: qsTr("刷新状态")
                enabled: !page.busy
                onClicked: page.reload()
            }
        }

        Text {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            visible: page.resultText !== ""
            color: page.resultOk ? "#46CEA3" : "#E05B5B"
            text: page.resultText
        }

        SettingExpander {
            Layout.fillWidth: true
            icon.name: "ic_fluent_settings_20_regular"
            title: qsTr("高级")
            description: qsTr("自动探测失败，或想换一个任务名时使用。")
            expanded: false

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 12

                SettingCard {
                    Layout.fillWidth: true
                    title: qsTr("主程序路径")
                    description: qsTr("留空则自动探测。填错会导致自启动失败。")

                    TextField {
                        Layout.preferredWidth: 400
                        placeholderText: qsTr("例如 D:\\ClassWidgets\\Class Widgets 2.exe")
                        text: page.info.customExe || ""
                        selectByMouse: true
                        onEditingFinished: {
                            if (backend) backend.setCustomExe(text)
                            page.reload()
                        }
                    }
                }

                SettingCard {
                    Layout.fillWidth: true
                    title: qsTr("计划任务名称")
                    description: qsTr("显示在「任务计划程序」里的名字。改名后需要重新创建任务。")

                    TextField {
                        Layout.preferredWidth: 280
                        text: page.info.taskName || ""
                        selectByMouse: true
                        onEditingFinished: {
                            if (backend) backend.setTaskName(text)
                            page.reload()
                        }
                    }
                }
            }
        }

        Text {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: qsTr("提示：创建或删除计划任务需要管理员权限，点击按钮后会出现 UAC 授权窗口。" +
                       "创建好的任务不会随插件卸载而删除，需要时请回到这里手动删除；" +
                       "若之后移动了 Class Widgets 2 的位置，请回来点一次「创建 / 更新」。")
        }
    }
}
