"""Keep package signatures required while allowing unsigned repository databases.

Archinstall's native signature enums cannot express DatabaseOptional separately.
Repository locations and package policy still come from native mirror_config.
"""

from types import SimpleNamespace


def configure_signature_policy(mirrors, extra):
    names = extra.get('repositories', {}).get('database_optional', [])
    for repository in mirrors.custom_repositories:
        if (
            repository.name in names
            and 'DatabaseOptional' not in repository.sign_option.value
        ):
            repository.sign_option = SimpleNamespace(
                value=repository.sign_option.value + ' DatabaseOptional'
            )
    return mirrors
