pragma Singleton
import Quickshell

// Launch user-facing apps in their own systemd unit through uwsm. Children of
// the shell stay in desktop-shell.service's cgroup and die when it restarts.
// Helpers whose lifetime belongs to the shell keep using Process/execDetached.
Singleton {
    function command(argv): var { return ["uwsm", "app", "-t", "service", "--", ...argv]; }
    function launch(argv): void { Quickshell.execDetached(command(argv)); }
}
