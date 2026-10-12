# Zephyrus power management

Tuned owns platform profiles and CPU energy preferences. tuned-ppd exposes the
power-profiles API to desktop applications and switches the balanced profile
between AC and battery variants. asusd retains ASUS charging, fan and hardware
features, with automatic profile switching and linked EPP management disabled.

The custom profiles inherit Tuned's balanced profile. Power saver additionally
disables CPU boost.

Use `powerprofilesctl` to select desktop power modes and `tuned-adm active` to
inspect the corresponding Tuned profile. Use desktop power controls rather than
`asusctl profile` to keep Tuned's selected mode consistent.
