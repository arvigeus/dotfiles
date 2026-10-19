# GA402RK power policy

## Ownership

TuneD owns mode selection, platform policy, CPU governor, EPP and CPU boost.
`tuned-ppd` supplies the standard PowerProfiles D-Bus API, authorization, profile
holds, persistence and AC/battery mapping. asusd retains charging, lighting and
firmware fan management; automatic profile selection and linked EPP are disabled.
Its delegated PPT operations may reassert the already-selected platform.
The retired independent desktop boost helper and its polkit action are removed
by the power module's migration hook. No additional privileged UI helper exists.

Provisioning installs an ASUS configuration seed only when none exists. On
reapply it edits only the three profile/EPP ownership flags, preserving the
existing charge limit and other ASUS preferences. An unrecognized RON layout
fails without overwriting the file.

The shared profile deliberately does not inherit an upstream profile's changing
collection of settings. It uses `amd-pstate-epp`'s dynamic `powersave` governor,
profile-specific EPP, the existing ten-second audio timeout, and the kernel's
global CPUFreq boost interface. TuneD 2.28's CPU plug-in instead tries per-policy
boost writes, which return EINVAL on this machine. The native sysfs plug-in owns
the working global control, including verification and rollback. Platform
selection precedes CPU settings, which precede sysfs settings.

On this kernel, enabling global boost can leave `scaling_max_freq` at the
previous non-boost ceiling (3.301 GHz), despite a 4.937 GHz hardware ceiling.
A second native sysfs instance restores the driver's current legal ceiling
after boost selection. The common profile reads `cpuinfo_max_freq` at
apply/verify time; Performance then applies its measured 4.00 GHz ceiling.
GA402RK's homogeneous CPU policies report identical limits. The drawer checks
these limits as well as the boost flag. `power-study` records every policy's
minimum, maximum, hardware maximum and boost flag.

TuneD's PPD daemon persists the selected mode. `power-source.service` observes
UPower's `OnBattery` property through D-Bus: on an actual source edge, it replaces
Balanced/Powersave with Balanced on AC or Powersave on battery. Performance and
unrecognized profiles remain untouched. Manual daily-mode selections survive
until the next source edge, including deliberate Powersave on AC or Balanced on
battery. The first source read only seeds the baseline, preserving saved choices
at boot or service restart. Charging/charge-limit changes do not trigger selection.
The listener runs system-wide, independent of desktop drawers, Hyprland or Gaming
Mode, and writes only the public PPD property, followed by confirmed readback.
It has no hardware controls or polling loop. Its subscription is installed before
the initial read; systemd orders it after UPower and tuned-ppd and restarts it on
failure. Errors are visible in `journalctl -u power-source.service`.
Balanced still maps to a separate Quiet/power policy on battery for manual use.
Native AC/DC variants remain necessary for thermal-policy reapplication even
when the visible profile stays Performance.
Selection through `power-mode`, the drawer or another PPD client is equivalent.
Direct `asusctl profile`/sysfs changes bypass policy and are unsupported; the
drawer reports mismatches instead of displaying a requested label as proof that
all hardware controls applied. Reverse ACPI-to-PPD mapping is disabled because
Quiet cannot distinguish Balanced on battery from Powersave.

Systemd restarts either existing policy daemon after an unexpected failure.
The daemon's saved choice and native profile apply path restore controls; no
watchdog script periodically rewrites hardware state.

## Thermal delegation

The Performance profile limits CPU frequency to 4.00 GHz while retaining boost
above nominal frequency. The ASUS sustained APU and platform settings are 45 W
and 60 W. These are firmware controls, not measurements of laptop consumption.
Each mode maps to a distinct battery profile to force a native transition on
AC/DC changes;
firmware-reported lower maxima clamp the requested budgets (45/60 W on the
investigated battery setup). Balanced on AC requests 30/45 W; Balanced on battery
and Powersave request 25/40 W. Stock Balanced allowed greater GPU power than
the bounded Performance policy, so all modes require explicit thermal budgets.
Their nominal CPU ceiling avoids the substantially higher component power of
boosted all-core work; Performance measured about 20% more matrixprod throughput
at roughly 45 W versus 30 W on the 680M SMU socket-power readout with the dGPU
asleep. These are synthetic firmware-sensor comparisons, not pure CPU rail or
whole-laptop energy-per-task measurements.

ASUS couples custom fan mode and PPT writes. A root-owned TuneD script at
priority 50 in the common profile delegates these operations through asusd's typed public D-Bus API,
after platform, CPU, boost and frequency-limit settings. It programs earlier
fan response, enables the native PPT group, sets budgets, then checks actual
firmware values and every fan-curve point. It never polls or runs independently
of TuneD. The CPU curve reaches full command at 70 C to assist shared cooling;
the GPU curve reaches full command at 85 C. The daily-mode curves leave fans off
below 60 C at the EC input and ramp to full command at 85 C. ASUS requires enabled
manual fan curves to honor PPT controls. Exact points are declared in the
script and recorded in the study. EC temperature input can differ from CPU Tctl; the
experimental recorder measures both identified temperatures and fan RPM.

On unload, the script asks asusd to restore firmware PPT defaults and disable
the outgoing platform's manual curves before TuneD restores the prior platform. asusd
persists its native per-source/per-profile groups and handles resume/source
events. TuneD starts after asusd and replays its hook even when reapplying the
same platform, which otherwise disables custom fan mode without a change event.
The source listener selects through PPD; asusd never selects a competing profile.
If applying thermal policy fails,
TuneD's hook falls back to Quiet and boost disabled; its ordinary verification
and drawer readback expose the mismatch. Detailed drawer snapshots also check
the effective PPT limits and active fan mode without probing the dGPU.

The thermal script is restricted to GA402RK. Targets in the profile's
`variables` section are passed through TuneD's native environment and clamped
to firmware ranges. No active-profile-file race or duplicated target table is
needed in the helper. Reverting this policy requires removing its profile hook
and reapplying a stock profile.

Every override of the custom `sysfs_cpu_limits` section must repeat `type=sysfs`:
TuneD's native merger otherwise replaces that type with the section name and
skips the unknown plug-in. Native verification covers only loaded plug-ins; tests
exercise TuneD's actual merger.

## Session and application integration

The existing display service observes native PowerProfiles signals. Powersave
temporarily caps an enabled internal eDP panel to an advertised 60 Hz mode at
the current resolution. External displays, brightness, layout, scale and
rotation remain user-owned. The service retains the previous mode in session
state and restores it on exit only if the cap remains applied. An explicit
refresh edit overrides the cap until leaving Powersave or restarting the shell.
Automatic refresh
changes are excluded from saved display preferences. Reconfiguration restores
the user's saved setup before reapplying policy; modesets use existing readback
and rollback. Blank panels are not awakened for policy updates.
When leaving Powersave with a blank panel, its restoration remains pending.
Hypridle's existing wake hook turns displays on and notifies the display service,
which applies or restores the refresh rate then. No wake poller is added.
The final 60/120/60 Hz battery comparison supports a modest refresh saving;
session drift limits its precision. The smaller repeat difference was about
0.5 W, corroborated in direction by battery energy loss. See the study record
for all phases and the separate energy-counter estimates.

mpv provisioning on GA402RK selects OpenGL and `hwdec=auto-safe`, retaining
automatic codec/device discovery. The user-selected `generic-high` shader
default and other profiles remain available. `power-profiles.conf` adds native
Powersave profile with `profile-restore=copy-equal`; both Balanced and Performance
restore prior options instead of hard-coding over user customization. Only
Powersave applies a quality overlay; its removal retains options manually edited
while the overlay was active.

`dotfiles-power.lua` reads the active TuneD profile at player startup and listens
for a script message. It creates a unique IPC socket under the private user
runtime directory only when no existing socket is configured. A systemd user
path unit observes TuneD's profile file and invokes the unprivileged one-shot
`power-session` notifier. Application notification needs no polling or resident
process; the separate source listener only selects PPD modes. Multiple instances
have separate endpoints. Existing custom IPC sockets
are preserved; those players receive startup policy but automatic live changes
require the user to send `script-message dotfiles-power` on their own socket.
`script-opts=dotfiles-power-enabled=no` opts a player out.

Settings requiring graphics-context recreation are startup settings. In-session
changes adjust rendering quality, not the rendering device or firmware MUX.
No global graphics selector, GPU probing daemon, forced dGPU disable or MUX
switch is installed. Sleeping GPU telemetry is skipped before reading hwmon.

VLC quality remains application-managed; it has no corresponding public
rendering-profile API.

## Measurement and recovery

`power-study` is an explicit measurement tool, not part of normal policy. It
records power source, battery energy and flow, display state, CPU policy,
identified hwmon sensors, fan RPM and runtime-safe DRM telemetry. Records are
stored under `$XDG_STATE_HOME/dotfiles-power-study`. An optional child process
is terminated as a process group when the bounded run ends or a guard trips.
Invalid/guarded runs stop that group immediately; normal completion allows five
seconds of graceful cleanup before escalation. This prevents a GPU benchmark
that ignores SIGTERM from continuing to heat during a thermal abort.
Default experimental guards are CPU 82 C, GPU edge 80 C and GPU hotspot/memory
90 C when `--gpu-telemetry` is requested; they are conservative experiment limits,
not hardware shutdown limits. GPU stress workloads must use this option. Battery
trials observe runtime state without reading GPU sensors, even if the GPU is
already active: sensor reads can repeatedly reset its autosuspend delay.
Hardware protections are never changed.

Options precede the label; an optional workload follows it. `--until-stopped`
keeps sampling until SIGINT/SIGTERM instead of ending at `--duration`:

```sh
power-study --warmup 30 --duration 600 idle
power-study --until-stopped --warmup 0 desktop
power-study --gpu-telemetry --interval .5 --warmup 30 --duration 900 game -- GAME ARGUMENTS
power-mode powersave
tuned-adm active
tuned-adm verify
systemctl --user status power-session.path power-session.service
```

Changing AC state, mode or brightness invalidates the current comparison.
Thermal guards, interrupted sampling and changed display configuration are
reported explicitly. Sampling uses `CLOCK_BOOTTIME` so suspend time counts toward
gap detection. Summaries separate battery `power_now` statistics from
energy-delta power; neither APU PPT nor component estimates stand in for battery
discharge. Runtime projections are estimates, not measured full discharges.
Short synthetic runs cannot establish gaming stability.

Automated checks live in `tests/test_power_policy.py`, `test_power_drawers.py`,
`test_display_drawer.py`, `test_mpv_power.py` and generation tests. Source-policy
tests simulate UPower edges and daemon readback without hardware writes; the
native mpv test verifies Powersave restoration and preservation of manual edits.
Physical measurements and their
limits belong in [the study record](evidence/2026-10-18.md).
