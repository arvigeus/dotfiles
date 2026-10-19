import QtQuick

InputField {
    id: root

    property int debounceInterval: 300
    signal searchRequested(string query)

    function submit(): void {
        debounce.stop();
        searchRequested(text);
    }

    onTextEdited: debounce.restart()
    onCleared: {
        debounce.stop();
        searchRequested("");
    }

    Timer {
        id: debounce
        interval: Math.max(0, root.debounceInterval)
        onTriggered: root.searchRequested(root.text)
    }
}
