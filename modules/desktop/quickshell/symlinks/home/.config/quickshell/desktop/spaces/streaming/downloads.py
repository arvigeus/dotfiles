"""Cancellable transfers, unchanged source audio, collision-safe media publication."""
import base64
import json
import os
from pathlib import Path
import re
import shutil

from mutagen.flac import Picture
from mutagen.oggopus import OggOpus

from spaces.books.jobs import check_cancelled, progress
from spaces.streaming.storage import StreamingError
from spaces.streaming.youtube import watch_url

# Rank all supported streams together using yt-dlp's quality/codec ordering.
# Opus is repackaged into Ogg; AAC stays in M4A. Neither path encodes audio.
AUDIO_FORMAT = r"bestaudio[acodec~='^(opus$|mp4a\.40\.|aac$)']"


def probe_media(commands, ffprobe, path):
    try:
        return json.loads(commands.run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]))
    except ValueError:
        raise StreamingError("The downloaded file could not be verified.") from None


def filename(value, limit=70):
    value = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]', "_", str(value)).strip(" .") or "Unknown"
    while len(value.encode()) > limit:
        value = value[:-1]
    return value


def publish(source, directory, stem):
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(1, 10001):
        destination = directory / (stem + (f" ({index})" if index > 1 else "") + source.suffix)
        try:
            # Staging is on this filesystem. link() publishes atomically without overwriting.
            os.link(source, destination)
            return destination
        except FileExistsError:
            continue
    raise StreamingError("Too many files share this download's name.")


def download(commands, item, directory, audio=False):
    directory.mkdir(parents=True, exist_ok=True)
    with commands.staging(directory) as stage:
        output = []

        def receive(line):
            if line.startswith("__progress__"):
                try:
                    data = json.loads(line[len("__progress__"):])
                    progress(done=int(data.get("downloaded_bytes") or 0),
                             total=int(data.get("total_bytes") or data.get("total_bytes_estimate") or 0),
                             detail="Downloading…" if data.get("status") != "finished" else "Processing media…")
                except (ValueError, TypeError):
                    pass
            elif line.startswith("__file__"):
                try:
                    output.append(Path(json.loads(line[len("__file__"):])))
                except (ValueError, TypeError):
                    raise StreamingError("The download returned an unreadable file path.") from None

        args = ["--newline", "--progress", "--progress-template", "download:__progress__%(progress)j",
                "--print", "after_move:__file__%(filepath)j", "--no-simulate", "--no-overwrites",
                "--embed-metadata", "-o", str(stage / "media.%(ext)s")]
        if audio:
            args += ["-f", AUDIO_FORMAT, "--write-thumbnail", "--convert-thumbnails", "jpg"]
        else:
            args += ["-f", "bv*+ba/b", "--merge-output-format", "mkv", "--remux-video", "mkv",
                     "--write-subs", "--sub-langs", "en.*,en", "--embed-subs"]
        commands.ytdlp([*args, "--", watch_url(item["id"])], timeout=6 * 3600, on_line=receive)
        check_cancelled()
        if len(output) != 1 or output[0].parent.resolve() != stage.resolve() or not output[0].is_file() or output[0].is_symlink():
            raise StreamingError("The download did not produce a complete media file.")
        source = output[0]
        progress(detail="Verifying audio…" if audio else "Verifying video…", done=0, total=0)
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            raise StreamingError("Install FFmpeg to verify downloads.")
        if audio:
            original = probe_media(commands, ffprobe, source)
            original_audio = [s for s in original.get("streams", []) if s.get("codec_type") == "audio"]
            if len(original_audio) != 1 or original_audio[0].get("codec_name") not in ("opus", "aac"):
                raise StreamingError("The download has no supported Opus or AAC audio stream.")
            codec = original_audio[0]["codec_name"]
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                raise StreamingError("Install FFmpeg to tag audio downloads.")
            tagged = stage / ("tagged.opus" if codec == "opus" else "tagged.m4a")
            command = [ffmpeg, "-nostdin", "-v", "error", "-n", "-i", str(source)]
            cover = stage / "media.jpg"
            has_cover = cover.is_file() and not cover.is_symlink()
            if has_cover and codec == "aac":
                command += ["-i", str(cover), "-map", "0:a:0", "-map", "1:v:0", "-map_metadata", "0", "-c", "copy", "-disposition:v:0", "attached_pic"]
            else:
                command += ["-map", "0:a:0", "-map_metadata", "0", "-c", "copy"]
            for key, value in {"title": item["title"], "artist": item["artist"], "album": item["album"],
                               "date": item["date"], "comment": watch_url(item["id"])}.items():
                if value:
                    command += ["-metadata", key + "=" + value]
                    if codec == "opus":
                        command += ["-metadata:s:a:0", key + "=" + value]
            commands.run([*command, str(tagged)])
            if has_cover and codec == "opus":
                # Ogg stores pictures in Vorbis comments, not a video stream.
                picture = Picture()
                picture.type = 3
                picture.mime = "image/jpeg"
                picture.data = cover.read_bytes()
                tags = OggOpus(tagged)
                tags["metadata_block_picture"] = [base64.b64encode(picture.write()).decode("ascii")]
                tags.save()
            source = tagged
        probe = probe_media(commands, ffprobe, source)
        streams = probe.get("streams") or []
        if audio:
            checked_audio = [s for s in streams if s.get("codec_type") == "audio"]
            if (len(checked_audio) != 1 or any(checked_audio[0].get(key) != original_audio[0].get(key)
                    for key in ("codec_name", "sample_rate", "channels"))):
                raise StreamingError("The downloaded audio's original format could not be preserved.")
            tags = {k.lower(): v for k, v in checked_audio[0].get("tags", {}).items()}
            tags.update({k.lower(): v for k, v in probe.get("format", {}).get("tags", {}).items()})
            if any(tags.get(key) != item[key] for key in ("title", "artist", "album")):
                raise StreamingError("The downloaded audio's tags could not be verified.")
            if has_cover and not any(s.get("disposition", {}).get("attached_pic") for s in streams):
                raise StreamingError("The downloaded audio's cover could not be verified.")
            date = item["date"]
            if re.fullmatch(r"\d{8}", date):
                date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
            stem = " - ".join(filename(item[key], 60) for key in ("title", "artist", "album")) + (f" ({filename(date, 10)})" if date else "")
        else:
            if not any(s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic") for s in streams):
                raise StreamingError("The download contains no playable video.")
            stem = filename(item["title"], 150) + " [" + item["id"] + "]"
        check_cancelled()
        destination = publish(source, directory, stem)
        # A committed file wins over a cancellation arriving after publication.
        return dict(path=str(destination), audio=audio, video=item)
