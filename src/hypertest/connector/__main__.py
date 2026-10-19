"""python -m hypertest.connector --config ~/.config/hypertest/connector.json"""
import argparse
import asyncio
import json
import os
import signal
from pathlib import Path

from hypertest.connector.daemon import ConnectorDaemon, private_key
from hypertest.harness_bridge.provider import PersistentCodex
from hypertest.harness_bridge.server import BridgeServer


def build_daemon(config: dict) -> ConnectorDaemon:
    state=Path(config['state_dir']).expanduser().absolute()
    state.mkdir(parents=True,mode=0o700,exist_ok=True)
    if state.resolve()!=state or state.is_symlink():
        raise ValueError('Connector state directory must be canonical')
    os.chmod(state,0o700)
    token_path=Path(config['device_token_file']).expanduser()
    if token_path.is_symlink() or token_path.stat().st_mode & 0o077:
        raise ValueError('Device token file must have private permissions')
    source=None
    if config.get('source',{}).get('allowed_origins'):
        from hypertest.connector.source import LocalSourceAdapter
        source=LocalSourceAdapter(state,allowed_origins=config['source']['allowed_origins'],
            allow_local_origin=config['source'].get('allow_local_origin',False))
    issue=None
    if config.get('issues'):
        from hypertest.connector.issues import LocalGitLabProject, LocalIssueAdapter
        issue=LocalIssueAdapter(state / "issues.sqlite3",
            {key:LocalGitLabProject.model_validate(value) for key,value in config["issues"]["integrations"].items()},node_id=config["node_id"])
    server=BridgeServer(socket_path=state/'control.sock',tool_socket_path=state/'relay.sock',
        state_dir=state/'bridge',workspace_root=state/'.hypertest-agent-sessions',host_id=config['node_key'],
        execution_key=private_key(state/'execution.key'),management_key=private_key(state/'management.key'),
        provider=PersistentCodex(config.get('codex_binary','codex')),max_concurrent=config.get('max_concurrent',2))
    return ConnectorDaemon(api_url=config['api_url'],node_id=config['node_id'],device_token=token_path.read_text().strip(),
        server=server,ca_file=config.get('ca_file'),allow_insecure_loopback=config.get('allow_insecure_loopback',False),
        source_adapter=source,issue_adapter=issue)


async def main():
    parser=argparse.ArgumentParser(description='Outbound local HyperTest Harness Connector')
    parser.add_argument('--config',type=Path,required=True)
    args=parser.parse_args()
    daemon=build_daemon(json.loads(args.config.read_text()))
    stopping=asyncio.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig,stopping.set)
    await daemon.run(stopping)


if __name__=='__main__':
    asyncio.run(main())
