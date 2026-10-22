.pragma library

function compact(n, suffix, digits) {
    return n === null || n === undefined || !isFinite(n) ? "—" : value(n, suffix, digits);
}

function value(value, suffix, digits) {
    return value === null || value === undefined || !isFinite(value) ? qsTr("Unavailable")
        : Number(value).toLocaleString(Qt.locale(), "f", digits === undefined ? 0 : digits) + (suffix || "");
}
function bytes(value) {
    if (value === null || value === undefined) return qsTr("Unavailable");
    const units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let n = value, i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return Number(n).toLocaleString(Qt.locale(), "f", i > 0 ? 1 : 0) + " " + units[i];
}
function duration(seconds) {
    if (!(seconds > 0)) return qsTr("Estimating…");
    const minutes = Math.max(1, Math.round(seconds / 60));
    return minutes >= 60 ? qsTr("%1 h %2 min").arg(Math.floor(minutes / 60)).arg(minutes % 60) : qsTr("%1 min").arg(minutes);
}
function batteryState(state) {
    return ({1: qsTr("Charging"), 2: qsTr("Discharging"), 3: qsTr("Empty"), 4: qsTr("Fully charged"),
        5: qsTr("Not charging"), 6: qsTr("Waiting to discharge")})[state] || qsTr("State unavailable");
}
// UPowerDevice states: 1 charging, 2 discharging.
function seconds(device) {
    return !device ? 0 : device.state === 1 ? device.timeToFull : device.state === 2 ? device.timeToEmpty : 0;
}
function estimate(device) {
    if (!device) return "";
    const s = seconds(device);
    if (device.state === 1) return s > 0 ? qsTr("About %1 until full").arg(duration(s)) : qsTr("Estimating time to full…");
    if (device.state === 2) return s > 0 ? qsTr("About %1 remaining").arg(duration(s)) : qsTr("Estimating remaining time…");
    return "";
}
function profile(value) {
    return ({"power-saver": qsTr("Powersave"), balanced: qsTr("Balanced"), performance: qsTr("Performance")})[value] || qsTr("Unavailable");
}
function profileIcon(value) {
    return ({"power-saver": "leaf", balanced: "gauge", performance: "zap"})[value] || "gauge";
}
