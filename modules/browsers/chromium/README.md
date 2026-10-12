# Chromium web apps

Modules declare native policy objects in `extra.browsers.chromium.web_apps`.
Generation combines the lists, and the Chromium script writes them as
`WebAppInstallForceList` in `/etc/chromium/policies/managed/web-apps.json`.

Chromium installs these apps when a regular profile starts with network access,
using its native web-app installation and OS integration. They open in separate
windows, share the Chromium profile, and do not create desktop-folder shortcuts.
Managed apps cannot be uninstalled through the browser while declared by policy.
Inspect installation and policy status at `chrome://apps` and `chrome://policy`.

Reference:
https://github.com/chromium/chromium/blob/main/components/policy/resources/templates/policy_definitions/Miscellaneous/WebAppInstallForceList.yaml
