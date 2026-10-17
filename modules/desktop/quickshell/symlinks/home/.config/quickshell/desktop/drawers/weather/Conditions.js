.pragma library

function description(code) {
    if (code === null || code === undefined) return qsTr("Unavailable");
    if (code === 0) return qsTr("Clear sky");
    if (code === 1) return qsTr("Mostly clear");
    if (code === 2) return qsTr("Partly cloudy");
    if (code === 3) return qsTr("Overcast");
    if ([45, 48].includes(code)) return qsTr("Fog");
    if ([51, 53, 55].includes(code)) return qsTr("Drizzle");
    if ([56, 57].includes(code)) return qsTr("Freezing drizzle");
    if ([61, 63, 65].includes(code)) return qsTr("Rain");
    if ([66, 67].includes(code)) return qsTr("Freezing rain");
    if ([71, 73, 75, 77].includes(code)) return qsTr("Snow");
    if ([80, 81, 82].includes(code)) return qsTr("Rain showers");
    if ([85, 86].includes(code)) return qsTr("Snow showers");
    if ([95, 96, 99].includes(code)) return qsTr("Thunderstorm");
    return qsTr("Unavailable");
}

function icon(code, day) {
    if (code === null || code === undefined) return "cloud";
    if (code <= 1) return day ? "sun" : "moon";
    if (code === 2) return day ? "cloud-sun" : "cloud";
    if ([45, 48].includes(code)) return "weather-fog";
    if ([71, 73, 75, 77, 85, 86].includes(code)) return "weather-snow";
    if ([95, 96, 99].includes(code)) return "weather-storm";
    if (code >= 51 && code <= 82) return "weather-rain";
    return "cloud";
}

function temperature(value) { return value === null || value === undefined ? "—" : Math.round(value) + "°"; }
function percent(value) { return value === null || value === undefined ? "—" : Math.round(value) + "%"; }
