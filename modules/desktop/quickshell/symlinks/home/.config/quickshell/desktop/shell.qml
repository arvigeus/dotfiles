pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Hyprland
import "ui"
import "bar"
import "launcher"
import "drawers"
import "drawers/clipboard"
import "drawers/displays"
import "drawers/power"

ShellRoot {
    id: root
    readonly property QtObject theme: Theme

    InteractionState { id: interactions }
    Launcher { id: launcher; interactionState: interactions }
    // The host owns category registration and lazy content; bar summaries do
    // not instantiate feature pages or start their helper processes. Feature-local
    // services, including detailed power telemetry, load with their drawers.
    // PowerSession owns one-time charging and recording lifetimes, with
    // supervised cleanup and no background sensor polling.
    // Audio test workers belong to the pages and stop on dismissal.
    // Bluetooth discovery and pending pairing also stop on dismissal.
    Drawers { id: drawers; interactionState: interactions }

    // WORKAROUND: Hyprland lacks geometry/order events; bindings.lua supplies them.
    // If the list order goes stale, check its layoutAction/release hooks and this
    // custom listener. Replace the paired workaround when native events suffice.
    // External reorder scripts: hyprctl dispatch 'hl.dsp.event("desktop-layout-changed")'
    // Capture continues while the drawer is closed; visible image rows load on demand.
    // Plain entry and debounced search use shared controls across drawers.
    Component.onCompleted: { layoutRefresh.restart(); ComfortService.start(); DisplayService.start(); PowerSession.start(); ClipboardService.start(); }

    Connections {
        target: Hyprland
        function onRawEvent(event: HyprlandEvent): void {
            DisplayService.handleEvent(event.name, event.data);
            if ((event.name === "custom" && event.data === "desktop-layout-changed")
                || ["openwindow", "closewindow", "activewindowv2", "movewindowv2",
                "changefloatingmode", "fullscreen", "workspacev2",
                "configreloaded", "monitoraddedv2", "monitorremoved"].includes(event.name))
                layoutRefresh.restart();
        }
    }

    Timer {
        id: layoutRefresh
        interval: 180
        onTriggered: Hyprland.refreshToplevels()
    }

    // Recovery for missed notification paths: uncomment this periodic fallback.
    // Kept disabled to avoid polling; prefer fixing the missing bindings.lua hook.
    // Timer {
    //     id: geometryRefresh
    //     interval: 1000
    //     repeat: true
    //     running: Hyprland.usingLua && Hyprland.toplevels.values.length > 1
    //     onTriggered: Hyprland.refreshToplevels()
    // }

    Variants {
        model: Quickshell.screens

        Bar {
            required property ShellScreen modelData
            screen: modelData
            onLauncherRequested: launcher.toggleOn(screen)
            onDrawerRequested: key => drawers.toggleDrawer(key, screen)
        }
    }
}
