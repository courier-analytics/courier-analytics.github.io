"""Push only validated public aggregates; never overwrite unrelated site files."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess

from enrich_slots import atomic_json
from refresh_dashboard import merge_feed

REPOSITORY = 'git@github.com:courier-analytics/courier-analytics.github.io.git'


def publish(feed, checkout, repository=REPOSITORY, environment=None):
    payload = json.loads(Path(feed).read_text())
    if payload.get('schema_version') != 1 or not payload.get('records'):
        raise ValueError('Invalid public feed')
    if any(row.get('source') != 'slots_export' for row in payload['records']):
        raise ValueError('Unknown public data source')
    public = merge_feed(None, payload)  # Validate counts; discard nonpublic fields.
    checkout = Path(checkout)
    def git(*args, cwd=checkout):
        return subprocess.run(['git', *args], cwd=cwd, env=environment,
                              capture_output=True, text=True, check=True)
    if not checkout.exists():
        checkout.parent.mkdir(parents=True, exist_ok=True)
        git('clone', '--single-branch', '--branch', 'main', repository, str(checkout), cwd=checkout.parent)
        (checkout/'.git/courier-publisher-owned').write_text(repository)
    marker = checkout/'.git/courier-publisher-owned'
    if not marker.is_file() or marker.read_text() != repository:
        raise ValueError('Publisher directory is not owned by this tool')
    if git('remote', 'get-url', 'origin').stdout.strip() != repository:
        raise ValueError('Unexpected publisher remote')
    if git('status', '--porcelain').stdout.strip():
        raise ValueError('Publisher checkout has local changes; preserved')
    git('fetch', 'origin', 'main')
    git('checkout', '--detach', 'FETCH_HEAD')
    destination = checkout/'data/dashboard.json'
    # Preserve history that another refresh may have published since our last run.
    if destination.exists():
        public = merge_feed(json.loads(destination.read_text()), public)
    atomic_json(destination, public)
    destination.chmod(0o644)
    git('add', '--', 'data/dashboard.json')
    staged = git('diff', '--cached', '--name-only').stdout.splitlines()
    if not staged:
        return 'Public aggregates already up to date'
    if staged != ['data/dashboard.json']:
        raise ValueError('Unexpected staged files; publication stopped')
    git('-c', 'user.name=Courier data updater', '-c', 'user.email=courier-data@users.noreply.github.com',
        'commit', '-m', 'Update courier slot aggregates')
    # A concurrent update rejects this push. No force push or branch reset.
    git('push', 'origin', 'HEAD:refs/heads/main')
    return 'Public aggregates pushed to main'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed', type=Path, required=True)
    parser.add_argument('--checkout', type=Path, default=Path('/opt/courier-analytics/publisher'))
    args = parser.parse_args()
    key = Path('/root/.ssh/courier-publisher')
    hosts = Path('/root/.ssh/courier-github-known-hosts')
    if not key.is_file() or not hosts.is_file():
        raise SystemExit('Publisher key or trusted GitHub host keys missing. Run setup_publisher.sh.')
    environment = os.environ.copy()
    environment['GIT_TERMINAL_PROMPT'] = '0'
    environment['GIT_SSH_COMMAND'] = ('ssh -i ' + shlex.quote(str(key)) +
        ' -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes'
        ' -o UserKnownHostsFile=' + shlex.quote(str(hosts)))
    try:
        print(publish(args.feed, args.checkout, environment=environment))
    except subprocess.CalledProcessError as error:
        raise SystemExit(f'Git publication failed (exit {error.returncode}); local feed retained. Check deploy key write access, branch protection and connectivity.')
    except (ValueError, KeyError, OSError):
        raise SystemExit('Publisher validation failed; publication stopped.')
