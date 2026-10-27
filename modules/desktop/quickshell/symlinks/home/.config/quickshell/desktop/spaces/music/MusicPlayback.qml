import QtQuick
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
    property string queueScopeKey: ""
    property int currentTrackIndex: -1
    property int playGeneration: 0
    property double position: 0
    property double duration: 0
    property double volume: 70
    property bool playerPollPending: false
    property bool playerPaused: true
    property bool shuffleEnabled: false
    property bool repeatAllEnabled: false

    function recordKey(track) {
        return controller.recordKey(track);
    }
    function songScopeKey() {
        return controller.songScopeKey();
    }

    function seekTo(value) {
        if (!ipcPath || !playerProcess)
            return;
        service.request("player-command", {
            ipcPath: ipcPath,
            action: "seek",
            value: value
        }, () => {});
    }

    function changeVolume(value) {
        volume = value;
        if (ipcPath && playerProcess)
            service.request("player-command", {
                ipcPath: ipcPath,
                action: "volume",
                value: value
            }, () => {});
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
        service.request("player-command", {
            ipcPath: ipcPath,
            action: "pause",
            value: playerPaused
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
        queueScopeKey = songScopeKey();
        shuffleHistory = [index];
        playTrackAt(index);
    }

    function playTrackAt(index, fromHistory) {
        if (!queueSongs.length || index < 0 || index >= queueSongs.length)
            return;
        const track = queueSongs[index];
        if (!track)
            return;
        if (recordKey(track) === currentTrackKey && playerProcess) {
            togglePause();
            return;
        }
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
        position = 0;
        duration = Number(track.duration) || 0;
        playerPaused = false;
        preparing = true;
        playFailed = false;
        playMessage = "Loading " + (track.title || "song") + "…";
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
                return;
            }
            ipcPath = result.ipcPath || "";
            playerProcess = process;
            preparing = false;
            playMessage = "Playing";
        });
    }

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
            return;
        }
        playFailed = code !== 0;
        playMessage = code === 0 ? "Playback ended." : "The stream ended or could not be played.";
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
        if (shuffleEnabled && playHistory.length) {
            const previous = playHistory[playHistory.length - 1];
            playHistory = playHistory.slice(0, -1);
            playTrackAt(previous, true);
        } else
            playTrackAt(Math.max(0, currentTrackIndex - 1), true);
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
        queueScopeKey = "";
        shuffleHistory = [];
        playHistory = [];
        preparing = false;
        playFailed = false;
        playMessage = "Playback stopped.";
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
        running: root.active && !!root.playerProcess && !!root.ipcPath
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
                root.volume = Number(result.volume) || 0;
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
        }
    }
}
