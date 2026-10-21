//@ pragma UseQApplication
//@ pragma IconTheme Adwaita
pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Services.SystemTray
import "ui"
import "bar"
import "launcher"
import "drawers"
import "drawers/clipboard"
import "drawers/displays"
import "drawers/power"
import "drawers/capture"
import "drawers/events"
import "drawers/notifications"

ShellRoot {
    id: root
    readonly property QtObject theme: Theme
    // Register the tray host for the session, including while its drawer is closed.
    readonly property var systemTray: SystemTray

    InteractionState { id: interactions }
    Launcher { id: launcher; interactionState: interactions }
    // The host owns category registration and lazy content; bar summaries do
    // not instantiate feature pages or start their helper processes. Feature-local
    // services, including detailed power telemetry, load with their drawers.
    // PowerSession owns one-time charging and recording lifetimes, with
    // supervised cleanup and no background sensor polling.
    // Audio test workers belong to the pages and stop on dismissal.
    // CaptureService attaches to the recording owner and retains screenshot
    // preferences/countdowns; camera controls
    // belong to the drawer and preview streams stop as soon as it is dismissed.
    // Bluetooth discovery and pending pairing also stop on dismissal.
    // CalendarService warms private snapshots quietly and keeps pending writes alive.
    Drawers { id: drawers; interactionState: interactions }
    NotificationPopups {}
    Binding {
        target: NotificationCenter; property: "drawerOpen"
        value: drawers.opened && drawers.currentDrawer?.key === "notifications"
    }

    // WORKAROUND: Hyprland lacks geometry/order events; bindings.lua supplies them.
    // If the list order goes stale, check its layoutAction/release hooks and this
    // custom listener. Replace the paired workaround when native events suffice.
    // External reorder scripts: hyprctl dispatch 'hl.dsp.event("desktop-layout-changed")'
    // Capture continues while the drawer is closed; visible image rows load on demand.
    // Plain entry and debounced search use shared controls across drawers.
    Component.onCompleted: { layoutRefresh.restart(); ComfortService.start(); DisplayService.start(); PowerSession.start(); ClipboardService.start(); CaptureService.start(); CalendarService.start(); NotificationCenter.start(); }

    GlobalShortcut {
        appid: "desktop"; name: "record-region"
        description: qsTr("Record an area or stop the current recording")
        onPressed: CaptureService.recordRegion()
    }

    Connections {
        target: CaptureService
        function onHideRequested(): void { drawers.dismiss(); launcher.dismiss(); }
    }
    Connections {
        target: interactions
        function onActiveSurfaceChanged(): void {
            if (interactions.activeSurface) CaptureService.guardDismissal();
        }
    }

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
