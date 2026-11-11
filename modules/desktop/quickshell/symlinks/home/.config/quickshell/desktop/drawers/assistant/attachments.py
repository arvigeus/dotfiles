"""Freeze bounded local attachments for the drawer; never fetch remote URLs."""

import base64
import hashlib
import io
import os
from pathlib import Path
import resource
import stat
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile

MAX_FILES = 6
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_CONTEXT_BYTES = 24 * 1024 * 1024
MAX_TEXT = 64000
MAX_CONTEXT_TEXT = 160000
IMAGE_FORMATS = {
    'png',
    'jpeg',
    'jpg',
    'webp',
    'gif',
    'bmp',
    'tiff',
    'tif',
    'avif',
    'heic',
    'heif',
    'jxl',
}
_app = None


def local_path(value):
    if not isinstance(value, str) or not value:
        raise ValueError('Invalid local file path.')
    parsed = urlsplit(value)
    if parsed.scheme:
        if parsed.scheme != 'file' or parsed.netloc not in ('', 'localhost'):
            raise ValueError('Attach a local file; remote URLs are not downloaded.')
        value = unquote(parsed.path)
    return Path(value).expanduser()


def read_file(path):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Only regular files can be attached.')
        if info.st_size > MAX_FILE_BYTES:
            raise ValueError('Files must be 16 MB or smaller.')
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError('Files must be 16 MB or smaller.')
    return data


def image_snapshot(name, data):
    from PySide6.QtCore import (
        QBuffer,
        QByteArray,
        QCoreApplication,
        QIODevice,
        QSize,
        Qt,
    )
    from PySide6.QtGui import QImage, QImageReader, QPainter

    global _app
    _app = QCoreApplication.instance() or QCoreApplication([])
    source = QBuffer()
    source.setData(QByteArray(data))
    source.open(QIODevice.ReadOnly)
    reader = QImageReader(source)
    kind = bytes(reader.format()).decode().lower()
    if kind not in IMAGE_FORMATS:
        return None
    QImageReader.setAllocationLimit(128)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > 40000000:
        raise ValueError('Image dimensions are too large (maximum 40 megapixels).')
    reader.setAutoTransform(True)
    if max(size.width(), size.height()) > 2048:
        reader.setScaledSize(size.scaled(QSize(2048, 2048), Qt.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        raise ValueError('Could not decode this image.')
    # Some plugins ignore scaled decoding. Enforce the output bound as well.
    if max(image.width(), image.height()) > 2048:
        image = image.scaled(2048, 2048, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    output = QBuffer()
    output.open(QIODevice.WriteOnly)
    if not image.save(output, 'PNG'):
        raise ValueError('Could not prepare this image.')
    mime = 'image/png'
    if output.size() > MAX_IMAGE_BYTES:
        flattened = QImage(image.size(), QImage.Format_RGB32)
        flattened.fill(Qt.white)
        painter = QPainter(flattened)
        painter.drawImage(0, 0, image)
        painter.end()
        output.close()
        output.setData(QByteArray())
        output.open(QIODevice.WriteOnly)
        if not flattened.save(output, 'JPEG', 88):
            raise ValueError('Could not prepare this image.')
        mime = 'image/jpeg'
    encoded = bytes(output.data())
    if len(encoded) > MAX_IMAGE_BYTES:
        raise ValueError('This image is too large after resizing.')
    return dict(
        kind='image',
        data=f'data:{mime};base64,' + base64.b64encode(encoded).decode(),
        size=len(encoded),
        width=image.width(),
        height=image.height(),
    )


def output_limit():
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_BYTES, MAX_FILE_BYTES))


def pdf_output_limit():
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))


def pdf_text(data):
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            ['pdftotext', '-layout', '-enc', 'UTF-8', '-', '-'],
            input=data,
            stdout=output,
            stderr=subprocess.PIPE,
            timeout=15,
            preexec_fn=pdf_output_limit,
            check=False,
        )
        if result.returncode:
            raise ValueError(
                'Could not read this PDF; it may be encrypted, damaged or too large.'
            )
        output.seek(0)
        return output.read(1024 * 1024).decode('utf-8')


def office_text(data, suffix):
    part = 'word/document.xml' if suffix == '.docx' else 'content.xml'
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.getinfo(part).file_size > 1024 * 1024:
            raise ValueError('This document is too large for the drawer.')
        xml = archive.read(part)
    if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:
        raise ValueError('Unsupported document XML.')
    document = ET.fromstring(xml)
    if suffix == '.docx':
        return '\n'.join(
            ''.join(node.itertext())
            for node in document.iter()
            if node.tag.endswith('}p')
        )
    return '\n'.join(
        ''.join(node.itertext())
        for node in document.iter()
        if node.tag.rsplit('}', 1)[-1] in ('p', 'h')
    )


def snapshot(name, data):
    name = (
        ''.join(character for character in name if character.isprintable())[:255]
        or 'Attachment'
    )
    suffix = Path(name).suffix.lower()
    if suffix == '.pdf' or data.startswith(b'%PDF-'):
        text = pdf_text(data)
        result = dict(kind='text', text=text)
    elif suffix in ('.docx', '.odt'):
        result = dict(kind='text', text=office_text(data, suffix))
    else:
        result = image_snapshot(name, data)
        if result is None:
            try:
                text = data.decode(
                    'utf-16'
                    if data.startswith((b'\xff\xfe', b'\xfe\xff'))
                    else 'utf-8-sig'
                )
            except UnicodeError as exc:
                raise ValueError(
                    'Use an image, text/code file, PDF, DOCX or ODT document.'
                ) from exc
            if '\0' in text or any(
                ord(char) < 9 or 13 < ord(char) < 32 for char in text
            ):
                raise ValueError('Binary files cannot be attached as text.')
            result = dict(kind='text', text=text)
    if result['kind'] == 'text':
        text = result['text']
        if not text.strip():
            raise ValueError(
                'No readable text was found. For scanned documents, attach page images to a vision model.'
            )
        if len(text) > MAX_TEXT:
            raise ValueError(
                'Document text exceeds 64,000 characters. Attach a smaller document or excerpt.'
            )
        result.update(text=text, size=len(text.encode()))
    result.update(
        id=hashlib.sha256(name.encode() + b'\0' + data).hexdigest(), name=name
    )
    return result


def prepare(urls):
    if not isinstance(urls, list) or len(urls) > MAX_FILES:
        raise ValueError('Attach up to six files at a time.')
    items, errors = [], []
    for url in urls:
        try:
            path = local_path(url)
            items.append(snapshot(path.name, read_file(path)))
        except (
            OSError,
            ValueError,
            KeyError,
            zipfile.BadZipFile,
            ET.ParseError,
            RuntimeError,
            subprocess.SubprocessError,
        ) as exc:
            errors.append(f'{str(url).rsplit("/", 1)[-1]}: {exc}')
    return dict(items=items, error='\n'.join(errors))


def clipboard():
    types = subprocess.run(
        ['wl-paste', '--list-types'],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    offered = types.stdout.splitlines()
    chosen = next(
        (
            kind
            for kind in [
                'text/uri-list',
                'image/png',
                'image/jpeg',
                'image/webp',
                'text/plain;charset=utf-8',
                'text/plain',
                'UTF8_STRING',
            ]
            if kind in offered
        ),
        None,
    )
    if not chosen:
        raise ValueError('The clipboard contains no supported text, files or image.')
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            ['wl-paste', '--no-newline', '--type', chosen],
            stdout=output,
            stderr=subprocess.PIPE,
            timeout=5,
            preexec_fn=output_limit,
            check=False,
        )
        if result.returncode:
            raise ValueError(
                'Could not read the clipboard. Copy the item again or attach a file.'
            )
        output.seek(0)
        data = output.read(MAX_FILE_BYTES + 1)
    if chosen == 'text/uri-list':
        return prepare(
            [
                line
                for line in data.decode().splitlines()
                if line and not line.startswith('#')
            ]
        )
    if chosen.startswith('image/'):
        return dict(items=[snapshot('Clipboard image', data)], error='')
    return dict(items=[], text=data.decode('utf-8'), error='')


def message_content(message, vision):
    text, files = message.get('content', ''), message.get('attachments', [])
    if (
        not isinstance(text, str)
        or not isinstance(files, list)
        or len(files) > MAX_FILES
    ):
        raise ValueError('Invalid chat attachments.')
    if not files:
        return text
    parts = [dict(type='text', text=text)] if text else []
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            raise ValueError('Invalid chat attachment.')
        if item.get('kind') == 'text':
            body = item.get('text')
            if not isinstance(body, str) or len(body) > MAX_TEXT:
                raise ValueError('Invalid document attachment.')
            parts.append(
                dict(type='text', text=f'Attached file: {item["name"]}\n\n{body}')
            )
        elif item.get('kind') == 'image':
            if not vision:
                raise ValueError(
                    'This conversation contains images. Choose a vision model or start a new chat.'
                )
            data = item.get('data', '')
            if not isinstance(data, str) or not data.startswith(
                ('data:image/png;base64,', 'data:image/jpeg;base64,')
            ):
                raise ValueError('Invalid image attachment.')
            try:
                decoded = base64.b64decode(data.split(',', 1)[1], validate=True)
            except ValueError as exc:
                raise ValueError('Invalid image attachment.') from exc
            if len(decoded) > MAX_IMAGE_BYTES:
                raise ValueError('Image attachment is too large.')
            parts.append(dict(type='image_url', image_url=dict(url=data)))
        else:
            raise ValueError('Unsupported chat attachment.')
    return parts
