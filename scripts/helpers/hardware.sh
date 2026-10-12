#!/usr/bin/env bash

cpu_vendor_is() {
	local wanted=${1:?CPU vendor required}
	awk -F: -v wanted="$wanted" '
		/vendor_id/ {
			gsub(/[[:space:]]/, "", $2)
			exit($2 == wanted ? 0 : 1)
		}
		END { if (NR == 0) exit 1 }
	' /proc/cpuinfo
}

pci_vendor_present() {
	local wanted=${1:?PCI vendor ID required} vendor
	for vendor in /sys/bus/pci/devices/*/vendor; do
		[[ -r $vendor ]] || continue
		[[ $(<"$vendor") == "$wanted" ]] && return 0
	done
	return 1
}

dmi_matches() {
	local pattern=${1:?DMI pattern required} value file
	for file in /sys/class/dmi/id/sys_vendor /sys/class/dmi/id/product_name; do
		[[ -r $file ]] || continue
		value=$(<"$file")
		[[ ${value,,} == *${pattern,,}* ]] && return 0
	done
	return 1
}

usb_vendor_present() {
	local wanted=${1:?USB vendor ID required} vendor
	for vendor in /sys/bus/usb/devices/*/idVendor; do
		[[ -r $vendor ]] || continue
		[[ ${wanted,,} == $(tr '[:upper:]' '[:lower:]' <"$vendor") ]] && return 0
	done
	return 1
}
