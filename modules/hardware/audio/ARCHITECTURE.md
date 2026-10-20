# Audio scheduling

PipeWire and WirePlumber use their upstream realtime module and RealtimeKit's
D-Bus service to obtain realtime scheduling without granting unrestricted
realtime privileges to the desktop user. The audio module explicitly installs
`rtkit`; D-Bus activates it on demand, so no enabled service or custom priority
override is needed. Existing processes must reconnect (normally at next login)
after installing the previously missing helper.

See [PipeWire's realtime module](https://docs.pipewire.org/page_module_rt.html).
