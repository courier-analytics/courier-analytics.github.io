"""Test private subscription nodes in an isolated loopback Xray process."""
import argparse
import getpass
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

from enrich_slots import atomic_json
from prepare_proxy_config import canonical_config
from private_proxy_input import read_nodes, ImportProblem
from verify_server_proxy import network_probe

TEST_PORT = 18082


def acceptable(result):
    return result['curl_exit'] == 0 and result['anonymous_http_status'] in ('200', '401')


def probe_node(node, binary, folder):
    # Never reuse a port belonging to another process and mistake it for success.
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', TEST_PORT))
    config = canonical_config(node)
    config['inbounds'][0]['port'] = TEST_PORT
    path = folder/'candidate.json'
    atomic_json(path, config)
    with (folder/'candidate-private.log').open('wb') as log:
        worker = subprocess.Popen([str(binary), 'run', '-config', str(path)],
                                  stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+3
            while time.monotonic() < deadline:
                if worker.poll() is not None:
                    return {'curl_exit': -1, 'anonymous_http_status': None}
                try:
                    with socket.create_connection(('127.0.0.1', TEST_PORT), timeout=.2):
                        return network_probe(f'socks5h://127.0.0.1:{TEST_PORT}')
                except OSError:
                    time.sleep(.1)
            return {'curl_exit': 7, 'anonymous_http_status': None}
        finally:
            if worker.poll() is None:
                worker.terminate()
                try:
                    worker.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=3)


def choose(nodes, binary, folder):
    for index, node in enumerate(nodes, 1):
        print(f'Testing node {index}/{len(nodes)} through isolated port {TEST_PORT}...', flush=True)
        result = probe_node(node, binary, folder)
        print(f"Node {index}: curl={result['curl_exit']}, HTTP={result['anonymous_http_status']}", flush=True)
        if acceptable(result):
            return node
    raise ImportProblem('no_subscription_node_reached_courier_api')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/root/courier-private-node.json'))
    args = parser.parse_args()
    binary = Path('/usr/local/lib/courier-proxy/xray')
    try:
        if not sys.stdin.isatty() or not os.access(binary, os.X_OK):
            raise ImportProblem('interactive_tty_and_installed_xray_required')
        value = getpass.getpass('Private HTTPS subscription or VLESS link (hidden): ').strip()
        nodes = read_nodes(value)
        with tempfile.TemporaryDirectory(prefix='courier-node-test-') as directory:
            node = choose(nodes, binary, Path(directory))
        atomic_json(args.output, node)
        print('Working node saved privately. Existing proxy and route have not been changed.', flush=True)
    except ImportProblem as error:
        raise SystemExit('Node selection failed: '+str(error)+'. No active route changed.')
    except (OSError, ValueError, TypeError, KeyError, EOFError, subprocess.SubprocessError):
        raise SystemExit('Node test failed; no active route changed. Subscription secrets hidden.')
