import QtQuick
import "../movies"

ArtworkCard {
    required property string payload
    required property int index
    readonly property var wallpaper: JSON.parse(payload)
    text: wallpaper.title || (wallpaper.providerName || "Wallhaven") + " · " + wallpaper.id
    subtitle: wallpaper.resolution || ""
    imageSource: wallpaper.thumbLarge || wallpaper.preview || ""
    fallbackIcon: "image"
}
