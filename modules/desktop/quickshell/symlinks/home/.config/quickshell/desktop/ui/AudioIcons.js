.pragma library

function volume(percent, muted = false) {
    if (muted) return "volume-x";
    if (percent <= 0) return "volume";
    return percent <= 50 ? "volume-1" : "volume-2";
}
