"""Private draft operations and explicit, non-overwriting PDF exports."""

from contextlib import ExitStack
from pathlib import Path
import shutil

from tool_jobs import Output, emit, rename_noreplace

PDF_EDITS = {'combine', 'rotate', 'metadata', 'protect', 'unprotect', 'watermark'}


def stage(action, entries, options, directory):
    import importlib

    if action not in PDF_EDITS:
        raise ValueError('Unknown edit.')
    root = Path(directory)
    if not root.is_dir():
        raise ValueError('Draft folder is unavailable.')
    if action == 'combine':
        import pikepdf

        if len(entries) < 2:
            raise ValueError('Add at least two documents to combine.')
        with pikepdf.Pdf.new() as merged, ExitStack() as sources:
            version = merged.pdf_version
            for entry in entries:
                pdf = sources.enter_context(
                    pikepdf.Pdf.open(entry['path'], password=entry.get('password', ''))
                )
                merged.pages.extend(pdf.pages)
                version = max(version, pdf.pdf_version)
            with Output(root / 'Combined documents.pdf') as output:
                merged.save(output.path, min_version=version)
                output.publish()
        emit('draft', path=str(root / 'Combined documents.pdf'))
        return 0
    module = importlib.import_module('pdf_tasks')
    failures = 0
    for index, entry in enumerate(entries):
        destination = root / str(index)
        destination.mkdir(mode=0o700)
        settings = dict(
            options, output=str(destination), password=entry.get('password', '')
        )
        failed = module.run(action, [entry['path']], settings) or 0
        failures += failed
        if not failed:
            outputs = list(destination.iterdir())
            if len(outputs) != 1 or not outputs[0].is_file():
                raise ValueError('The edit did not produce a draft.')
            name = Path(entry.get('name', entry['path'])).stem + '.pdf'
            normalized = destination / name
            if outputs[0] != normalized:
                rename_noreplace(outputs[0], normalized)
            emit('draft', path=str(normalized))
    return failures


def save(entries):
    def write(entry):
        path = Path(entry['path'])
        target = Path(entry['target'])
        with Output(target) as output:
            shutil.copyfile(path, output.path)
            output.publish()

    # Preflight all names before publishing any file in a batch.
    targets = [str(Path(entry['target']).absolute()) for entry in entries]
    if len(set(targets)) != len(targets):
        raise ValueError('Some output names are the same. Save those files separately.')
    for entry in entries:
        target = Path(entry['target'])
        if target.exists() or target.is_symlink():
            raise ValueError('Output already exists: ' + str(target))
        if not target.parent.is_dir():
            raise ValueError('Choose an existing output folder.')
    # Keep the entry metadata intact while sharing per-file failure reporting.
    failures = 0
    for index, entry in enumerate(entries):
        emit(
            'progress',
            current=index,
            total=len(entries),
            name=Path(entry['target']).name,
        )
        try:
            write(entry)
        except (OSError, ValueError, RuntimeError) as error:
            from tool_jobs import row

            failures += 1
            row(entry['target'], 'Failed', str(error), error=True)
    return failures


def export_pdf(entry, variant, options, directory):
    """Export a variant of the current draft without adopting it as an edit."""
    import tempfile
    import pdf_tasks

    if variant not in ('linearize', 'reduce', 'pdfa', 'split', 'images'):
        raise ValueError('Unknown PDF export format.')
    path = Path(entry['path'])
    target = Path(entry['target'])
    settings = dict(options, password=entry.get('password', ''))
    if variant == 'images' or (
        variant == 'split' and settings.get('split_mode', 'separate') == 'separate'
    ):
        return pdf_tasks.run(variant, [path], dict(settings, output=str(target))) or 0
    with (
        Output(target) as output,
        tempfile.TemporaryDirectory(prefix='export-', dir=directory) as temporary,
    ):
        failures = pdf_tasks.run(variant, [path], dict(settings, output=temporary)) or 0
        if failures:
            return failures
        files = list(Path(temporary).glob('*.pdf'))
        if len(files) != 1:
            raise ValueError('The export did not produce a PDF.')
        shutil.copyfile(files[0], output.path)
        output.publish()
    return 0
