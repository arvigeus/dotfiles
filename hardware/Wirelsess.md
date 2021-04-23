# Wireless Card

## Qualcomm Atheros QCA6174 (ath10k_pci)

```shell
$ lspci | grep -i net

05:00.0 Network controller: Qualcomm Atheros QCA6174 802.11ac Wireless Network Adapter (rev 32)

```

```shell
$ iwconfig

wlp5s0    IEEE 802.11  ESSID:"Rogue Router"  
          Mode:Managed  Frequency:2.412 GHz  Access Point: 88:AD:43:FA:CC:00
          Bit Rate=1 Mb/s   Tx-Power=20 dBm
          Retry short limit:7   RTS thr:off   Fragment thr:off
          Power Management:off
          Link Quality=55/70  Signal level=-55 dBm  
          Rx invalid nwid:0  Rx invalid crypt:0  Rx invalid frag:0
          Tx excessive retries:0  Invalid misc:96   Missed beacon:0

```

### Complete info

```sh
wget -N -t 5 -T 10 https://github.com/UbuntuForums/wireless-info/raw/master/wireless-info && chmod +x wireless-info && ./wireless-info
```

## Disable power management

```shell
sudo nano /etc/NetworkManager/conf.d/default-wifi-powersave-on.conf
```

Change `wifi.powersave` to 2 ([see more](https://gist.github.com/jcberthon/ea8cfe278998968ba7c5a95344bc8b55)).

```text
[connection]
wifi.powersave = 2
```

Reboot for the change to take effect.

Execute `iwconfig` and ensure that `Power Management:off`.
