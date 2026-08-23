import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import qs.Commons
import qs.Ui

// Titlebar controls for a compositor that has no titlebars: minimize and
// close act on the focused window, and the list button opens a dropdown of
// everything currently minimized.
//
// "Minimized" is not a Hyprland concept. The shared command-line tools park
// windows on special:minimized and remember their origin workspace in
// ~/.cache/hypr-minimized-stack. Both the bar and the keybindings invoke those
// same tools, so they share one definition of minimized state.
BarWidget {
  id: root
  moduleName: "io.github.fabiopauli.windowcontrols"

  // Bar.findPanelWidget requires open/close/opened on the widget root.
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function toggle() { if (panelLoader.item) panelLoader.item.toggle() }
  function closeForPopoutSwitch() { if (panelLoader.item) panelLoader.item.closeForPopoutSwitch() }

  property var windows: []
  readonly property int count: windows.length

  readonly property bool showList: setting("showList", true) !== false
  readonly property bool showMinimize: setting("showMinimize", true) !== false
  readonly property bool showClose: setting("showClose", true) !== false
  readonly property bool hideListWhenEmpty: setting("hideListWhenEmpty", false) === true
  readonly property bool showCount: setting("showCount", true) !== false
  readonly property bool listVisible: showList && (count > 0 || !hideListWhenEmpty)

  implicitWidth: layout.implicitWidth
  implicitHeight: layout.implicitHeight

  readonly property string countTooltip: count === 0
    ? "No minimized windows"
    : (count === 1 ? "1 minimized window" : count + " minimized windows")

  function refresh() {
    if (listProc.running) return
    listProc.running = true
  }

  function openList() {
    refresh()
    toggle()
  }

  function applyList(text) {
    // Util.parseModuleJson keeps only the final line and cannot parse an
    // array. The command emits compact JSON; malformed output becomes an
    // empty list instead of throwing inside the shell's collector.
    var parsed = []
    try {
      parsed = JSON.parse(String(text || "").trim() || "[]")
    } catch (error) {
      console.warn("io.github.fabiopauli.windowcontrols: could not parse minimized window list:", error)
    }
    root.windows = Array.isArray(parsed) ? parsed : []
  }

  function validAddress(address) {
    return /^0x[0-9a-fA-F]+$/.test(String(address || ""))
  }

  function restore(address) {
    if (!root.bar || !validAddress(address)) return
    root.bar.run("omarchy-restore-minimized " + address)
    refreshSoon.restart()
  }

  function dismiss(address) {
    if (!root.bar || !validAddress(address)) return
    // Hyprland on Omarchy uses Lua dispatchers. Target the parked window
    // directly so closing a list row never restores or focuses it first.
    root.bar.run("hyprctl eval 'hl.dispatch(hl.dsp.window.close({ window = \"address:" + address + "\" }))' >/dev/null")
    refreshSoon.restart()
  }

  function injectPanel() {
    if (!panelLoader.item) return
    panelLoader.item.bar = root.bar
    panelLoader.item.settings = root.settings
    panelLoader.item.anchorItem = listButton
    panelLoader.item.hostWidget = root
    panelLoader.item.host = root
  }

  onBarChanged: { injectPanel(); refresh() }
  onSettingsChanged: injectPanel()
  Component.onCompleted: refresh()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("MinimizedPanel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  Process {
    id: listProc
    command: ["omarchy-minimized-list"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyList(text)
    }
  }

  // Minimize/restore are workspace moves. Debounce raw events because the
  // compositor can emit them before hyprctl reports the settled workspace.
  Timer {
    id: refreshSoon
    interval: 120
    onTriggered: root.refresh()
  }

  Connections {
    target: Hyprland
    function onRawEvent(event) {
      if (!event || !event.name) return
      var name = String(event.name)
      if (name.indexOf("movewindow") === 0 || name === "closewindow" || name === "openwindow"
          || name === "windowtitle" || name === "windowtitlev2") refreshSoon.restart()
    }
  }

  // Backstop for missed events and manual moves.
  Timer {
    interval: 30000
    running: true
    repeat: true
    onTriggered: root.refresh()
  }

  // A row on horizontal bars and a column on vertical bars. The count is a
  // separate WidgetButton because BarIconButton fixes text at icon size.
  Grid {
    id: layout
    anchors.centerIn: parent
    rows: root.vertical ? -1 : 1
    columns: root.vertical ? 1 : -1
    flow: root.vertical ? Grid.TopToBottom : Grid.LeftToRight

    BarIconButton {
      id: listButton
      visible: root.listVisible
      bar: root.bar
      text: "󰍜" // MDI menu
      tooltipText: root.countTooltip
      dimmed: root.count === 0
      useActiveColor: false
      onPressed: function(mouseButton) {
        if (mouseButton === Qt.LeftButton) root.openList()
      }
    }

    WidgetButton {
      visible: root.listVisible && root.showCount && root.count > 0
      bar: root.bar
      text: String(root.count)
      tooltipText: root.countTooltip
      fontSize: Style.font.body
      useActiveColor: false
      horizontalMargin: 2
      onPressed: function(mouseButton) {
        if (mouseButton === Qt.LeftButton) root.openList()
      }
    }

    BarIconButton {
      visible: root.showMinimize
      bar: root.bar
      text: "󰖰" // MDI window-minimize
      tooltipText: "Minimize window\nSUPER + M"
      useActiveColor: false
      onPressed: function(mouseButton) {
        if (mouseButton !== Qt.LeftButton) return
        if (root.bar) root.bar.run("omarchy-minimize")
        refreshSoon.restart()
      }
    }

    BarIconButton {
      visible: root.showClose
      bar: root.bar
      text: "󰖭" // MDI window-close
      tooltipText: "Close window"
      useActiveColor: false
      onPressed: function(mouseButton) {
        if (mouseButton !== Qt.LeftButton) return
        if (root.bar) root.bar.run("hyprctl eval 'hl.dispatch(hl.dsp.window.close())' >/dev/null")
      }
    }
  }

  IpcHandler {
    target: root.moduleName

    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): void { root.broadcast("refresh") }
    function count(): int { return root.count }
  }
}
