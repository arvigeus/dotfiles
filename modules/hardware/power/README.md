# Zephyrus power management

Choose Performance, Balanced or Powersave in the Performance drawer, or use
`power-mode performance|balanced|powersave`. Run `power-mode` to read the mode.
The bar's Performance icon follows the active mode. Plugging in selects Balanced;
unplugging selects Powersave. Performance stays selected across both changes.
You can choose another mode manually until the next power-source change.

| Mode | CPU and power budgets | Cooling | Display and mpv quality | Plug / unplug |
| --- | --- | --- | --- | --- |
| **Powersave** | Efficiency preference, boost off; Quiet firmware profile; **25 W APU / 40 W platform**. | Fans off through 60°C, ramping to full at 85°C. | Internal panel capped at **60 Hz**; basic scaling, shaders/interpolation/debanding off. | Plug → **Balanced**. Unplug → **Powersave**. |
| **Balanced** | Boost off. **AC:** balanced preference and firmware profile, **30/45 W**. **Battery (manual choice):** efficiency preference, Quiet, **25/40 W**. | Same fan curve as Powersave. | Your refresh rate and configured mpv quality. | Plug → **Balanced**. Unplug → **Powersave**. |
| **Performance** | Performance preference and firmware profile; boost on with a **4.00 GHz** ceiling; **45/60 W**. | Earlier, stronger cooling; CPU fan reaches full command at 70°C, GPU fan at 85°C. | Your refresh rate and configured mpv quality. | Stays **Performance** on either source. |

Budgets are APU/platform firmware limits, not laptop consumption; firmware may
clamp them on battery. Fan temperatures use the firmware's control sensor and
can differ from the displayed CPU temperature.

Changing refresh rate yourself overrides Powersave's cap until you leave
Powersave or restart the shell. Your brightness and external-display settings
remain yours.

Leaving Powersave restores your mpv quality settings in both Balanced and
Performance. New players use the efficient OpenGL/hardware-decoding path;
an already running player keeps its renderer until restarted.
VLC keeps its own playback settings in every mode.

Battery charge limits remain separate in the Battery drawer. A worn battery's
reduced capacity limits runtime independently of the power mode.

See [architecture and verification](ARCHITECTURE.md) for ownership, application
compatibility, measurements and recovery details.
