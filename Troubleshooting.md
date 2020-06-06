# Troubleshooting

## Link to NTFS drive appears hidden (ubuntu: attr)

(replace `/mnt/d` with your drive)

```sh
sudo setfattr -h -v 0x00000000 -n system.ntfs_attrib_be /mnt/d
```
