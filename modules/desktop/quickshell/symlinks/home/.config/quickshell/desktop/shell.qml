import QtQml
import Quickshell
import "ui"
import "bar"

ShellRoot {
    readonly property QtObject theme: Theme

    Variants {
        model: Quickshell.screens

        Bar {
            required property ShellScreen modelData
            screen: modelData
        }
    }
}
