import QtQuick
import qs.Commons
import qs.Ui

// One row per window currently parked on special:minimized. BarWidget.qml
// owns the process and actions; this nested panel owns presentation and
// keyboard navigation.
Panel {
  id: root
  moduleName: "io.github.fabiopauli.windowcontrols"
  ipcTarget: "io.github.fabiopauli.windowcontrols"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root
  property var host: null

  readonly property var windows: host && host.windows ? host.windows : []
  readonly property int count: windows.length

  readonly property color contentForeground: bar ? bar.foreground : Color.foreground
  readonly property string contentFontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color mutedForeground: Qt.darker(contentForeground, 1.5)
  readonly property int panelWidth: Style.space(320)
  readonly property int rowHeight: Style.space(38)

  property int cursorIndex: 0

  function clampCursor() {
    if (count === 0) cursorIndex = 0
    else if (cursorIndex >= count) cursorIndex = count - 1
    else if (cursorIndex < 0) cursorIndex = 0
  }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  function activateCursor() {
    if (count === 0) return
    var entry = windows[cursorIndex]
    if (!entry) return
    root.close()
    if (host) host.restore(entry.address)
  }

  function dismissCursor() {
    if (count === 0 || !host) return
    var entry = windows[cursorIndex]
    if (!entry) return
    host.dismiss(entry.address)
    if (count <= 1) root.close()
  }

  onOpenedChanged: if (opened) cursorIndex = 0
  onCountChanged: clampCursor()

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(root.panelWidth)
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent

      onMoveRequested: function(dx, dy) {
        if (root.count === 0 || dy === 0) return
        root.cursorIndex = (root.cursorIndex + dy + root.count) % root.count
      }
      onActivateRequested: root.activateCursor()
      onCloseRequested: root.close()
      onDeleteRequested: root.dismissCursor()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: column
        width: parent.width
        spacing: Style.spacing.sm

        PanelSectionHeader {
          text: "MINIMIZED WINDOWS"
          foreground: root.contentForeground
          fontFamily: root.contentFontFamily
        }

        Item {
          width: parent.width
          height: Style.spacing.xxs
        }

        Text {
          visible: root.count === 0
          width: parent.width
          textFormat: Text.PlainText
          text: "Nothing is minimized.\nSUPER + M minimizes the focused window."
          color: root.mutedForeground
          font.family: root.contentFontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
          lineHeight: 1.3
        }

        Repeater {
          model: root.windows

          delegate: CursorSurface {
            id: row
            required property int index
            required property var modelData

            width: column.width
            height: root.rowHeight
            foreground: root.contentForeground
            hasCursor: root.cursorIndex === index

            MouseArea {
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onEntered: root.cursorIndex = row.index
              onClicked: {
                root.cursorIndex = row.index
                root.activateCursor()
              }
            }

            Row {
              anchors.fill: parent
              anchors.leftMargin: Style.spacing.rowPaddingX
              anchors.rightMargin: Style.spacing.sm
              spacing: Style.spacing.lg

              Text {
                id: appIcon
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: "󰘔" // MDI application-outline
                color: root.mutedForeground
                font.family: root.contentFontFamily
                font.pixelSize: Style.font.icon
              }

              Column {
                anchors.verticalCenter: parent.verticalCenter
                width: Math.max(Style.space(40), parent.width - appIcon.width - closeAction.width - parent.spacing * 2)
                spacing: 0

                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  text: String(row.modelData.title || row.modelData.class || "Untitled window")
                  color: root.contentForeground
                  font.family: root.contentFontFamily
                  font.pixelSize: Style.font.body
                  elide: Text.ElideRight
                }

                Text {
                  width: parent.width
                  visible: !!row.modelData.class
                  textFormat: Text.PlainText
                  text: String(row.modelData.class || "")
                  color: root.mutedForeground
                  font.family: root.contentFontFamily
                  font.pixelSize: Style.font.caption
                  elide: Text.ElideRight
                }
              }

              PanelActionButton {
                id: closeAction
                anchors.verticalCenter: parent.verticalCenter
                iconText: "󰅖" // MDI close
                tooltipText: "Close without restoring"
                foreground: root.contentForeground
                hoverColor: root.bar ? root.bar.urgent : Color.urgent
                onClicked: {
                  root.cursorIndex = row.index
                  root.dismissCursor()
                }
              }
            }
          }
        }
      }
    }
  }
}
