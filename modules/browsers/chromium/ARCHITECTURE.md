# Chromium web-app policy

Modules declare native policy objects in `extra.browsers.chromium.web_apps`.
Generation merges the lists; the setup script publishes them as
`WebAppInstallForceList` in `/etc/chromium/policies/managed/web-apps.json`.
Chromium owns installation and OS integration when a regular profile starts.

Use the upstream [policy schema](https://github.com/chromium/chromium/blob/main/components/policy/resources/templates/policy_definitions/Miscellaneous/WebAppInstallForceList.yaml)
for supported fields.
