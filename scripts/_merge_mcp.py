"""MCP config installer for offline-bundle (intranet side). NOT imported by pack.py.

Reads bundle/mcp-servers.json (written by pack.py mcp on the online machine),
then:
  1. copies each stdio server's tree bundle/mcp/<name>/ -> <mcp-root>/<name>/
  2. resolves "ask:VAR" placeholders (prompted here, or via --set, because the
     values — e.g. NocoDB MCP tokens — are created on the intranet, never known
     at pack time and never stored in the bundle)
  3. merges the rendered config fragments into zcode's user config
     (~/.zcode/cli/config.json -> mcp.servers), backing the file up first.

zcode's MCP config schema is strict (unknown keys drop the server) and does not
expand ${...} templates, so fragments were rendered at pack time with canonical
fields only; the {{INSTALL_DIR}} token below is expanded by THIS script before
writing. See references/gotchas.md E2.

Usage:
    python _merge_mcp.py <bundle> [--dry-run] [--set NAME=VALUE ...]
                        [--config <path>] [--mcp-root <dir>] [--no-prompt]

Exit 0 = merged ok, 1 = fatal issue.
"""
import argparse
import copy
import getpass
import json
import os
import re
import shutil
import sys
from datetime import datetime

# symbol output must not crash under GBK pipes/consoles (cp936 default)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_ASK_RE = re.compile(r"ask:([A-Za-z0-9_]+)")
_SENSITIVE = ("TOKEN", "SECRET", "PASSWORD", "KEY")


def ok(s):   print("  OK " + s)
def warn(s): print("  !! " + s)
def fail(s): print("  XX " + s)


def now_ts():
    return datetime.now().strftime("%Y%m%d%H%M%S")


def read_value(var):
    """Prompt for one placeholder value.

    Sensitive names (TOKEN/SECRET/PASSWORD/KEY) use getpass - but only when
    stdin is a real tty: Windows getpass reads the CONSOLE directly, so under
    a piped/redirected stdin it would block forever. Non-tty falls back to a
    plain read (automation scenario; secrecy is moot without a human typing).
    """
    sensitive = any(s in var.upper() for s in _SENSITIVE)
    prompt = f"  value for {var}" + (" (input hidden): " if sensitive else ": ")
    if sensitive and sys.stdin.isatty():
        return getpass.getpass(prompt)
    if not sys.stdin.isatty() and sensitive:
        warn(f"{var}: stdin is not a tty - reading as plain input")
    return input(prompt).strip()


def default_config_path():
    return os.path.join(os.path.expanduser("~"), ".zcode", "cli", "config.json")


def default_mcp_root():
    pd = os.environ.get("ProgramData") or os.path.join(
        os.environ.get("SystemDrive", "C:"), "ProgramData")
    return os.path.join(pd, "zcode-mcp")


def scan_ask_vars(obj, found):
    """Collect every ask:VAR name appearing in any string leaf of a config fragment.

    Placeholders may appear inside larger strings (e.g.
    http://host/api/v2/mcp/ask:NOCODB_TOKEN_ID), so scan substrings, not just
    exact values.
    """
    if isinstance(obj, str):
        for m in _ASK_RE.finditer(obj):
            found.add(m.group(1))
    elif isinstance(obj, dict):
        for v in obj.values():
            scan_ask_vars(v, found)
    elif isinstance(obj, list):
        for v in obj:
            scan_ask_vars(v, found)


def resolve_value(s, values):
    """Substitute every ask:VAR occurrence in a string using resolved values."""
    return _ASK_RE.sub(lambda m: values.get(m.group(1), m.group(0)), s)


def render(obj, values):
    """Deep-render a config fragment: ask:VAR substitution + {{INSTALL_DIR}}."""
    if isinstance(obj, str):
        if "{{INSTALL_DIR}}" in obj:
            obj = obj.replace("{{INSTALL_DIR}}", values["__INSTALL_DIR__"])
        return resolve_value(obj, values)
    if isinstance(obj, dict):
        return {k: render(v, values) for k, v in obj.items()}
    if isinstance(obj, list):
        return [render(v, values) for v in obj]
    return obj


def install_tree(src, dst, dry_run):
    """Copy a stdio server tree into place, backing up any previous install."""
    if not os.path.isdir(src):
        fail(f"tree missing in bundle: {src}")
        return False
    if dry_run:
        ok(f"would copy tree {src} -> {dst}")
        return True
    if os.path.isdir(dst):
        bak = f"{dst}.bak.{now_ts()}"
        if os.path.isdir(bak):
            shutil.rmtree(bak, ignore_errors=True)
        try:
            os.rename(dst, bak)
            warn(f"backed up previous install to {os.path.basename(bak)}")
        except OSError:
            shutil.rmtree(dst, ignore_errors=True)
            warn(f"backup move failed for {dst}, removed old in place")
    shutil.copytree(src, dst)
    ok(f"tree installed: {dst}")
    return True


def main():
    ap = argparse.ArgumentParser(prog="_merge_mcp.py")
    ap.add_argument("bundle", help="bundle dir (contains mcp-servers.json)")
    ap.add_argument("--dry-run", action="store_true", help="show plan, change nothing")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                    help="resolve an ask: placeholder non-interactively (repeatable)")
    ap.add_argument("--config", default=None,
                    help=f"zcode config path (default: {default_config_path()})")
    ap.add_argument("--mcp-root", default=None,
                    help=f"install root for stdio trees (default: {default_mcp_root()}<name>)")
    ap.add_argument("--no-prompt", action="store_true",
                    help="never prompt; servers with unresolved placeholders are skipped")
    args = ap.parse_args()

    mcp_json = os.path.join(args.bundle, "mcp-servers.json")
    if not os.path.isfile(mcp_json):
        fail(f"no mcp-servers.json at {mcp_json} (nothing to install)")
        sys.exit(1)
    with open(mcp_json, encoding="utf-8") as f:
        doc = json.load(f)
    servers = doc.get("servers", {})
    if not servers:
        warn("mcp-servers.json declares no servers")
        sys.exit(0)

    config_path = args.config or default_config_path()
    mcp_root = args.mcp_root or default_mcp_root()

    print("=" * 46)
    print("  offline-bundle MCP install")
    print("=" * 46)
    print(f"  bundle:      {args.bundle}")
    print(f"  zcode conf:  {config_path}")
    print(f"  mcp root:    {mcp_root}")
    if args.dry_run:
        print("  mode:        DRY-RUN")
    print()

    fatal = False

    # 1) collect placeholders across all fragments
    asks = set()
    for srv in servers.values():
        scan_ask_vars(srv.get("config", {}), asks)

    # 2) resolve them: --set first, then interactive prompt
    values = {}
    for kv in args.set:
        if "=" not in kv:
            warn(f"--set expects NAME=VALUE, got {kv!r}; ignored")
            continue
        k, v = kv.split("=", 1)
        values[k] = v
    missing = [a for a in sorted(asks) if a not in values]
    for var in missing:
        if args.dry_run:
            continue  # reported per-server below
        if args.no_prompt:
            continue
        try:
            values[var] = read_value(var)
        except EOFError:
            values[var] = ""
        if not values[var]:
            warn(f"{var} left empty - the server may fail to authenticate")

    # 3) per-server: install trees + render fragments
    merged = {}
    for name, srv in servers.items():
        print(f"  -- mcp:{name} ({srv.get('transport')}) --")
        frag = copy.deepcopy(srv.get("config", {}))
        scan_ask_vars(frag, unresolved := set())
        unresolved -= set(values)
        if args.dry_run and unresolved:
            warn(f"placeholders to fill at real install: {sorted(unresolved)}")
        elif unresolved:
            warn(f"unresolved placeholders {sorted(unresolved)} and --no-prompt: "
                 f"server skipped")
            continue
        values_local = dict(values)
        values_local["__INSTALL_DIR__"] = os.path.join(mcp_root, name)
        if srv.get("install") == "tree":
            src = os.path.join(args.bundle, "mcp", name)
            if not install_tree(src, values_local["__INSTALL_DIR__"], args.dry_run):
                fatal = True
                continue
        merged[name] = render(frag, values_local)
        if srv.get("note"):
            print(f"     note: {srv['note']}")
    print()

    if not merged:
        fail("no MCP servers to merge into zcode config")
        sys.exit(1)

    # 4) merge into zcode user config (backup first, atomic write)
    if args.dry_run:
        for name, frag in merged.items():
            print(f"  would merge mcp.servers.{name}:")
            print("    " + json.dumps(frag, ensure_ascii=False, indent=4)
                  .replace("\n", "\n    "))
        print()
        warn("dry-run: config not modified")
        sys.exit(1 if fatal else 0)

    if os.path.isfile(config_path):
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except json.JSONDecodeError as e:
            fail(f"{config_path} is not valid JSON ({e}); fix it manually first — "
                 "this script never overwrites a config it cannot parse")
            sys.exit(1)
        bak = f"{config_path}.bak.{now_ts()}"
        shutil.copy2(config_path, bak)
        warn(f"backed up config to {os.path.basename(bak)}")
    else:
        cfg = {}
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        warn(f"no existing config; creating {config_path}")

    mcp = cfg.get("mcp")
    if not isinstance(mcp, dict):
        if mcp is None:
            mcp = cfg["mcp"] = {}
        else:
            fail(f"{config_path}: 'mcp' exists but is not an object; fix manually")
            sys.exit(1)
    srv_map = mcp.get("servers")
    if srv_map is None:
        srv_map = mcp["servers"] = {}
    elif not isinstance(srv_map, dict):
        fail(f"{config_path}: 'mcp.servers' exists but is not an object; fix manually")
        sys.exit(1)

    for name, frag in merged.items():
        if name in srv_map:
            warn(f"mcp.servers.{name}: replacing existing entry")
        srv_map[name] = frag
        ok(f"mcp.servers.{name} merged")

    tmp = config_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, config_path)
    ok(f"config written: {config_path}")

    print("=" * 46)
    print("  done. Restart zcode, then check Settings -> MCP.")
    print("=" * 46)
    sys.exit(1 if fatal else 0)


if __name__ == "__main__":
    main()
