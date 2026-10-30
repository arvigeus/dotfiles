"""Configure the Blender Lab MCP extension through Blender's Python API."""

from pathlib import Path

import bpy

REPOSITORY = 'lab_blender_org'
ADDON = f'bl_ext.{REPOSITORY}.mcp'


def require_finished(result, action):
    if result != {'FINISHED'}:
        raise RuntimeError(f'{action} failed: {result}')


def main():
    preferences = bpy.context.preferences
    # The bridge checks this permission even for its localhost socket.
    preferences.system.use_online_access = True

    repository = next(
        (repo for repo in preferences.extensions.repos if repo.module == REPOSITORY),
        None,
    )
    if repository is None:
        repository = preferences.extensions.repos.new(
            name='Blender Lab',
            module=REPOSITORY,
            remote_url='https://lab.blender.org/',
        )
    repository.enabled = True
    repository.use_remote_url = True
    repository.remote_url = 'https://lab.blender.org/'

    if not (Path(repository.directory) / 'mcp' / 'blender_manifest.toml').is_file():
        require_finished(
            bpy.ops.extensions.repo_sync(repo_directory=repository.directory),
            'Blender Lab repository sync',
        )
        require_finished(
            bpy.ops.extensions.package_install(
                repo_directory=repository.directory,
                pkg_id='mcp',
                enable_on_install=True,
            ),
            'MCP extension installation',
        )
    addon = preferences.addons.get(ADDON)
    if addon is None or addon.preferences is None:
        require_finished(bpy.ops.preferences.addon_enable(module=ADDON), 'MCP enable')

    mcp = preferences.addons[ADDON].preferences
    if mcp is None:
        raise RuntimeError('MCP add-on preferences are unavailable after enabling it')
    mcp.host = 'localhost'
    mcp.port = 9876
    mcp.use_autostart = True
    require_finished(bpy.ops.wm.save_userpref(), 'Saving Blender preferences')
    print('Blender MCP: online access and Auto Start enabled on localhost:9876')


if __name__ == '__main__':
    main()
