import QtQuick
import QtQuick.Controls
import "../../ui"

Button {
    id: root
    property string iconName: ""
    property string hint: text
    property color iconColor: Theme.muted
    implicitWidth: Theme.controlHeight
    implicitHeight: Theme.controlHeight
    padding: 8
    hoverEnabled: true
    Accessible.name: text
    opacity: enabled ? 1 : 0.4
    contentItem: Icon { name: root.iconName; color: root.hovered || root.visualFocus ? Theme.accent : root.iconColor }
    background: ButtonBackground { highlighted: root.hovered || root.visualFocus || root.checked; pressed: root.down }
    PassiveToolTip { target: root; text: root.hint; maximumLineCount: 20 }
}
