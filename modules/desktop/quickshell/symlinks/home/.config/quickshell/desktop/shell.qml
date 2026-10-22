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
    // Register the tray host for the session, including while its drawer is closed.
    readonly property var systemTray: SystemTray

    InteractionState { id: interactions }
    Launcher { id: launcher; interactionState: interactions }
    Drawers { id: drawers; interactionState: interactions }
    NotificationPopups {}
    Binding {
        target: NotificationCenter; property: "drawerOpen"
        value: drawers.opened && drawers.currentDrawer?.key === "notifications"
    }

    // Session-wide services that must run before any drawer opens.
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

    // WORKAROUND: Hyprland lacks window geometry/order events, so bindings.lua
    // dispatches the custom "desktop-layout-changed" event after layout actions.
    // If the window list order goes stale, check those hooks. External reorder
    // scripts: hyprctl dispatch 'hl.dsp.event("desktop-layout-changed")'
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
