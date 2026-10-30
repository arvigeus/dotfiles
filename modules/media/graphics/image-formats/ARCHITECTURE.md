# Qt image formats

This module owns shared image-format support for Qt applications, including Koko
and Dolphin's image thumbnailer. `kimageformats` supplies the HEIC/HEIF Qt plugin;
its optional `libheif` backend is explicit so a fresh installation can decode
those files. libheif's package dependencies provide HEVC decoding.
`qt6-imageformats` supplies additional formats such as TIFF and TGA.

The existing Koko MIME defaults include `image/heic` and `image/heif`. Dolphin's
`kio-extras` image thumbnailer uses the same Qt readers, so no separate HEIC
thumbnailer, conversion hook or MIME override is needed. Restart applications
that were running before the plugins were installed.

Validate with `QImageReader.supportedImageFormats()` and decode representative
HEIC files through `QImageReader`, then request a thumbnail through KIO's native
preview job. Read image data without modifying the original files.
