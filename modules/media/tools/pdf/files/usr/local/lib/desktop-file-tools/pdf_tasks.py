"""PDF operations preserve originals and publish complete outputs without overwriting."""

from contextlib import ExitStack
from pathlib import Path
import re
import secrets

from tool_jobs import Output, batch, command, files, row, target_for
from tool_specs import action, option

PASSWORD = option('password', 'Current password', 'password')
ACTIONS = [
    action(
        'combine',
        'Combine PDFs',
        'Pages',
        [PASSWORD],
        minimum=2,
        description='Pages follow the order in the file list.',
    ),
    action(
        'split',
        'Extract / split pages',
        'Pages',
        [
            option('pages', 'Pages (blank for all)'),
            option(
                'split_mode',
                'Export as',
                'choice',
                'separate',
                [
                    ('Separate PDFs for each page', 'separate'),
                    ('One PDF with selected pages', 'selection'),
                ],
            ),
            PASSWORD,
        ],
    ),
    action(
        'rotate',
        'Rotate pages',
        'Pages',
        [
            option(
                'angle',
                'Rotation',
                'choice',
                '90',
                [('90° clockwise', '90'), ('180°', '180'), ('270° clockwise', '270')],
            ),
            PASSWORD,
        ],
    ),
    action('linearize', 'Optimize for web', 'Optimize', [PASSWORD]),
    action(
        'reduce',
        'Reduce file size',
        'Optimize',
        [
            option(
                'dpi',
                'Quality',
                'choice',
                '150',
                [('150 dpi · e-book', '150'), ('300 dpi · printer', '300')],
            )
        ],
    ),
    action('metadata', 'Remove metadata', 'Optimize', [PASSWORD]),
    action('pdfa', 'Convert to PDF/A-2b', 'Optimize'),
    action(
        'protect',
        'Set a password',
        'Security',
        [PASSWORD, option('new_password', 'New password', 'password')],
    ),
    action('unprotect', 'Remove password', 'Security', [PASSWORD]),
    action(
        'watermark',
        'Add a PDF watermark',
        'Watermark',
        [
            option('watermark', 'Watermark PDF', 'file'),
            option(
                'layer',
                'Position',
                'choice',
                'over',
                [('Over pages', 'over'), ('Under pages', 'under')],
            ),
            PASSWORD,
        ],
    ),
    action('images', 'Extract images', 'Extract'),
    action('inspect', 'File information', 'Information', [PASSWORD], output=False),
    action('signatures', 'Show signatures', 'Information', output=False),
]


def page_selection(text, count):
    """Validate one-based ranges, retaining written order and removing overlaps."""
    text = str(text).strip()
    if not text:
        return list(range(count))
    if len(text) > 4096:
        raise ValueError('The page selection is too long.')
    selected = []
    seen = set()
    for part in text.split(','):
        match = re.fullmatch(r'([0-9]+)(?:\s*-\s*([0-9]+))?', part.strip())
        if not match:
            raise ValueError('Use page numbers and ranges, for example 1-5,7.')
        first = int(match[1])
        last = int(match[2] or match[1])
        if first < 1 or last < first or last > count:
            raise ValueError(f'Choose ascending ranges between 1 and {count}.')
        for number in range(first - 1, last):
            if number not in seen:
                selected.append(number)
                seen.add(number)
    return selected


def run(action_id, paths, options, _plan=None):
    import pikepdf

    selected = files(paths, {'.pdf'})
    if not selected:
        raise ValueError('Select PDF files or a folder containing PDFs.')
    password = options.get('password', '')
    folder = options.get('output', '')

    def opened(path):
        return pikepdf.Pdf.open(path, password=password)

    if action_id == 'combine':
        # The picker/list order is deliberately retained, rather than sorting filenames.
        if len(selected) < 2:
            raise ValueError('Select at least two PDFs.')
        target = (
            Path(folder) if folder else selected[0].parent
        ) / 'Combined documents.pdf'
        with (
            Output(target) as output,
            pikepdf.Pdf.new() as merged,
            ExitStack() as sources,
        ):
            version = merged.pdf_version
            for path in selected:
                source = sources.enter_context(opened(path))
                merged.pages.extend(source.pages)
                version = max(version, source.pdf_version)
            merged.save(output.path, min_version=version)
            output.publish()
        return

    def process(path):
        if action_id == 'signatures':
            text = command(['pdfsig', path], accepted=(0, 1, 2)).decode(
                errors='replace'
            )
            row(path, 'Signatures', text.strip())
            return
        if action_id in ('pdfa', 'reduce', 'images'):
            extension = '.pdf'
            suffix = action_id
            if action_id == 'images':
                with Output(
                    target_for(path, 'images', '', folder).with_suffix(''),
                    directory=True,
                ) as output:
                    command(['pdfimages', '-all', path, output.path / 'image'])
                    output.publish()
                return
            with Output(target_for(path, suffix, extension, folder)) as output:
                if action_id == 'reduce':
                    dpi = options.get('dpi', '150')
                    if dpi not in ('150', '300'):
                        raise ValueError('Choose 150 or 300 dpi.')
                    command(
                        [
                            'gs',
                            '-q',
                            '-dSAFER',
                            '-dNOPAUSE',
                            '-dBATCH',
                            '-sDEVICE=pdfwrite',
                            '-dPDFSETTINGS='
                            + ('/ebook' if dpi == '150' else '/printer'),
                            '-sOutputFile=' + str(output.path),
                            '-f',
                            path,
                        ]
                    )
                else:
                    command(
                        [
                            'ocrmypdf',
                            '--ocr-engine',
                            'none',
                            '--skip-text',
                            '--output-type',
                            'pdfa-2',
                            '--',
                            path,
                            output.path,
                        ]
                    )
                output.publish()
            return
        with opened(path) as pdf:
            if action_id == 'inspect':
                for key, value in [
                    ('Pages', len(pdf.pages)),
                    ('PDF version', pdf.pdf_version),
                    ('Encrypted', pdf.is_encrypted),
                    ('Optimized for web', pdf.is_linearized),
                ]:
                    row(path, key, value)
                for key, value in pdf.docinfo.items():
                    row(path, str(key).lstrip('/'), str(value))
                return
            if action_id == 'split':
                indices = page_selection(options.get('pages', ''), len(pdf.pages))
                if not indices:
                    raise ValueError('This document has no pages to export.')
                mode = options.get('split_mode', 'separate')
                if mode not in ('separate', 'selection'):
                    raise ValueError('Choose a page export format.')
                if mode == 'selection':
                    with (
                        Output(target_for(path, 'selection', '.pdf', folder)) as output,
                        pikepdf.Pdf.new() as part,
                    ):
                        for index in indices:
                            part.pages.append(pdf.pages[index])
                        part.save(output.path, min_version=pdf.pdf_version)
                        output.publish()
                else:
                    target = (Path(folder) if folder else path.parent) / (
                        path.stem + ' [pages]'
                    )
                    with Output(target, directory=True) as output:
                        for index in indices:
                            with pikepdf.Pdf.new() as part:
                                part.pages.append(pdf.pages[index])
                                part.save(
                                    output.path / f'{index + 1:04}.pdf',
                                    min_version=pdf.pdf_version,
                                )
                        output.publish()
                return
            if action_id == 'rotate':
                angle = int(options.get('angle', '90'))
                if angle not in (90, 180, 270):
                    raise ValueError('Choose a quarter-turn rotation.')
                for index in page_selection(options.get('pages', ''), len(pdf.pages)):
                    pdf.pages[index].rotate(angle, relative=True)
            elif action_id == 'metadata':
                if '/Metadata' in pdf.Root:
                    del pdf.Root['/Metadata']
                for key in list(pdf.docinfo.keys()):
                    del pdf.docinfo[key]
            elif action_id == 'watermark':
                watermark = Path(options.get('watermark', '')).absolute()
                with pikepdf.Pdf.open(watermark) as mark:
                    if not mark.pages:
                        raise ValueError('The watermark PDF has no pages.')
                    for page in pdf.pages:
                        if options.get('layer', 'over') == 'under':
                            page.add_underlay(mark.pages[0])
                        else:
                            page.add_overlay(mark.pages[0])
            elif action_id not in ('linearize', 'protect', 'unprotect'):
                raise ValueError('Unknown PDF operation.')
            save_options = {}
            if action_id == 'linearize':
                save_options['linearize'] = True
            if action_id == 'protect':
                new_password = options.get('new_password', '')
                if not new_password:
                    raise ValueError('Enter a new password.')
                save_options['encryption'] = pikepdf.Encryption(
                    user=new_password, owner=secrets.token_urlsafe(32), R=6
                )
            elif pdf.is_encrypted and action_id != 'unprotect':
                save_options['encryption'] = True
            with Output(target_for(path, action_id, '.pdf', folder)) as output:
                pdf.save(output.path, **save_options)
                output.publish()

    return batch(selected, process)
