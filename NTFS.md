# NTFS

## Link to NTFS drive appears hidden (ubuntu: attr)

(replace `/mnt/d` with your drive)

```sh
sudo setfattr -h -v 0x00000000 -n system.ntfs_attrib_be /mnt/d
```

## Steam game on NTFS partition

Add `exec` option to `/etc/fstab` entry.

Example:

```txt
uid=1000,gid=1000,umask=0022,auto,rw,exec
```
