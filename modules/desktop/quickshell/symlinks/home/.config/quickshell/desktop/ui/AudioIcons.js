.pragma library

function volume(percent, muted = false) {
    if (muted) return "volume-x";
    if (percent <= 0) return "volume";
    return percent <= 50 ? "volume-1" : "volume-2";
}

// Percent of the loudest channel, matching pactl and pavucontrol. PwNodeAudio.volume
// is the channel average, so balanced levels would read lower than the mixer shows.
function level(audio) {
    const volumes = Array.from(audio?.volumes ?? []);
    return Math.round((volumes.length ? Math.max(...volumes) : audio?.volume ?? 0) * 100);
}
