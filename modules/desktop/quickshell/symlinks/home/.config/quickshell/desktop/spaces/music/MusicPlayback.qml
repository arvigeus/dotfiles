import QtQuick
import QtCore
import Quickshell.Io

// Owns the queue, player process and IPC polling for one retained Music Space.
Item {
    id: root
    objectName: "musicPlayback"
    visible: false
    required property var service
    required property var controller
    property bool active: false
    property string playMessage: ""
    property bool preparing: false
    property bool playFailed: false
    property string ipcPath: ""
    property string currentTrackKey: ""
    property var currentTrack: null
    property var playerProcess: null
    property var queueSongs: []
    property var shuffleHistory: []
    property var playHistory: []
    property int currentTrackIndex: -1
    property int playGeneration: 0
    property double position: 0
    property double duration: 0
    property double volume: 70
    property bool playerPollPending: false
    property bool playerPaused: true
    property bool shuffleEnabled: false
    property bool repeatAllEnabled: false
    property bool preferencesLoaded: false
    property string artworkUrl: ""

    Settings {
        id: preferences
        location: StandardPaths.writableLocation(StandardPaths.ConfigLocation) + "/quickshell/desktop/music-playback.ini"
        category: "Playback"
    }

    function savePreferences() {
        if (!preferencesLoaded)
            return;
        preferences.setValue("shuffleEnabled", shuffleEnabled);
        preferences.setValue("repeatAllEnabled", repeatAllEnabled);
        preferences.sync();
    }

    onShuffleEnabledChanged: {
        savePreferences();
        syncMprisState();
    }
    onRepeatAllEnabledChanged: {
        savePreferences();
        syncMprisState();
    }

    Component.onCompleted: {
        shuffleEnabled = preferences.value("shuffleEnabled", false) === true;
        repeatAllEnabled = preferences.value("repeatAllEnabled", false) === true;
        preferencesLoaded = true;
        syncMprisState();
    }

    Connections {
        target: root.service
        function onWorkerEvent(payload) {
            root.handleMprisEvent(payload);
        }
    }

    function canGoNext() {
        if (!currentTrack || currentTrackIndex < 0 || !queueSongs.length)
            return false;
        if (shuffleEnabled) {
            const unplayed = queueSongs.some((track, index) => index !== currentTrackIndex && !shuffleHistory.includes(index));
            return unplayed || (repeatAllEnabled && queueSongs.length > 0);
        }
        return currentTrackIndex + 1 < queueSongs.length || (repeatAllEnabled && queueSongs.length > 0);
    }

    function canGoPrevious() {
        if (!currentTrack || currentTrackIndex < 0)
            return false;
        if (position > 0)
            return true;
        return shuffleEnabled ? playHistory.length > 0 : currentTrackIndex > 0;
    }

    function syncMprisState() {
        if (!service)
            return;
        service.request("mpris-state", {
            state: {
                track: currentTrack ? {
                    title: currentTrack.title || currentTrack.name || "",
                    artistNames: currentTrack.artistNames || currentTrack.artist || "",
                    album: currentTrack.album || ""
                } : null,
                trackKey: currentTrackKey,
                artUrl: artworkUrl,
                playing: !!playerProcess && !playerPaused,
                paused: playerPaused,
                preparing: preparing,
                active: !!playerProcess,
                position: position,
                duration: duration,
                volume: volume,
                shuffleEnabled: shuffleEnabled,
                repeatAllEnabled: repeatAllEnabled,
                canNext: canGoNext(),
                canPrevious: canGoPrevious(),
                canSeek: !!playerProcess
            }
        }, () => {});
    }

    function setArtwork(url) {
        const value = String(url || "");
        if (artworkUrl === value)
            return;
        artworkUrl = value;
        syncMprisState();
    }

    function handleMprisEvent(payload) {
        if (!payload || payload.source !== "mpris")
            return;
        switch (payload.command) {
        case "next":
            if (canGoNext())
                playNext(false);
            break;
        case "previous":
            if (canGoPrevious())
                playPrevious();
            break;
        case "toggle":
            togglePause();
            break;
        case "play":
            if (playerPaused || !playerProcess)
                togglePause();
            break;
        case "pause":
            if (!playerPaused)
                togglePause();
            break;
        case "stop":
            stopPlayback();
            break;
        case "seek-by":
            seekTo(position + Number(payload.value || 0));
            break;
        case "seek-to":
            seekTo(Number(payload.value || 0));
            break;
        case "shuffle":
            shuffleEnabled = !!payload.value;
            break;
        case "repeat":
            repeatAllEnabled = !!payload.value;
            break;
        case "volume":
            changeVolume(Number(payload.value || 0) * 100);
            break;
        case "open-uri":
            controller.playUri(String(payload.value || ""));
            break;
        }
    }

    function recordKey(track) {
        return controller.recordKey(track);
    }

    function seekTo(value) {
        if (!ipcPath || !playerProcess)
            return;
        // Shown at once; the next poll confirms where mpv landed.
        position = Math.max(0, value);
        service.request("player-command", {
            ipcPath: ipcPath,
            action: "seek",
            value: value
        }, () => {});
        syncMprisState();
    }

    function changeVolume(value) {
        volume = Math.max(0, Math.min(100, Number(value) || 0));
        if (ipcPath && playerProcess)
            service.request("player-command", {
                ipcPath: ipcPath,
                action: "volume",
                value: value
            }, () => {});
        syncMprisState();
    }

    function togglePause() {
        if (!playerProcess) {
            if (currentTrack && currentTrackIndex >= 0)
                playTrackAt(currentTrackIndex);
            return;
        }
        if (!ipcPath)
            return;
        playerPaused = !playerPaused;
        syncMprisState();
        // mpv owns the state; MPRIS may have changed it while polling was off.
        service.request("player-command", {
            ipcPath: ipcPath,
            action: "toggle-pause"
        }, (result, failure) => {
            if (failure) {
                playFailed = true;
                playMessage = failure;
            }
        });
    }

    function playSongs(songs, index) {
        if (!Array.isArray(songs) || index < 0 || index >= songs.length)
            return;
        playHistory = [];
        queueSongs = songs.slice();
        shuffleHistory = [index];
        playTrackAt(index);
    }

    function playTrackAt(index, fromHistory) {
        if (!queueSongs.length || index < 0 || index >= queueSongs.length)
            return;
        const track = queueSongs[index];
        if (!track)
            return;
        if (!fromHistory && currentTrackIndex >= 0 && currentTrackIndex !== index)
            playHistory = playHistory.concat([currentTrackIndex]);
        if (!shuffleHistory.includes(index))
            shuffleHistory = shuffleHistory.concat([index]);
        const generation = ++playGeneration;
        const previousProcess = playerProcess;
        const previousIpcPath = ipcPath;
        playerProcess = null;
        ipcPath = "";
        if (previousProcess)
            previousProcess.destroy();
        if (previousIpcPath)
            service.request("player-cleanup", {
                ipcPath: previousIpcPath
            }, () => {});
        currentTrack = track;
        currentTrackKey = recordKey(track);
        currentTrackIndex = index;
        artworkUrl = "";
        position = 0;
        duration = Number(track.duration) || 0;
        playerPaused = false;
        preparing = true;
        playFailed = false;
        playMessage = "Loading " + (track.title || "song") + "…";
        syncMprisState();
        service.request("play", {
            track: track,
            volume: volume
        }, (result, failure) => {
            if (generation !== root.playGeneration) {
                if (result && result.ipcPath)
                    service.request("player-cleanup", {
                        ipcPath: result.ipcPath
                    }, () => {});
                return;
            }
            if (failure || !result || !Array.isArray(result.command)) {
                preparing = false;
                playFailed = true;
                playerPaused = true;
                playMessage = failure || "Could not resolve this song's stream.";
                syncMprisState();
                return;
            }
            const process = playerComponent.createObject(root, {
                playerCommand: result.command
            });
            if (!process) {
                preparing = false;
                playFailed = true;
                playerPaused = true;
                playMessage = "Could not start the audio player.";
                service.request("player-cleanup", {
                    ipcPath: result.ipcPath || ""
                }, () => {});
                syncMprisState();
                return;
            }
            ipcPath = result.ipcPath || "";
            playerProcess = process;
            preparing = false;
            playMessage = "Playing";
            syncMprisState();
        });
    }

    // code is null when the player never started.
    function playerExited(process, code) {
        if (playerProcess !== process)
            return;
        const completedTrack = currentTrack;
        const socketPath = ipcPath;
        playerProcess = null;
        ipcPath = "";
        process.destroy();
        if (socketPath)
            service.request("player-cleanup", {
                ipcPath: socketPath
            }, () => {});
        playerPaused = true;
        playFailed = false;
        position = 0;
        if (code === 0 && completedTrack && queueSongs.length > 0) {
            const hasUnplayedNext = shuffleEnabled ? shuffleHistory.length < queueSongs.length : currentTrackIndex + 1 < queueSongs.length;
            if (repeatAllEnabled || hasUnplayedNext) {
                playNext(true);
                return;
            }
            playMessage = "Queue finished.";
            syncMprisState();
            return;
        }
        playFailed = code !== 0;
        playMessage = code === 0 ? "Playback ended." : code === null ? "Could not start the audio player." : "The stream ended or could not be played.";
        syncMprisState();
    }

    function playNext(fromEnd) {
        if (!queueSongs.length)
            return;
        let nextIndex;
        if (shuffleEnabled && queueSongs.length > 1) {
            let candidates = queueSongs.map((track, index) => index).filter(index => index !== currentTrackIndex);
            candidates = candidates.filter(index => !shuffleHistory.includes(index));
            if (!candidates.length) {
                if (repeatAllEnabled) {
                    shuffleHistory = [currentTrackIndex];
                    candidates = queueSongs.map((track, index) => index).filter(index => index !== currentTrackIndex);
                } else if (!fromEnd) {
                    stopPlayback();
                    playMessage = "End of queue.";
                    return;
                } else {
                    playerPaused = true;
                    playMessage = "Queue finished.";
                    return;
                }
            }
            nextIndex = candidates[Math.floor(Math.random() * candidates.length)];
        } else {
            nextIndex = currentTrackIndex + 1;
        }
        if (nextIndex >= queueSongs.length) {
            if (!repeatAllEnabled && !fromEnd) {
                stopPlayback();
                playMessage = "End of queue.";
                return;
            }
            if (!repeatAllEnabled) {
                playMessage = "Queue finished.";
                return;
            }
            nextIndex = 0;
        }
        playTrackAt(nextIndex);
    }

    function playPrevious() {
        if (!queueSongs.length)
            return;
        if (position > 3) {
            seekTo(0);
            return;
        }
        let previous = Math.max(0, currentTrackIndex - 1);
        if (shuffleEnabled && playHistory.length) {
            previous = playHistory[playHistory.length - 1];
            playHistory = playHistory.slice(0, -1);
        }
        // At the start of the queue, Previous restarts the current song.
        if (previous === currentTrackIndex && playerProcess)
            seekTo(0);
        else
            playTrackAt(previous, true);
    }

    function stopPlayback() {
        ++playGeneration;
        const process = playerProcess;
        const socketPath = ipcPath;
        playerProcess = null;
        ipcPath = "";
        if (process)
            process.destroy();
        if (socketPath)
            service.request("player-cleanup", {
                ipcPath: socketPath
            }, () => {});
        playerPaused = true;
        position = 0;
        currentTrack = null;
        currentTrackKey = "";
        currentTrackIndex = -1;
        queueSongs = [];
        shuffleHistory = [];
        playHistory = [];
        preparing = false;
        playFailed = false;
        playMessage = "Playback stopped.";
        artworkUrl = "";
        syncMprisState();
    }

    Component.onDestruction: {
        const process = playerProcess;
        const socketPath = ipcPath;
        playerProcess = null;
        if (process)
            process.destroy();
        if (socketPath)
            service.request("player-cleanup", {
                ipcPath: socketPath
            }, () => {});
    }

    Timer {
        id: playerTimer
        objectName: "musicStatusTimer"
        interval: 650
        repeat: true
        running: !!root.playerProcess && !!root.ipcPath
        onTriggered: {
            if (root.playerPollPending)
                return;
            root.playerPollPending = true;
            const socketPath = root.ipcPath;
            service.request("player-state", {
                ipcPath: socketPath
            }, (result, failure) => {
                root.playerPollPending = false;
                if (socketPath !== root.ipcPath || failure || !result || !result.ready)
                    return;
                root.position = Number(result.position) || 0;
                root.duration = Number(result.duration) || root.duration;
                root.playerPaused = !!result.paused;
                // A poll racing mpv's exit has no volume; keep the listener's level.
                if (typeof result.volume === "number")
                    root.volume = result.volume;
                root.syncMprisState();
            });
        }
    }

    Component {
        id: playerComponent
        Process {
            id: streamPlayer
            property var playerCommand: []
            command: playerCommand
            running: true
            onExited: (code, status) => root.playerExited(streamPlayer, code)
            // A failed start emits no exited; after a real exit this is a no-op.
            onRunningChanged: if (!running)
                root.playerExited(streamPlayer, null)
        }
    }
}
