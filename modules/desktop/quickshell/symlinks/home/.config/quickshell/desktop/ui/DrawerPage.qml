import QtQuick
import Quickshell

// Each category owns its content and feature-local services. Bind discovery,
// subscriptions and timers to active, which becomes false as soon as input is
// released. The tree survives only the exit animation, then is destroyed. Keep
// persistent preferences and operations that must survive dismissal outside this
// transient tree; avoid eager service imports in the catalogue/host. A list-heavy
// page can supply its own virtualized view. screen is set before activation.
FocusScope {
    property bool active: false
    property ShellScreen screen: null
    property Item initialFocus: null
    property Component headerActions: null
    property string headerSubtitle: ""
    // An open popup can consume Escape before the host dismisses the page.
    property var escapeHandler: null
    signal closeRequested()
    signal drawerRequested(string key)
}
