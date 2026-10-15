.pragma library

function wifi(strength, enabled = true, connected = true) {
    if (!enabled) return "wifi-off";
    if (!connected || strength < 15) return "wifi-zero";
    return strength >= 70 ? "wifi" : strength >= 40 ? "wifi-high" : "wifi-low";
}
