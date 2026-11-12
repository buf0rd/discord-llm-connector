# by:buf0rd | Back it up. Install it. Put it back if the install fails.
import grp
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time

INSTALL_ROOT = Path('/opt/discord-llm')
CONFIG_PATH = Path('/etc/discord-llm/config.json')
UNIT_PATH = Path('/etc/systemd/system/discord-llm.service')
BACKUP_ROOT = Path('/var/backups/discord-llm')
STAGE_ROOT = Path(__file__).resolve().parent
SOURCE_FILES = ('bot.py', 'backend.py', 'settings.py', 'configure.py', 'websearch.py', 'README.md')

ROLLBACK_CODE = '''# by:buf0rd | Restore the files this installer changed.
import json, os, shutil, subprocess
from pathlib import Path
backup_dir = Path(__file__).resolve().parent
snapshot = json.loads((backup_dir / 'manifest.json').read_text())
subprocess.run(['systemctl', 'stop', 'discord-llm'], check=False)
subprocess.run(['systemctl', 'disable', 'discord-llm'], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for item in snapshot['files']:
    destination = Path(item['path'])
    if item['exists']:
        shutil.copyfile(backup_dir / item['backup'], destination)
        os.chown(destination, item['uid'], item['gid'])
        os.chmod(destination, item['mode'])
    else:
        destination.unlink(missing_ok=True)
subprocess.run(['systemctl', 'daemon-reload'], check=True)
if snapshot['enabled']:
    subprocess.run(['systemctl', 'enable', 'discord-llm'], check=True)
if snapshot['active']:
    subprocess.run(['systemctl', 'start', 'discord-llm'], check=True)
print('Previous files and service state restored. Runtime packages and conversation history were not rolled back.')
'''


def service_state(operation):
    return subprocess.run(['systemctl', operation, '--quiet', 'discord-llm'],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def replace_file(path, content, gid=0, mode=0o644):
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
            os.fchown(output.fileno(), 0, gid)
            os.fchmod(output.fileno(), mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup_dir = Path(tempfile.mkdtemp(prefix=time.strftime('%Y%m%d-%H%M%S-'), dir=BACKUP_ROOT))
    targets = [INSTALL_ROOT / name for name in SOURCE_FILES] + [CONFIG_PATH, UNIT_PATH]
    # The shell may have stopped the service to repair missing Python dependencies.
    active_before = os.environ.get('CONNECTOR_WAS_ACTIVE') == '1'
    snapshot = {'active': active_before, 'enabled': service_state('is-enabled'), 'files': []}
    for index, target in enumerate(targets):
        if target.is_symlink():
            raise SystemExit(f'Refusing to replace a symlink: {target}. No application files changed.')
        item = {'path': str(target), 'exists': target.exists(), 'backup': str(index)}
        if target.exists():
            metadata = target.stat()
            item.update(uid=metadata.st_uid, gid=metadata.st_gid, mode=stat.S_IMODE(metadata.st_mode))
            shutil.copy2(target, backup_dir / str(index))
        snapshot['files'].append(item)
    (backup_dir / 'manifest.json').write_text(json.dumps(snapshot))
    (backup_dir / 'rollback.py').write_text(ROLLBACK_CODE)
    try:
        subprocess.run(['systemctl', 'stop', 'discord-llm'], check=False)
        for name in SOURCE_FILES:
            replace_file(INSTALL_ROOT / name, (STAGE_ROOT / name).read_bytes())
        replace_file(CONFIG_PATH, (STAGE_ROOT / 'ready-config.json').read_bytes(),
                     gid=grp.getgrnam('discord-llm').gr_gid, mode=0o640)
        replace_file(UNIT_PATH, (STAGE_ROOT / 'discord-llm.service').read_bytes())
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'reset-failed', 'discord-llm'], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['systemctl', 'start', 'discord-llm'], check=True)
        time.sleep(3)
        if not service_state('is-active'):
            raise RuntimeError('The service did not stay running. Check journalctl -u discord-llm.')
        subprocess.run(['systemctl', 'enable', 'discord-llm'], check=True)
    except BaseException:
        print('Install failed. Restoring the previous files.', file=sys.stderr)
        subprocess.run([sys.executable, str(backup_dir / 'rollback.py')], check=True)
        raise
    print('\nInstalled // by:buf0rd')
    print('In Discord: !help, then !status. Wait five seconds between commands.')
    print('Try a model response: !ask Hello')
    print('Logs: sudo journalctl -u discord-llm -n 60 --no-pager')
    print('Guide: /opt/discord-llm/README.md')
    print(f'Rollback: sudo {INSTALL_ROOT}/venv/bin/python {backup_dir}/rollback.py')
    print('Service activity is checked. Discord login, backend access, and optional search still need a live test.')


if __name__ == '__main__':
    os.umask(0o077)
    main()

