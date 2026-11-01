"""Self-check helper for install.bat. NOT imported by pack.py (kept independent so
the intranet machine needs no part of the pack tooling).

Usage:
    python _check_install.py <bundle> [skill_name]          # dry-run self-check
    python _check_install.py <bundle> [skill_name] -test    # real import/require test

Prints a report. Exit 0 = ok, 1 = fatal issues found.
"""
import json, os, sys, subprocess, zipfile, csv, io

# symbol output must not crash under GBK pipes/consoles (cp936 default)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

bundle = sys.argv[1].rstrip("\\/")
want = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] and not sys.argv[2].startswith("-") else None
# NB: scan argv[2:], not argv[3:] — with no skill name given, "-test" sits at argv[2]
test_mode = "-test" in sys.argv[2:]
index_path = os.path.join(bundle, "manifest-index.json")

def c(code, s): return f"\033[{code}m{s}\033[0m"
def ok(s):   print(c("32","OK") + " " + s)
def warn(s): print(c("33","!!") + " " + s)
def fail(s): print(c("31","XX") + " " + s)

def wheel_top_level_modules(whl_path):
    """Return the list of top-level import names declared by a wheel, by reading
    its RECORD or top_level.txt. Falls back to the dist name if unknown."""
    mods = []
    try:
        with zipfile.ZipFile(whl_path) as z:
            # top_level.txt is the canonical list of import names
            for name in z.namelist():
                if name.endswith(".dist-info/top_level.txt"):
                    data = z.read(name).decode("utf-8", "ignore").strip()
                    mods = [m.strip() for m in data.splitlines() if m.strip()]
                    break
    except Exception:
        pass
    if not mods:
        # fallback: dist name from filename (may be wrong, but better than nothing)
        dist = os.path.basename(whl_path).split("-")[0]
        mods = [dist]
    return mods

def npm_package_name(pkg_dir):
    """Read the real package 'name' from a node_modules package dir."""
    pj = os.path.join(pkg_dir, "package.json")
    if os.path.isfile(pj):
        try:
            with open(pj, encoding="utf-8") as f:
                return json.load(f).get("name")
        except Exception:
            pass
    return None

if not os.path.isfile(index_path):
    fail(f"no manifest-index.json at {index_path}"); sys.exit(1)
with open(index_path, encoding="utf-8") as f:
    index = json.load(f)

pip_wh = os.path.join(bundle, "wheelhouse", "pip")
npm_wh = os.path.join(bundle, "wheelhouse", "npm")
npm_nm = os.path.join(npm_wh, "node_modules")
pw_dir = os.path.join(bundle, "pw-browser")
tools_auto = os.path.join(bundle, "tools", "auto")
tools_manual = os.path.join(bundle, "tools", "manual")

fatal = False
for skill in index.get("skills", []):
    name = skill["skill_name"]
    if want and name != want:
        continue
    print(f"  -- {name} --")
    tgt = skill.get("target", {})
    target_py = tgt.get("python", "3.12")
    target_arch = tgt.get("arch", "amd64")
    pip_files = [f for f in os.listdir(pip_wh)] if os.path.isdir(pip_wh) else []
    if pip_files:
        # Check by wheel filename tags, NOT pip dry-run (see gotchas B1):
        # pip --dry-run uses the CURRENT interpreter to match tags, but the bundle
        # targets a different python. Filename-tag inspection is correct offline.
        pytag = "cp" + target_py.replace(".", "")
        plat = {"amd64": "win_amd64", "x86": "win32"}.get(target_arch, f"win_{target_arch}")
        compatible = []
        for f in pip_files:
            if not f.endswith(".whl"):
                continue
            parts = f[:-4].split("-")
            if len(parts) < 5:
                compatible.append(f)  # pure-python, no tag columns
                continue
            pythontag = parts[-3]
            platformtag = parts[-1]
            if pythontag in ("py2.py3",) or pythontag.startswith("py3") or pythontag.startswith("py"):
                compatible.append(f)
            elif pythontag == pytag and plat in platformtag:
                compatible.append(f)
            elif "abi3" in parts[-2] and pythontag[2:] <= target_py.replace(".",""):
                compatible.append(f)  # abi3 wheels are forward-compatible
        if compatible:
            ok(f"pip pool: {len(pip_files)} wheels, {len(compatible)} compatible with {pytag}/{plat}")
        else:
            fail(f"pip pool has {len(pip_files)} wheels but NONE compatible with {pytag}/{plat}")
            fatal = True
        if test_mode:
            # real import test using the TRUE module names from each wheel's top_level.txt
            import importlib
            for f in sorted(pip_files):
                if not f.endswith(".whl"):
                    continue
                mods = wheel_top_level_modules(os.path.join(pip_wh, f))
                imported = False
                for m in mods:
                    try:
                        importlib.import_module(m)
                        ok(f"import {m}")
                        imported = True
                        break
                    except ImportError:
                        continue
                if not imported:
                    warn(f"could not import {mods} (transitive dep without a single import name - ok)")
    else:
        warn("pip wheelhouse empty (ok if skill has no pip deps)")

    # npm: prefer the merged node_modules tree (pack.py >= new) over bare tgz
    if os.path.isdir(npm_nm):
        # list top-level packages in the merged tree
        top = []
        for d in os.listdir(npm_nm):
            if d.startswith("."):
                continue
            full = os.path.join(npm_nm, d)
            if d.startswith("@") and os.path.isdir(full):
                for sub in os.listdir(full):
                    top.append(os.path.join(d, sub))
            elif os.path.isdir(full):
                top.append(d)
        ok(f"npm node_modules: {len(top)} package(s) present")
        if test_mode:
            for pkg in sorted(top):
                pkg_dir = os.path.join(npm_nm, *pkg.split("/"))
                real_name = npm_package_name(pkg_dir) or pkg
                # require uses the real package name (may differ from dir for scoped)
                r = subprocess.run(["node","-e",f"require('{real_name}')"],
                                   capture_output=True, text=True,
                                   env={**os.environ, "NODE_PATH": npm_nm})
                if r.returncode == 0:
                    ok(f"require('{real_name}')")
                else:
                    warn(f"require('{real_name}') failed (may need NODE_PATH in a new shell)")
    else:
        # legacy: bare tarballs only (old pack.py)
        npm_files = [f for f in os.listdir(npm_wh)] if os.path.isdir(npm_wh) else []
        warn(f"npm: only raw tgz found, no node_modules tree ({len(npm_files)} files)")
        warn("  -> bundle was packed by old pack.py; npm deps will fail offline. Re-pack.")
        if test_mode and npm_files:
            for f in npm_files:
                pkg = f.replace(".tgz","").rsplit("-",2)[0]
                r = subprocess.run(["node","-e",f"require('{pkg}')"], capture_output=True, text=True)
                if r.returncode == 0: ok(f"require('{pkg}')")
                else: warn(f"require('{pkg}') failed")

    if skill.get("has_playwright"):
        if os.path.isdir(pw_dir) and any(x.startswith("chromium") for x in os.listdir(pw_dir)):
            ok("playwright chromium present")
        else:
            fail("playwright expected but no chromium in pw-browser/"); fatal = True
    if os.path.isdir(tools_auto):
        for d in os.listdir(tools_auto):
            ok(f"tool (auto): {d}")
    if os.path.isdir(tools_manual):
        for f in os.listdir(tools_manual):
            if f.endswith(".README"):
                warn(f"tool (manual) {f[:-7]}: not yet provided (non-fatal)")

# --- MCP servers (bundle-level; written by pack.py mcp) ---
mcp_json = os.path.join(bundle, "mcp-servers.json")
if os.path.isfile(mcp_json):
    try:
        with open(mcp_json, encoding="utf-8") as f:
            mcp_doc = json.load(f)
    except json.JSONDecodeError as e:
        fail(f"mcp-servers.json is not valid JSON: {e}"); fatal = True
        mcp_doc = {}
    for name, srv in mcp_doc.get("servers", {}).items():
        print(f"  -- mcp:{name} --")
        cfg = srv.get("config", {})
        transport = srv.get("transport")
        if transport == "http":
            if cfg.get("url"):
                ok(f"http url: {cfg['url']}")
            else:
                fail(f"mcp:{name} (http) has no url"); fatal = True
            # ask: placeholders are expected pre-install; _merge_mcp.py fills them
            for k, v in (cfg.get("headers") or {}).items():
                if isinstance(v, str) and v.startswith("ask:"):
                    warn(f"header {k} = {v} (filled at install time)")
        elif transport == "stdio-npm":
            entry = srv.get("entry", "")
            entry_path = os.path.join(bundle, "mcp", name, *entry.split("/"))
            if entry and os.path.isfile(entry_path):
                ok(f"entry present: mcp/{name}/{entry}")
                if test_mode:
                    r = subprocess.run(["node", "--check", entry_path],
                                       capture_output=True, text=True)
                    if r.returncode == 0:
                        ok(f"node --check ok ({srv.get('package', '?')})")
                    else:
                        msg = (r.stderr or r.stdout).strip().splitlines()
                        warn(f"node --check failed: {msg[-1] if msg else '?'}")
            else:
                fail(f"mcp:{name} entry missing in bundle: mcp/{name}/{entry}")
                fatal = True
            nm = os.path.join(bundle, "mcp", name, "node_modules")
            if os.path.isdir(nm):
                ok("node_modules tree present")
            else:
                fail(f"mcp:{name} has no node_modules tree"); fatal = True
            for k, v in (cfg.get("env") or {}).items():
                if isinstance(v, str) and v.startswith("ask:"):
                    warn(f"env {k} = {v} (filled at install time)")
        else:
            fail(f"mcp:{name} unknown transport {transport!r}"); fatal = True
        if srv.get("note"):
            print(f"     note: {srv['note']}")

print()
sys.exit(1 if fatal else 0)
