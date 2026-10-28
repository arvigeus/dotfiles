import "../../ui"
import QtQuick
import QtQuick.Controls

// Keyboard and programmatic focus scroll into view; call wheelInput.reveal(item)
// to show anything else.
ScrollView {
    id: root

    // The wheel handler must sit in the moving content item to see wheels
    // before the Flickable. As a second child there it disables ScrollView's
    // implicit content size, so the declared child sizes the content instead.
    readonly property WheelScroll wheelInput: WheelScroll {
        view: root.contentItem as Flickable
        revealFocus: true
    }
    readonly property Item contentBody: {
        for (let i = 0; i < contentChildren.length; ++i)
            if (contentChildren[i] !== wheelInput)
                return contentChildren[i];
        return null;
    }
    contentWidth: contentBody?.implicitWidth ?? 0
    contentHeight: contentBody?.implicitHeight ?? 0

    ScrollBar.vertical: MovieScrollBar {}

    ScrollBar.horizontal: MovieScrollBar {}
}
