# Battery and Performance drawers

`BatteryDrawer.qml`, `PerformanceDrawer.qml` and this directory present native
UPower/PowerProfiles state and the shell-owned power actions. Mode definitions,
AC/DC selection, TuneD/ASUS policy and mpv integration belong to the
[power module](../../../../../../../../../hardware/power/ARCHITECTURE.md). The
Zephyrus charge-limit provider is described in the
[device integration](../../../../../../../../../hardware/devices/zephyrus/ARCHITECTURE.md#battery-care-and-performance).

## Sources of truth

UPower supplies batteries, peripherals, the aggregate display device and
`OnBattery`. Quickshell's `PowerProfiles` supplies the active mode, performance
availability, degradation and holds; the shell only reads it.

Quickshell 0.3.2's `PowerProfiles.profile` setter stores the new value before
its asynchronous D-Bus write and never reverts or re-reads it on failure.
TuneD-PPD emits `ActiveProfile` only after a successful switch. Mode buttons
therefore send `{"op": "profile"}` to `session.py`, which sets PPD's
`ActiveProfile` (15 s timeout, as for `power-mode`) and reads it back. The
selected button, bar icon and Powersave refresh cap follow PPD's confirmed
property. Buttons are disabled while any session action is pending, so clicks
cannot queue switches whose later confirmations overwrite each other.

Without a PowerProfiles service (the VM host), Quickshell still reports Balanced.
The session helper checks once at startup whether the name is owned or
activatable, matching Quickshell's own startup read. `modesAvailable: false`
hides the modes; `null` (unchecked or failed check) keeps them.

## PowerService

`backend.py` runs only while a drawer observes it: every 10 s for charge-limit
providers, and every 2 s with telemetry and policy readback while Performance is
open. The helper exits after the last observer leaves. A refresh during that
stop restarts it (Quickshell restarts a process whose stop is still pending).

Policy readback covers `zephyrus-*` TuneD profiles only. It follows
`[main] include` in TuneD's merge order (includes first, then the profile) under
`/etc/tuned/profiles`. It compares the platform profile, EPP, governor, global
boost and frequency ceiling, plus ASUS PPT values and custom fan mode. A missing
include or option reports an incomplete policy. TuneD writes `active_profile`
before its worker thread applies the profile. AC/DC changes can apply twice
as TuneD-PPD resolves the battery variant and `power-source` selects the daily
mode. Readback skips the first 5 s after that file changes.

Telemetry never reads sensors on runtime-suspended devices or their parents.
The generic hwmon loop skips display-class (PCI `0x03`) chips whatever their
driver. GPU sensors are read only by the GPU sampler. With runtime PM `auto`, it
samples at most every autosuspend delay plus 1 s (minimum 8 s), leaving the
device time to suspend. GPU names come from `product_name` or a targeted
`pci.ids` lookup. There is no NVML, `nvidia-smi` or render-node access. The CPU
name is read once per helper run.

## PowerSession

`session.py` starts with the shell and lives for its lifetime. It receives one
JSON request per line and writes one state line per request, plus unsolicited
lines at startup and when a recording ends. Only replies to actions set
`reply: true`, which `PowerSession` counts as pending work. `power` reports
forward UPower's `OnBattery`, or null without a ready laptop battery.
Operations: `power`, `profile`, `charge-limit`, `charge-once`,
`restore-charge`, `record`, `stop-recording`.

QProcess SIGKILLs its direct child on reload, so that child is an idle
supervisor. The `setsid` session child sees stdin EOF, or a closed stdout while
a request is running, and then stops its recorder and saves. A flock on
`session.lock` keeps one generation at a time. A new generation that finds the
lock held exits, and `PowerSession` retries after 5 s.

Charge once writes its restoration intent (provider key, previous limit, boot
ID) to `session.json` before setting 100%. It restores on unplug, on request or
after a reboot. A limit changed elsewhere wins, and a failed readback keeps the
intent only if the hardware actually changed.

Recording runs `power-study --until-stopped --warmup 0 --interval 2` into this
state directory. It ends on Stop, on shell exit, or when power-study detects a
policy, AC, brightness or display change or a sampling gap. power-study marks
signal-ended runs `interrupted`, so only an abort reason or a missing summary is
shown as a warning. power-study keeps every sample in memory until the summary
(about 11 KB per sample on GA402RK, roughly 19 MiB per hour). The drawer sets no
time limit.
