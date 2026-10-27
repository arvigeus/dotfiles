"""Native GnuPG operations use the user's agent/pinentry and preserve owner trust."""

from pathlib import Path
import re
import tarfile

from tool_jobs import Output, batch, command, emit, row
from tool_specs import action, option

ARMOR = option('armor', 'ASCII armor', 'boolean', False)
RECIPIENTS = option('recipients', 'Recipients', 'public-keys')
SIGNER = option('signer', 'Signing identity', 'secret-key')
ACTIONS = [
    action('encrypt', 'Encrypt with keys', 'Encrypt', [RECIPIENTS, ARMOR]),
    action(
        'symmetric',
        'Encrypt with a password',
        'Encrypt',
        [ARMOR],
        description='GnuPG asks for the password in its secure prompt.',
    ),
    action('sign-encrypt', 'Sign and encrypt', 'Encrypt', [RECIPIENTS, SIGNER, ARMOR]),
    action(
        'sign',
        'Sign',
        'Sign',
        [
            SIGNER,
            option(
                'signature',
                'Signature format',
                'choice',
                'binary',
                [
                    ('Signed file', 'binary'),
                    ('ASCII signed file', 'armor'),
                    ('Detached signature', 'detached'),
                ],
            ),
        ],
    ),
    action(
        'decrypt',
        'Decrypt',
        'Decrypt',
        description='Encrypted folders are restored as tar archives; extract them with Ark.',
    ),
    action(
        'verify',
        'Verify signatures',
        'Verify',
        [option('original', 'Original file (detached signatures)', 'file')],
        output=False,
    ),
    action('key-info', 'Inspect key files', 'Keys', output=False),
    action(
        'import',
        'Import keys',
        'Keys',
        output=False,
        description='Imports selected keys without changing their owner trust.',
    ),
]


def key_records(secret=False):
    raw = command(
        [
            'gpg',
            '--batch',
            '--with-colons',
            '--fingerprint',
            '--list-secret-keys' if secret else '--list-keys',
        ]
    )
    records = []
    current = None
    for line in raw.decode(errors='replace').splitlines():
        parts = line.split(':')
        if parts[0] in ('pub', 'sec'):
            current = dict(
                fingerprint='',
                name='',
                validity=parts[1],
                capabilities=parts[11],
                secret=secret,
            )
            records.append(current)
        elif parts[0] == 'fpr' and current is not None and not current['fingerprint']:
            current['fingerprint'] = parts[9]
        elif parts[0] == 'uid' and current is not None and not current['name']:
            text = parts[9].encode()
            current['name'] = re.sub(
                rb'\\x([0-9a-fA-F]{2})', lambda m: bytes([int(m[1], 16)]), text
            ).decode(errors='replace')
    return [
        record
        for record in records
        if record['fingerprint']
        and record['validity'] not in ('r', 'e', 'd', 'i')
        and 'D' not in record['capabilities']
    ]


def send_keys():
    public = key_records()
    secret = {key['fingerprint'] for key in key_records(True)}
    for key in public:
        key['secret'] = key['fingerprint'] in secret
    emit('keys', keys=public)


def run(action_id, paths, options, _plan=None):
    if action_id == 'keys':
        send_keys()
        return
    if not paths:
        raise ValueError('Select files or folders first.')
    if action_id == 'import':

        def import_file(path):
            if not path.is_file():
                raise ValueError('Select key files.')
            text = command(['gpg', '--batch', '--import', '--', path])
            row(path, 'Imported', text.decode(errors='replace').strip())

        failures = batch(paths, import_file)
        send_keys()
        return failures
    if action_id == 'key-info':

        def inspect(path):
            text = command(
                ['gpg', '--batch', '--show-keys', '--fingerprint', '--', path]
            )
            row(path, 'Key information', text.decode(errors='replace').strip())

        return batch(paths, inspect)
    recipients = options.get('recipients', [])
    signer = options.get('signer', '')
    if action_id in ('encrypt', 'sign-encrypt'):
        if (
            not isinstance(recipients, list)
            or not recipients
            or any(
                not re.fullmatch(r'[0-9A-Fa-f]{40,64}', value) for value in recipients
            )
        ):
            raise ValueError('Select one or more recipient keys.')
    if action_id in ('sign', 'sign-encrypt') and not re.fullmatch(
        r'[0-9A-Fa-f]{40,64}', signer
    ):
        raise ValueError('Select a signing identity.')

    def process(path):
        if action_id == 'verify':
            argv = ['gpg', '--batch', '--status-fd', '1', '--verify', '--', path]
            if options.get('original'):
                argv.append(Path(options['original']).absolute())
            text = command(argv).decode(errors='replace')
            row(path, 'Signature verified', text.strip())
            return
        if not path.exists() or path.is_symlink():
            raise ValueError('Select existing regular files or folders.')
        folder = Path(options['output']) if options.get('output') else path.parent
        if path.is_dir() and folder.resolve().is_relative_to(path.resolve()):
            raise ValueError(
                'Choose an output folder outside the folder being encrypted.'
            )
        if action_id == 'decrypt':
            name = (
                path.name.rsplit('.', 1)[0]
                if path.suffix.lower() in ('.gpg', '.pgp', '.asc')
                else path.name + ' [decrypted]'
            )
        elif action_id == 'sign' and options.get('signature') == 'detached':
            name = path.name + '.sig'
        else:
            armor = options.get('armor', False) or (
                action_id == 'sign' and options.get('signature') == 'armor'
            )
            name = (
                path.name
                + ('.tar' if path.is_dir() else '')
                + ('.asc' if armor else '.gpg')
            )
        with Output(folder / name) as output:
            source = path
            if path.is_dir():
                if action_id == 'decrypt':
                    raise ValueError('Select encrypted files.')
                if action_id == 'sign' and options.get('signature') == 'detached':
                    raise ValueError(
                        'Detached signatures require a regular file; sign the folder as a signed archive instead.'
                    )
                source = Path(output.temporary.name) / 'source.tar'
                with tarfile.open(source, 'w', dereference=False) as archive:
                    archive.add(path, arcname=path.name)
            argv = ['gpg', '--yes', '--no-tty', '--output', output.path]
            if action_id in ('encrypt', 'sign-encrypt'):
                argv.append('--batch')
                for recipient in recipients:
                    argv.extend(['--recipient', recipient])
                if options.get('armor'):
                    argv.append('--armor')
                if action_id == 'sign-encrypt':
                    argv.extend(['--local-user', signer, '--sign'])
                argv.append('--encrypt')
            elif action_id == 'symmetric':
                if options.get('armor'):
                    argv.append('--armor')
                argv.append('--symmetric')
            elif action_id == 'sign':
                argv.extend(['--local-user', signer])
                if options.get('signature') == 'armor':
                    argv.append('--armor')
                argv.append(
                    '--detach-sign'
                    if options.get('signature') == 'detached'
                    else '--sign'
                )
            elif action_id == 'decrypt':
                argv.append('--decrypt')
            else:
                raise ValueError('Unknown encryption operation.')
            command([*argv, '--', source])
            output.publish()

    return batch(paths, process)
