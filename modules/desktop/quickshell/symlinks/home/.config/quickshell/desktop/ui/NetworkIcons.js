.pragma library

// Signal bars shown by the Wi-Fi icon: 0 (none) to 3 (full).
function level(strength) {
    return strength >= 70 ? 3 : strength >= 40 ? 2 : strength >= 15 ? 1 : 0;
}

function wifi(strength, enabled = true, connected = true) {
    if (!enabled) return "wifi-off";
    if (!connected) return "wifi-zero";
    return ["wifi-zero", "wifi-low", "wifi-high", "wifi"][level(strength)];
}
