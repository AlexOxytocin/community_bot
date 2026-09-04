"""Activate Telegram on an unchanged measured runtime, with env/menu rollback.

Prepare records private state only. Apply never changes images, schema, registration
mode or user subscriptions. A foreign webhook is a hard stop, not a takeover.
"""

from __future__ import annotations

# ruff: noqa: E501 - embedded runtime program is passed as one fixed argv value.
import argparse
import importlib
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from ops._runtime import read_dotenv, validate_environment_file
from ops.wallet_cutover import ROOT, SERVICES, CutoverError, digest, inspect, run, save

WEB = "community-mini-app-core-web-1"
WORKER = "community-mini-app-core-worker-1"
ENV_FILE = ROOT / "shared" / ".env"
CHAT, TOPIC = -1002237685639, 24962
NGINX_FILE = Path("/opt/app/nginx/conf.d/default.conf")
WEBHOOK_LOCATION = """    location = /api/telegram/webhook {
        proxy_pass http://community-mini-app-core-web-1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 256k;
    }

"""

# Executed as a fixed argv program inside the existing image. Only rollback data
# (not executable source) uses stdin. Bot tokens never leave the runtime.
RUNTIME = r"""
import asyncio, json, sys, urllib.request, urllib.error
from aiogram import Bot
from aiogram.types import BotCommand
from community_bot.bootstrap.settings import get_settings
diagnostic = {'step':'settings'}
async def main():
    s = get_settings()
    async with Bot(token=s.bot_token.get_secret_value()) as bot:
        action = sys.argv[1]
        if action == "inspect":
            me = await bot.get_me()
            if me.username != "humanquest_bot" or s.telegram_bot_username != me.username:
                raise ValueError("Bot identity mismatch")
            if s.community_telegram_chat_id != -1002237685639:
                raise ValueError("Community chat mismatch")
            member = await bot.get_chat_member(-1002237685639, me.id)
            if member.status not in {"administrator", "creator"}:
                raise ValueError("Bot must be a chat administrator")
            w = await bot.get_webhook_info()
            url = s.mini_app_origin.rstrip('/') + '/api/telegram/webhook'
            if not url.startswith('https://') or (w.url and w.url != url):
                raise ValueError("Foreign webhook; coordinated takeover required")
            if w.url and (not s.telegram_webhook_secret or w.has_custom_certificate):
                raise ValueError("Existing webhook cannot be safely restored")
            commands = [x.model_dump() for x in await bot.get_my_commands()]
            if len({x['command'] for x in commands} | {'start','notifications'}) > 100:
                raise ValueError("Command list full")
            print(json.dumps({'webhook':w.model_dump(mode='json'), 'commands':commands,
                'url':url, 'menu':(await bot.get_chat_menu_button()).model_dump(mode='json')}))
        elif action == "probe":
            results = {}
            for name, base in [('public',s.mini_app_origin),('internal','http://127.0.0.1:8000')]:
                req = urllib.request.Request(base.rstrip('/')+'/api/telegram/webhook', data=b'{"update_id":0}',
                    headers={'Content-Type':'application/json','X-Telegram-Bot-Api-Secret-Token':'invalid-secret'})
                try:
                    r = urllib.request.urlopen(req,timeout=10)
                except urllib.error.HTTPError as e: r = e
                with r:
                    results[name] = {'status':r.status,'type':r.headers.get('Content-Type'),
                        'server':r.headers.get('Server'),'mitigated':r.headers.get('cf-mitigated')}
            print(json.dumps(results))
        elif action == "apply":
            from community_bot.bootstrap.telegram_features import configure
            diagnostic['step'] = 'configure_bot'
            await configure(apply=True)
            # Verify the actual public ingress without inventing a user message.
            url = s.mini_app_origin.rstrip('/') + '/api/telegram/webhook'
            def request(secret):
                req = urllib.request.Request(url, data=b'{"update_id":0}', headers={
                    'Content-Type':'application/json', 'X-Telegram-Bot-Api-Secret-Token':secret})
                try:
                    with urllib.request.urlopen(req, timeout=10) as r: return r.status
                except urllib.error.HTTPError as e: return e.code
            diagnostic['step'] = 'public_ingress'
            diagnostic['invalid_status'] = request('invalid-secret')
            diagnostic['valid_status'] = request(s.telegram_webhook_secret.get_secret_value())
            if diagnostic['invalid_status'] != 403 or diagnostic['valid_status'] != 200:
                raise ValueError('Public ingress verification failed')
            commands = {x.command for x in await bot.get_my_commands()}
            if not {'start','notifications'} <= commands:
                raise ValueError('Commands verification failed')
            print(json.dumps({'ingress':True,'commands':True}))
        elif action == "restore":
            old = json.load(sys.stdin)
            w = old['webhook']
            if w['url']:
                await bot.set_webhook(url=w['url'], secret_token=s.telegram_webhook_secret.get_secret_value(),
                    allowed_updates=w.get('allowed_updates'), max_connections=w.get('max_connections'),
                    drop_pending_updates=False)
            else:
                await bot.delete_webhook(drop_pending_updates=False)
            await bot.set_my_commands([BotCommand(**x) for x in old['commands']])
            if (await bot.get_webhook_info()).url != w['url']:
                raise ValueError('Webhook rollback verification failed')
            print(json.dumps({'restored':True}))
        else: raise ValueError('Unknown runtime action')
try:
    asyncio.run(main())
except Exception as error:
    print(json.dumps({'diagnostic':diagnostic,'error_type':type(error).__name__}))
    sys.exit(1)
"""


def runtime(action: str, data: dict | None = None) -> dict:
    """Capture transport diagnostics privately; never print tokens or webhook URLs."""
    result = subprocess.run(
        ["docker", "exec", "-i", WEB, "python", "-c", RUNTIME, action],
        input=json.dumps(data).encode() if data is not None else b"",
        capture_output=True,
        check=False,
    )
    if result.returncode:
        # Only this program's allowlisted diagnostics may reach the operator.
        try:
            error = json.loads(result.stdout)
        except (ValueError, UnicodeDecodeError):
            error = {}
        diagnostic = error.get("diagnostic", {})
        safe = {
            key: diagnostic[key]
            for key in ("step", "invalid_status", "valid_status")
            if key in diagnostic
        }
        raise CutoverError(f"Runtime {action} failed: {json.dumps(safe)}")
    return json.loads(result.stdout)


def environment_content(original: str, secret: str) -> bytes:
    """Change only the three explicitly scoped settings; preserve other content."""
    changes = {
        "TELEGRAM_WEBHOOK_SECRET": secret,
        "NOMAD_TELEGRAM_CHAT_ID": str(CHAT),
        "NOMAD_TELEGRAM_TOPIC_ID": str(TOPIC),
    }
    lines = [
        line for line in original.splitlines() if line.partition("=")[0].strip() not in changes
    ]
    return (
        "\n".join(lines) + "\n" + "\n".join(f"{k}={v}" for k, v in changes.items()) + "\n"
    ).encode()


def nginx_content(original: str) -> bytes:
    """Insert one exact Telegram endpoint inside the measured host, never edit root routes."""
    host = "    server_name allo.godmodetools.com;"
    marker = "    location /api/v1/ {"
    if original.count(host) != 1:
        raise CutoverError("Ambiguous nginx host")
    start = original.index(host)
    end = original.find("\nserver {", start)
    end = len(original) if end < 0 else end
    section = original[start:end]
    if "/api/telegram/webhook" in section:
        if WEBHOOK_LOCATION not in section:
            raise CutoverError("Existing webhook proxy differs")
        return original.encode()
    if section.count(marker) != 1:
        raise CutoverError("Ambiguous API location")
    position = original.index(marker, start, end)
    return (original[:position] + WEBHOOK_LOCATION + original[position:]).encode()


def edge(state: dict, receipt: Path, *, old: bool = False) -> None:
    """Validate and reload one staged nginx route, retaining a complete rollback copy."""
    if digest(NGINX_FILE) not in {state["nginx_sha256"], state["new_nginx_sha256"]}:
        raise CutoverError("Nginx config drifted")
    source = receipt.parent / ("old.nginx" if old else "new.nginx")
    expected = state["nginx_sha256"] if old else state["new_nginx_sha256"]
    if digest(source) != expected:
        raise CutoverError("Nginx staging changed")
    replace_file(source, NGINX_FILE)
    run("docker", "exec", "nginx", "nginx", "-t")
    run("docker", "exec", "nginx", "nginx", "-s", "reload")


def compose(state: dict, *args: str) -> str:
    """Bind the exact running image, release, environment and package."""
    return run(
        "docker",
        "compose",
        "--env-file",
        str(ENV_FILE),
        "-f",
        state["config"],
        *args,
        env=os.environ
        | {
            "COMMUNITY_BOT_ENV_FILE": str(ENV_FILE),
            "COMMUNITY_BOT_IMAGE": state["image"],
            "COMMUNITY_BOT_RELEASE": state["release"],
        },
    )


def validate(state: dict) -> None:
    """Recheck measured identities, schema and Compose services before mutation."""
    validate_environment_file(ENV_FILE)
    if (
        digest(ENV_FILE) != state["env_sha256"]
        or digest(Path(state["config"])) != state["config_sha256"]
    ):
        raise CutoverError("Environment or Compose drifted")
    for name in (WEB, WORKER):
        item = inspect(name)
        if (
            item["Image"] != state["image"]
            or item["Config"]["Labels"].get("com.docker.compose.project.config_files")
            != state["config"]
        ):
            raise CutoverError("Runtime identity drifted")
    if set(compose(state, "config", "--services").splitlines()) != SERVICES:
        raise CutoverError("Unexpected Compose services")
    values = read_dotenv(ENV_FILE)
    head = run(
        "docker",
        "exec",
        "community-mini-app-core-postgres-1",
        "psql",
        "-X",
        "-U",
        values["POSTGRES_USER"],
        "-d",
        values["POSTGRES_DB"],
        "-Atc",
        "SELECT version_num FROM alembic_version",
    )
    if head != "0033":
        raise CutoverError("Expected schema 0033")


def verify(state: dict) -> None:
    """Wait for healthy exact runtime and its fresh worker heartbeat."""
    program = "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/readyz',timeout=5).read().decode())"
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            result = json.loads(run("docker", "exec", WEB, "python", "-c", program))
            if result.get("healthy") and result.get("release") == state["release"]:
                return
        except (CutoverError, json.JSONDecodeError):
            pass
        time.sleep(2)
    raise CutoverError("Exact readiness timeout")


def replace_env(source: Path) -> None:
    """Atomically promote a root-private staged environment without logging it."""
    replace_file(source, ENV_FILE)


def replace_file(source: Path, destination: Path) -> None:
    """Replace only a measured destination from its private staged copy."""
    temporary = destination.with_name(f".{destination.name}.telegram-stage")
    if temporary.exists():
        raise CutoverError("Unresolved environment staging file")
    with temporary.open("xb") as out:
        temporary.chmod(0o600)
        out.write(source.read_bytes())
        out.flush()
        os.fsync(out.fileno())
    temporary.replace(destination)


def apply(state: dict, receipt: Path) -> None:
    """Recover the previous env and Telegram controls on any activation error."""
    validate(state)
    if digest(receipt.parent / "new.env") != state["new_env_sha256"]:
        raise CutoverError("Staged environment changed")
    current = runtime("inspect")
    if any(current[key] != state["telegram"][key] for key in ("commands", "url", "menu")) or (
        current["webhook"]["url"] != state["telegram"]["webhook"]["url"]
    ):
        raise CutoverError("Telegram state drifted; prepare again")
    state["phase"] = "activating"
    save(receipt, state)
    try:
        replace_env(receipt.parent / "new.env")
        compose(state, "up", "-d", "--no-deps", "--force-recreate", "worker", "web")
        verify(state)
        edge(state, receipt)
        runtime("apply")
        if runtime("inspect")["menu"] != state["telegram"]["menu"]:
            raise CutoverError("Launch menu unexpectedly changed")  # noqa: TRY301
    except Exception:
        restore(state, receipt)
        raise
    state["phase"] = "ready"
    save(receipt, state)


def restore(state: dict, receipt: Path) -> None:
    """Recover after a failed activation or interrupted SSH session, without DB restore."""
    if digest(receipt.parent / "old.env") != state["env_sha256"] or digest(ENV_FILE) not in {
        state["env_sha256"],
        state["new_env_sha256"],
    }:
        raise CutoverError("Environment drift prevents rollback")
    # An existing webhook must receive its original secret, not the staged secret.
    replace_env(receipt.parent / "old.env")
    compose(state, "up", "-d", "--no-deps", "--force-recreate", "worker", "web")
    verify(state)
    edge(state, receipt, old=True)
    runtime("restore", state["telegram"])
    state["phase"] = "rolled_back"
    save(receipt, state)


def prepare() -> Path:
    """Measure a ready deployment and save private reversible activation inputs."""
    web = inspect(WEB)
    labels = web["Config"]["Labels"]
    config = Path(labels["com.docker.compose.project.config_files"]).resolve(strict=True)
    if (
        not config.is_relative_to(ROOT / "shared" / "releases")
        or config.name != "compose.production.yaml"
    ):
        raise CutoverError("Unexpected Compose package")
    validate_environment_file(config)
    validate_environment_file(ENV_FILE)
    state: dict[str, Any] = {
        "release": labels["org.opencontainers.image.revision"],
        "image": web["Image"],
        "config": str(config),
        "config_sha256": digest(config),
        "env_sha256": digest(ENV_FILE),
        "phase": "prepared",
        "head": "0033",
    }
    validate(state)
    verify(state)
    state["telegram"] = runtime("inspect")
    nginx = inspect("nginx")
    if not any(
        m.get("Source") == str(NGINX_FILE.parent) and m.get("Destination") == "/etc/nginx/conf.d"
        for m in nginx["Mounts"]
    ):
        raise CutoverError("Nginx mount mismatch")
    if NGINX_FILE.is_symlink() or NGINX_FILE.stat().st_uid != 0:
        raise CutoverError("Nginx file is not root-owned regular input")
    run("docker", "exec", "nginx", "nginx", "-t")
    old_nginx = NGINX_FILE.read_bytes()
    new_nginx = nginx_content(old_nginx.decode())
    directory = ROOT / "shared" / "releases" / f"telegram-{uuid4().hex}"
    directory.mkdir(mode=0o700)
    original = ENV_FILE.read_bytes()
    values = read_dotenv(ENV_FILE)
    new = environment_content(
        original.decode(), values.get("TELEGRAM_WEBHOOK_SECRET") or secrets.token_urlsafe(48)
    )
    for name, content in (
        ("old.env", original),
        ("new.env", new),
        ("old.nginx", old_nginx),
        ("new.nginx", new_nginx),
    ):
        with (directory / name).open("xb") as stream:
            (directory / name).chmod(0o600)
            stream.write(content)
    receipt = directory / "receipt.json"
    state["new_env_sha256"] = digest(directory / "new.env")
    state["nginx_sha256"] = digest(directory / "old.nginx")
    state["new_nginx_sha256"] = digest(directory / "new.nginx")
    save(receipt, state)
    return receipt


def main() -> None:
    """Run explicit prepare/apply, never on application startup."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "apply", "recover", "status", "probe"))
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if os.name != "posix" or os.geteuid() != 0:
        raise CutoverError("Requires Linux root")
    with (ROOT / "shared" / "releases" / "dev-deploy.lock").open("a") as lock:
        fcntl = importlib.import_module("fcntl")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.mode == "probe":
            print(json.dumps(runtime("probe")))
        elif args.mode == "prepare":
            print(json.dumps({"prepared_receipt": str(prepare())}))
        else:
            if args.receipt is None:
                raise CutoverError("Receipt required")
            validate_environment_file(args.receipt)
            state = json.loads(args.receipt.read_text())
            if args.mode == "status":
                print(
                    json.dumps(
                        {key: state[key] for key in ("phase", "release", "image", "config", "head")}
                    )
                )
                return
            if args.mode == "recover" and state["phase"] == "activating":
                restore(state, args.receipt)
            elif args.mode == "apply" and state["phase"] == "prepared":
                apply(state, args.receipt)
            else:
                raise CutoverError("Receipt is not prepared; do not repeat activation")
            print(
                json.dumps(
                    {"phase": state["phase"], "release": state["release"], "head": state["head"]}
                )
            )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - do not disclose transport secrets.
        detail = str(error) if isinstance(error, CutoverError) else type(error).__name__
        print(f"Activation stopped: {detail}", file=sys.stderr)
        raise SystemExit(1) from None
