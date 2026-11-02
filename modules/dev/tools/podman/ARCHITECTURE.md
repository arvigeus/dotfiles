# Container storage

The module includes `fuse-overlayfs` for rootless overlay storage, including
Btrfs-backed home directories. Podman selects the installed helper with its
default storage configuration; no driver or graphroot override is managed here.

Validate storage changes with `podman info` and `docker image ls` as the regular
user. Adding this dependency does not require resetting or replacing container
storage.
