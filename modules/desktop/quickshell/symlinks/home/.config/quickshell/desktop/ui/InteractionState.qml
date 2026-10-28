import QtQuick
import Quickshell

Scope {
    id: root

    // One owner for every interactive surface, across all outputs. The drawer
    // host, launcher and Space host share ownership; there is no navigation stack.
    property QtObject activeSurface: null
    property ShellScreen screen: null

    function open(surface: QtObject, output: ShellScreen): void {
        if (!surface || !Quickshell.screens.includes(output))
            return;
        if (activeSurface === surface && screen === output)
            return;
        // Release input ownership before changing output or opening another surface.
        activeSurface = null;
        screen = output;
        activeSurface = surface;
    }

    function toggle(surface: QtObject, output: ShellScreen): void {
        if (!Quickshell.screens.includes(output))
            return;
        if (activeSurface === surface && screen === output)
            dismiss(surface);
        else
            open(surface, output);
    }

    function dismiss(surface: QtObject): void {
        // A delayed callback from an old surface must not close its replacement.
        if (activeSurface !== surface)
            return;
        activeSurface = null;
        screen = null;
    }

    Connections {
        target: Quickshell
        function onScreensChanged(): void {
            if (root.activeSurface && !Quickshell.screens.includes(root.screen))
                root.dismiss(root.activeSurface);
        }
    }
}
