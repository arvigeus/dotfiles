"""Frozen, bounded attachments without reading the host clipboard or making requests."""

import base64
import io
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib

import support

files = support.load(
    'assistant_attachments', support.DESKTOP / 'drawers/assistant/attachments.py'
)


def png(width=2, height=2):
    def chunk(kind, data):
        body = kind + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body))

    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress((b'\0' + b'\x40\x60\x80' * width) * height))
        + chunk(b'IEND', b'')
    )


def office(part, content):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr(part, content)
    return output.getvalue()


def pdf():
    content = b'BT /F1 12 Tf 20 80 Td (Hello document) Tj ET'
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length '
        + str(len(content)).encode()
        + b' >>\nstream\n'
        + content
        + b'\nendstream',
    ]
    result = b'%PDF-1.4\n'
    positions = [0]
    for index, body in enumerate(objects, 1):
        positions.append(len(result))
        result += f'{index} 0 obj\n'.encode() + body + b'\nendobj\n'
    start = len(result)
    result += b'xref\n0 6\n0000000000 65535 f \n' + b''.join(
        f'{position:010d} 00000 n \n'.encode() for position in positions[1:]
    )
    return (
        result
        + f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()
    )


class AssistantAttachmentTests(unittest.TestCase):
    def test_text_is_frozen_and_names_are_not_shell_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '$(touch nope) notes.md'
            path.write_text('    Original text ✓\n')
            result = files.prepare([path.as_uri()])
            path.write_text('Changed after attachment')
            self.assertFalse(result['error'])
            item = result['items'][0]
            self.assertEqual(item['text'], '    Original text ✓\n')
            content = files.message_content(
                dict(content='Summarize', attachments=[item]), False
            )
            self.assertIn('Original text ✓', content[1]['text'])
            self.assertFalse((Path(directory) / 'nope').exists())

    def test_images_are_normalized_and_do_not_require_original_files(self):
        item = files.snapshot('image.png', png(3000, 2))
        self.assertEqual(item['kind'], 'image')
        self.assertEqual(item['width'], 2048)
        content = files.message_content(
            dict(content='Read it', attachments=[item]), True
        )
        self.assertTrue(
            content[1]['image_url']['url'].startswith('data:image/png;base64,')
        )
        self.assertTrue(
            base64.b64decode(
                content[1]['image_url']['url'].split(',', 1)[1]
            ).startswith(b'\x89PNG')
        )
        with self.assertRaisesRegex(ValueError, 'vision'):
            files.message_content(dict(attachments=[item]), False)

    def test_remote_images_and_unsupported_binary_are_rejected(self):
        result = files.prepare(['https://example.org/private.png'])
        self.assertFalse(result['items'])
        self.assertIn('local file', result['error'])
        with self.assertRaisesRegex(ValueError, 'Invalid image'):
            files.message_content(
                dict(
                    attachments=[
                        dict(
                            name='remote',
                            kind='image',
                            data='https://example.org/image.png',
                        )
                    ]
                ),
                True,
            )
        with self.assertRaises(ValueError):
            files.snapshot('binary.dat', b'\0\xff\x01\x02')

    def test_word_and_open_document_text_are_extracted(self):
        docx = office(
            'word/document.xml',
            '<w:document xmlns:w="urn:word"><w:p><w:r><w:t>First</w:t></w:r></w:p><w:p><w:r><w:t>Second</w:t></w:r></w:p></w:document>',
        )
        odt = office(
            'content.xml',
            '<office xmlns:text="urn:text"><text:p>One</text:p><text:h>Two</text:h></office>',
        )
        self.assertEqual(files.snapshot('notes.docx', docx)['text'], 'First\nSecond')
        self.assertEqual(files.snapshot('notes.odt', odt)['text'], 'One\nTwo')

    @unittest.skipUnless(shutil.which('pdftotext'), 'Poppler is required')
    def test_pdf_text_is_extracted_locally(self):
        self.assertIn('Hello document', files.snapshot('document.pdf', pdf())['text'])

    def test_limits_and_special_files_fail_without_hanging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fifo = root / 'fifo'
            os.mkfifo(fifo)
            self.assertIn('regular files', files.prepare([str(fifo)])['error'])
            path = root / 'big.txt'
            path.write_text('a' * 10)
            with patch.object(files, 'MAX_FILE_BYTES', 4):
                self.assertIn('smaller', files.prepare([str(path)])['error'])
        with self.assertRaises(ValueError):
            files.prepare(['file:///a'] * 7)
        with self.assertRaisesRegex(ValueError, '64,000'):
            files.snapshot('large.txt', b'a' * 64001)

    def test_clipboard_prefers_images_and_never_pastes_text_instead(self):
        def fake(args, **kwargs):
            if '--list-types' in args:
                return subprocess.CompletedProcess(
                    args, 0, 'text/plain\nimage/png\n', ''
                )
            self.assertEqual(args[-1], 'image/png')
            kwargs['stdout'].write(png())
            return subprocess.CompletedProcess(args, 0, b'', b'')

        with patch.object(files.subprocess, 'run', side_effect=fake):
            value = files.clipboard()
        self.assertEqual(value['items'][0]['kind'], 'image')
        self.assertNotIn('text', value)
