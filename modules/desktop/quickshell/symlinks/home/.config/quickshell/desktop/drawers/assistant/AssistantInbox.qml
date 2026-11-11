import Quickshell.Io

IpcHandler {
    target: "assistant"

    function addFiles(payload: string): string {
        try {
            if (payload.length > 96 * 1024)
                return qsTr("These file paths are too long to add in one selection.");
            const urls = JSON.parse(payload).files;
            if (!Array.isArray(urls) || urls.length < 1 || urls.length > 6)
                return qsTr("Select between one and six files to add to Assistant.");
            if (!urls.every(url => typeof url === "string" && /^file:\/\/(?:localhost)?\//.test(url)))
                return qsTr("Only local files can be added to Assistant.");
            return AssistantService.attachUrls(urls, true) ? "" : AssistantService.attachmentError;
        } catch (_) {
            return qsTr("Could not read the selected files.");
        }
    }
}
