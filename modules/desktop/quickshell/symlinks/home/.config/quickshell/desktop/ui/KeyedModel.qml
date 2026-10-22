import QtQml
import QtQml.Models
import "Models.js" as Models

// Keep delegates and their focus while updating and reordering plain snapshots.
ListModel {
    id: root
    dynamicRoles: true
    property var values: []
    property string keyField: "key"
    onValuesChanged: Models.sync(root, values, keyField, "modelData")
    onKeyFieldChanged: Models.sync(root, values, keyField, "modelData")
    Component.onCompleted: Models.sync(root, values, keyField, "modelData")
}
