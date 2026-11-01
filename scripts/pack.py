#!/usr/bin/env python
"""pack.py — online-machine packer for offline-bundle-skill.

Reads a manifest, cross-downloads deps into a shared wheelhouse, copies the skill
body into a persistent bundle, appends to manifest-index.json.

Usage:
    python pack.py add <skill-dir> [--manifest <m.json>] [--target "py:3.12,os:win,arch:amd64,node:20"] [--bundle <dir>]
    python pack.py mcp --manifest <mcp.json> [--bundle <dir>]

Target priority: --target > manifest.target > detected localhost.
"""
import argparse
import json
import os
import platform
import sys

# symbol output (✓/✗/中文) must not crash under GBK pipes/consoles (intranet cmd
# defaults to cp936); UTF-8 with errors=replace is safe for console and redirect
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _schema import validate_manifest, validate_mcp_manifest

# --- logging helpers ---------------------------------------------------------
def _c(code, s): return f"\033[{code}m{s}\033[0m"
def ok(s):   print(_c("32", "✓") + " " + s)
def info(s): print(_c("34", "→") + " " + s)
def warn(s): print(_c("33", "○") + " " + s)
def fail(s): print(_c("31", "✗") + " " + s)

# --- platform detection ------------------------------------------------------
def detect_target():
    """Best-effort localhost target detection."""
    arch = "amd64" if platform.machine().lower() in ("amd64", "x86_64") else platform.machine().lower()
    py = "%d.%d" % sys.version_info[:2]
    node = "20"  # default; real node version checked at download time
    return {"python": py, "os": "win", "arch": arch, "node": node}

def parse_target(s):
    """Parse 'py:3.12,os:win,arch:amd64,node:20' into a target dict."""
    keymap = {"py": "python", "os": "os", "arch": "arch", "node": "node"}
    out = {}
    for part in s.split(","):
        part = part.strip()
        if not part: continue
        if ":" not in part:
            raise ValueError(f"bad target part {part!r}, expected key:value")
        k, v = part.split(":", 1)
        out[keymap.get(k.strip(), k.strip())] = v.strip()
    return out

# --- manifest loading --------------------------------------------------------
def load_manifest(path, validator=validate_manifest):
    if not os.path.isfile(path):
        fail(f"manifest not found: {path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    # Try parsing as-is first (real manifests are strict JSON).
    # Only fall back to comment-stripping if direct parse fails, and only strip
    # lines that start with // (after optional whitespace) — never inline //,
    # because URLs contain "//" inside string values.
    m = _try_load(raw)
    if m is None:
        m = _try_load(_strip_json_comments(raw))
    if m is None:
        fail(f"manifest is not valid JSON (even after stripping // comments)")
        sys.exit(1)
    errors = validator(m)
    if errors:
        fail("manifest validation failed:")
        for e in errors:
            print("    " + e)
        sys.exit(1)
    return m

def _try_load(raw):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None

def _strip_json_comments(raw):
    """Strip only full-line // comments (lines whose first non-space chars are //).

    NOTE: we deliberately do NOT strip inline // because URL string values like
    'https://...' contain '//' that is NOT a comment. The manifest template uses
    legitimate JSON keys like "//": "explanation" which parse fine without stripping.
    """
    out = []
    for line in raw.splitlines():
        if line.lstrip().startswith("//"):
            continue
        out.append(line)
    return "\n".join(out)

def resolve_target(args, manifest):
    """Apply priority: --target > manifest.target > detect localhost."""
    if args.target:
        t = parse_target(args.target)
        info(f"using --target from command line: {t}")
        return t
    if manifest.get("target"):
        info(f"using manifest.target: {manifest['target']}")
        return manifest["target"]
    t = detect_target()
    warn(f"no target specified — using detected localhost: {t}")
    warn("confirm this matches the intranet machine before proceeding.")
    resp = input("  continue? [y/N] ").strip().lower()
    if resp != "y":
        fail("aborted by user.")
        sys.exit(1)
    return t

# --- pip download ------------------------------------------------------------
def download_pip(deps_pip, target, bundle):
    """Cross-download pip wheels into bundle/wheelhouse/pip/. Idempotent + dedup."""
    if not deps_pip:
        info("no pip deps, skipping.")
        return 0
    wheelhouse = os.path.join(bundle, "wheelhouse", "pip")
    os.makedirs(wheelhouse, exist_ok=True)
    arch = target["arch"]
    plat = {"amd64": "win_amd64", "x86": "win32"}.get(arch, f"win_{arch}")
    # build requirement specs (name + optional version)
    specs = []
    for entry in deps_pip:
        name = entry["name"]
        ver = entry.get("version")
        specs.append(f"{name}{ver}" if ver else name)
    info(f"downloading {len(specs)} pip package(s) for python {target['python']} {plat}...")
    # pip download resolves transitive deps when --no-deps is absent
    cmd = [
        sys.executable, "-m", "pip", "download",
        "-d", wheelhouse,
        "--python-version", target["python"],
        "--platform", plat,
        "--only-binary", ":all:",
    ] + specs
    info("running: " + " ".join(cmd))
    import subprocess
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        fail("pip download failed. stderr:")
        print(result.stderr)
        if "No matching distribution" in result.stderr or "only-binary" in result.stderr:
            advise = (
                "  -> A package has no prebuilt wheel for the target "
                f"(python {target['python']}/{plat}).\n"
                "    Options: pin a different version in manifest, or use a "
                "python version that has wheels for this package."
            )
            print(advise)
        sys.exit(1)
    wheels = [f for f in os.listdir(wheelhouse) if f.endswith((".whl", ".tar.gz"))]
    ok(f"pip wheelhouse has {len(wheels)} file(s) at {wheelhouse}")
    return len(wheels)

# --- npm pack ----------------------------------------------------------------
def download_npm(deps_npm, bundle):
    """Install npm deps (with full transitive dep tree) into a shared node_modules.

    Produces bundle/wheelhouse/npm/node_modules/  <- merged, deduped, offline-ready
            bundle/wheelhouse/npm/*.tgz           <- raw tarballs kept for reference

    WHY not just `npm pack`: a bare tgz has no bundled deps, so `npm install -g
    docx.tgz` on an offline intranet tries to fetch transitive deps from the
    registry and fails. We instead `npm install` each package so the whole
    dependency tree is materialized on disk; the merged node_modules is then
    copyable to a global path + NODE_PATH on the intranet (no npm, no network).
    """
    if not deps_npm:
        info("no npm deps, skipping.")
        return 0
    npm_dir = os.path.join(bundle, "wheelhouse", "npm")
    nm_dir = os.path.join(npm_dir, "node_modules")
    os.makedirs(npm_dir, exist_ok=True)
    # ensure a package.json exists so npm treats npm_dir as a project root
    pj = os.path.join(npm_dir, "package.json")
    if not os.path.isfile(pj):
        with open(pj, "w", encoding="utf-8") as f:
            f.write('{"name":"offline-bundle-npm","version":"1.0.0","private":true}')
    import subprocess
    count = 0
    for entry in deps_npm:
        name = entry["name"]
        ver = entry.get("version")
        pkg = f"{name}@{ver}" if ver else name
        info(f"npm install {pkg} (full dep tree)...")
        # --no-audit --no-fund: silence noise; omit=dev: skip devDeps
        cmd = ["npm", "install", "--no-audit", "--no-fund", "--omit=dev", pkg]
        result = subprocess.run(cmd, cwd=npm_dir, capture_output=True, text=True, shell=True)
        if result.returncode != 0:
            fail(f"npm install failed for {pkg}:")
            print(result.stderr)
            sys.exit(1)
        # also keep a raw tarball for reference (best-effort; ignore failure)
        subprocess.run(["npm", "pack", pkg, "--pack-destination", npm_dir],
                       cwd=npm_dir, capture_output=True, text=True, shell=True)
        ok(f"npm: {pkg} installed")
    # count top-level packages actually installed
    top_pkgs = [d for d in os.listdir(nm_dir) if not d.startswith(".")
                and os.path.isdir(os.path.join(nm_dir, d))] if os.path.isdir(nm_dir) else []
    # scoped packages live under @scope/name -> count dirs under @*
    total = len(top_pkgs)
    scoped = [d for d in top_pkgs if d.startswith("@")]
    for s in scoped:
        total += len(os.listdir(os.path.join(nm_dir, s))) - 1  # minus the dir itself
    ok(f"npm node_modules has {total} package(s) at {nm_dir}")
    return total

# --- playwright browser ------------------------------------------------------
def download_playwright(pw, target, bundle):
    """If deps.playwright present, install chromium into bundle/pw-browser/."""
    if not pw:
        info("no playwright dep, skipping.")
        return False
    browsers = pw.get("browsers", ["chromium"])
    version = pw.get("version")
    pw_cache = os.path.join(bundle, "pw-browser")
    os.makedirs(pw_cache, exist_ok=True)
    import subprocess
    env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=pw_cache)
    pkg = f"playwright@{version}" if version else "playwright"
    for browser in browsers:
        info(f"playwright install {browser} (via {pkg}) -> {pw_cache}")
        # npx --yes ensures we use the pinned version without global install
        cmd = ["npx", "--yes", pkg, "install", browser]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, shell=True)
        if result.returncode != 0:
            fail(f"playwright install failed for {browser}:")
            print(result.stderr)
            sys.exit(1)
    found = any(name.startswith("chromium") for name in os.listdir(pw_cache))
    if found:
        ok(f"playwright browser(s) at {pw_cache}")
    else:
        warn(f"playwright ran but no chromium dir found in {pw_cache} - verify manually")
    return True

# --- tools (auto + manual) ---------------------------------------------------
def download_tools(deps_tools, target, bundle):
    """Download auto tools, write placeholders for manual tools."""
    if not deps_tools:
        info("no tools deps, skipping.")
        return {"auto": 0, "manual": 0}
    auto_dir = os.path.join(bundle, "tools", "auto")
    manual_dir = os.path.join(bundle, "tools", "manual")
    os.makedirs(auto_dir, exist_ok=True)
    os.makedirs(manual_dir, exist_ok=True)
    import zipfile, urllib.request, shutil
    auto_count = 0
    manual_count = 0
    for tool in deps_tools:
        name = tool["name"]
        kind = tool["kind"]
        if kind == "manual":
            note = tool["note"]
            readme = os.path.join(manual_dir, f"{name}.README")
            with open(readme, "w", encoding="utf-8") as f:
                f.write(f"MANUAL TOOL: {name}\n\n{note}\n")
            warn(f"manual tool '{name}': place its installer in {manual_dir}")
            warn(f"  note: {note}")
            manual_count += 1
            continue
        # auto: fill url_template, download, extract
        version = tool["version"]
        url = tool["url_template"].replace("{version}", version)
        extract_root = tool.get("extract_root", "").replace("{version}", version)
        dest = os.path.join(auto_dir, name)
        info(f"tool {name} {version}: downloading {url}")
        zip_path = dest + ".zip"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pack.py"})
            with urllib.request.urlopen(req) as r, open(zip_path, "wb") as f:
                shutil.copyfileobj(r, f)
        except Exception as e:
            fail(f"download failed for {name}: {e}")
            print(f"  url was: {url}")
            sys.exit(1)
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        os.makedirs(dest, exist_ok=True)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(dest)
        os.remove(zip_path)
        # if extract_root set, hoist that subdir up
        if extract_root:
            sub = os.path.join(dest, extract_root)
            if os.path.isdir(sub):
                tmp = dest + "__tmp"
                os.rename(sub, tmp)
                shutil.rmtree(dest)
                os.rename(tmp, dest)
        ok(f"tool {name} {version} extracted to {dest}")
        auto_count += 1
    return {"auto": auto_count, "manual": manual_count}

# --- MCP servers ----------------------------------------------------------------
def resolve_npm_bin(pkg_json, pkg_name, want_bin=None):
    """Pick the entry script from an installed package's 'bin' field.

    bin may be a string ("dist/x.js") or a map ({"cmd": "dist/x.js"}).
    Selection: explicit want_bin > the key equal to the package basename
    (@scope/name -> name) > the first entry. Returns a path relative to the
    package root, or None when there is nothing usable.
    """
    bin_field = pkg_json.get("bin")
    if isinstance(bin_field, str):
        return bin_field
    if isinstance(bin_field, dict):
        if want_bin:
            return bin_field.get(want_bin)
        base = pkg_name.rsplit("/", 1)[-1]
        if base in bin_field:
            return bin_field[base]
        for v in bin_field.values():
            return v
    return None

def pack_mcp_stdio(srv, bundle):
    """Materialize one stdio-npm MCP server as a self-contained tree.

    bundle/mcp/<name>/ holds its own package.json + node_modules (whole tree,
    transitive deps included). Deliberately NOT the shared wheelhouse pool:
    the zcode config references the entry script by absolute path, and Node's
    standard resolution (ESM included — ESM ignores NODE_PATH, see gotchas E1)
    then finds deps in <name>/node_modules by walking up from the entry.
    """
    import shutil, subprocess
    name = srv["name"]
    pkg = srv["package"]
    pkg_name = pkg["name"]
    ver = pkg.get("version")
    spec = f"{pkg_name}@{ver}" if ver else pkg_name
    srv_dir = os.path.join(bundle, "mcp", name)
    if os.path.isdir(srv_dir):
        info(f"mcp[{name}]: replacing existing tree {srv_dir}")
        shutil.rmtree(srv_dir)
    os.makedirs(srv_dir, exist_ok=True)
    pj = os.path.join(srv_dir, "package.json")
    with open(pj, "w", encoding="utf-8") as f:
        f.write(json.dumps({"name": f"offline-bundle-mcp-{name}",
                            "version": "1.0.0", "private": True}))
    info(f"mcp[{name}]: npm install {spec} (full dep tree)...")
    result = subprocess.run(["npm", "install", "--no-audit", "--no-fund",
                             "--omit=dev", spec],
                            cwd=srv_dir, capture_output=True, text=True, shell=True)
    if result.returncode != 0:
        fail(f"npm install failed for {spec}:")
        print(result.stderr)
        sys.exit(1)
    nm = os.path.join(srv_dir, "node_modules")
    pkg_dir = os.path.join(nm, *pkg_name.split("/"))
    pkg_pj = os.path.join(pkg_dir, "package.json")
    if not os.path.isfile(pkg_pj):
        fail(f"mcp[{name}]: installed package manifest not found: {pkg_pj}")
        sys.exit(1)
    with open(pkg_pj, encoding="utf-8") as f:
        installed = json.load(f)
    entry = resolve_npm_bin(installed, installed.get("name", pkg_name), srv.get("bin"))
    if not entry:
        hint = f" (wanted {srv['bin']!r})" if srv.get("bin") else ""
        fail(f"mcp[{name}]: no usable bin entry in {pkg_name}{hint}")
        sys.exit(1)
    entry = entry.replace("\\", "/")
    while entry.startswith("./"):
        entry = entry[2:]
    if not os.path.isfile(os.path.join(pkg_dir, *entry.split("/"))):
        fail(f"mcp[{name}]: bin entry does not exist on disk: {entry}")
        sys.exit(1)
    # count top-level packages (incl. @scope/*), same convention as download_npm
    top = [d for d in os.listdir(nm)
           if not d.startswith(".") and os.path.isdir(os.path.join(nm, d))]
    count = len(top)
    for d in top:
        if d.startswith("@"):
            count += len(os.listdir(os.path.join(nm, d))) - 1
    ok(f"mcp[{name}]: {spec} installed, entry node_modules/{pkg_name}/{entry}, "
       f"{count} package(s)")
    return {"package": spec, "entry": f"node_modules/{pkg_name}/{entry}",
            "count": count}

def build_mcp_record(srv, tree_info, now):
    """Render one server into its mcp-servers.json record (config fragment).

    The config uses ONLY canonical zcode MCP fields (type/url/headers/command/
    args/env/timeoutMs — unknown keys make zcode drop the server, gotchas E2)
    and absolute-path-ready args: {{INSTALL_DIR}} is expanded by _merge_mcp.py
    on the intranet machine (zcode does not expand ${...} in config servers).
    """
    rec = {
        "name": srv["name"],
        "transport": srv["transport"],
        "added": now,
        "note": srv.get("note", ""),
    }
    if srv["transport"] == "http":
        rec["install"] = "none"
        cfg = {"type": "http", "url": srv["url"]}
        if srv.get("headers"):
            cfg["headers"] = dict(srv["headers"])
        if srv.get("timeoutMs") is not None:
            cfg["timeoutMs"] = srv["timeoutMs"]
    else:  # stdio-npm
        rec["install"] = "tree"
        rec["package"] = tree_info["package"]
        rec["entry"] = tree_info["entry"]
        cfg = {"type": "stdio", "command": "node",
               "args": ["{{INSTALL_DIR}}\\" + tree_info["entry"].replace("/", "\\")]}
        if srv.get("env"):
            cfg["env"] = dict(srv["env"])
        if srv.get("timeoutMs") is not None:
            cfg["timeoutMs"] = srv["timeoutMs"]
    rec["config"] = cfg
    return rec

def update_mcp_servers_json(bundle, records):
    """Merge rendered server records into bundle/mcp-servers.json by name."""
    path = os.path.join(bundle, "mcp-servers.json")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    else:
        doc = {"bundle_version": "1.0", "created": now_iso(), "servers": {}}
    doc.setdefault("servers", {})
    for rec in records:
        if rec["name"] in doc["servers"]:
            info(f"mcp[{rec['name']}]: replacing previous record")
        doc["servers"][rec["name"]] = rec
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    ok(f"mcp-servers.json updated: {len(doc['servers'])} server(s) total")

def update_index_mcp(bundle, metas):
    """Record MCP servers into bundle/manifest-index.json.

    Creates the index when absent so an MCP-only bundle still passes
    install.bat's step [1] self-check.
    """
    index_path = os.path.join(bundle, "manifest-index.json")
    if os.path.isfile(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f)
    else:
        index = {"bundle_version": "1.0", "created": now_iso(), "skills": []}
    lst = index.get("mcp_servers", [])
    for meta in metas:
        lst = [s for s in lst if s.get("name") != meta["name"]]
        lst.append(meta)
    index["mcp_servers"] = lst
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    ok(f"manifest-index updated: {len(index['skills'])} skill(s), "
       f"{len(lst)} mcp server(s)")

# --- skill body copy ---------------------------------------------------------
def copy_skill_body(manifest, bundle, force):
    """Copy the skill directory into bundle/skills/<name>/."""
    name = manifest["skill_name"]
    src = manifest["skill_source"]
    dest = os.path.join(bundle, "skills", name)
    if os.path.isdir(dest) and not force:
        fail(f"skill '{name}' already in bundle at {dest}")
        fail("  re-run with --force to overwrite (your local edits will be lost).")
        sys.exit(1)
    import shutil
    if src["type"] == "local":
        src_path = src["path"]
        if not os.path.isdir(src_path):
            fail(f"skill_source.path not found: {src_path}")
            sys.exit(1)
        info(f"copying skill {name}: {src_path} -> {dest}")
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        shutil.copytree(src_path, dest, ignore=shutil.ignore_patterns(".git"))
        ok(f"skill body copied to {dest}")
    elif src["type"] == "git":
        url = src["url"]; ref = src.get("ref", "main")
        info(f"cloning skill {name}: {url}@{ref}")
        import subprocess, tempfile
        tmp = tempfile.mkdtemp()
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", ref, url, tmp],
            capture_output=True, text=True, shell=True)
        if result.returncode != 0:
            fail(f"git clone failed: {result.stderr}")
            sys.exit(1)
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        shutil.copytree(tmp, dest, ignore=shutil.ignore_patterns(".git"))
        shutil.rmtree(tmp, ignore_errors=True)
        ok(f"skill body cloned to {dest}")

def now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def update_index(manifest, target, bundle, pip_count, npm_count, tool_counts, has_pw):
    """Append/replace a record in bundle/manifest-index.json by skill_name."""
    index_path = os.path.join(bundle, "manifest-index.json")
    if os.path.isfile(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f)
    else:
        index = {"bundle_version": "1.0", "created": now_iso(), "skills": []}
    name = manifest["skill_name"]
    # dedup: replace any existing entry with the same name
    index["skills"] = [s for s in index["skills"] if s["skill_name"] != name]
    index["skills"].append({
        "skill_name": name,
        "added": now_iso(),
        "target": target,
        "source_type": manifest["skill_source"]["type"],
        "has_playwright": has_pw,
        "files": {
            "pip": pip_count,
            "npm": npm_count,
            "tools_auto": tool_counts["auto"],
            "tools_manual": tool_counts["manual"],
        },
    })
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    ok(f"manifest-index updated: {len(index['skills'])} skill(s) total")

def finalize_bundle(bundle):
    """Copy install.bat + helper scripts into the bundle root so it's self-contained on intranet.

    Every file install.bat invokes must be listed here (gotchas D1).
    """
    import shutil
    here = os.path.dirname(os.path.abspath(__file__))
    for fname in ("install.bat", "_check_install.py", "_merge_mcp.py"):
        src = os.path.join(here, fname)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(bundle, fname))
            ok(f"{fname} copied to bundle root")
        else:
            warn(f"{fname} not found at {src}")

# --- main --------------------------------------------------------------------
def cmd_add(args):
    info(f"=== pack add: {args.skill_dir} ===")
    mpath = args.manifest or os.path.join(args.skill_dir, "manifest.json")
    info(f"loading manifest: {mpath}")
    manifest = load_manifest(mpath)
    target = resolve_target(args, manifest)
    manifest["target"] = target  # freeze resolved target into manifest
    bundle = os.path.abspath(args.bundle or "./offline-bundle")
    info(f"bundle dir: {bundle}")
    ok("manifest loaded and validated.")
    os.makedirs(bundle, exist_ok=True)
    pip_count = download_pip(manifest["deps"].get("pip", []), target, bundle)
    npm_count = download_npm(manifest["deps"].get("npm", []), bundle)
    has_pw = download_playwright(manifest["deps"].get("playwright"), target, bundle)
    tool_counts = download_tools(manifest["deps"].get("tools", []), target, bundle)
    copy_skill_body(manifest, bundle, args.force)
    update_index(manifest, target, bundle, pip_count, npm_count, tool_counts, has_pw)
    finalize_bundle(bundle)

    # summary
    print("\n" + "=" * 44)
    ok(f"packed skill '{manifest['skill_name']}' into {bundle}")
    print(f"  pip files:     {pip_count}")
    print(f"  npm files:     {npm_count}")
    print(f"  playwright:    {'yes' if has_pw else 'no'}")
    print(f"  tools auto:    {tool_counts['auto']}")
    print(f"  tools manual:  {tool_counts['manual']} (place installers in bundle/tools/manual/)")
    print("=" * 44)
    info(f"next: copy {bundle} to the intranet machine, run install.bat --dry-run")

def cmd_mcp(args):
    info(f"=== pack mcp: {args.manifest} ===")
    m = load_manifest(args.manifest, validator=validate_mcp_manifest)
    bundle = os.path.abspath(args.bundle or "./offline-bundle")
    info(f"bundle dir: {bundle}")
    os.makedirs(bundle, exist_ok=True)
    records, metas = [], []
    for srv in m["servers"]:
        tree_info = None
        if srv["transport"] == "stdio-npm":
            tree_info = pack_mcp_stdio(srv, bundle)
        rec = build_mcp_record(srv, tree_info, now_iso())
        records.append(rec)
        meta = {"name": srv["name"], "transport": srv["transport"], "added": rec["added"]}
        if tree_info:
            meta["package"] = tree_info["package"]
        metas.append(meta)
    update_mcp_servers_json(bundle, records)
    update_index_mcp(bundle, metas)
    finalize_bundle(bundle)

    # summary
    print("\n" + "=" * 44)
    ok(f"packed {len(records)} MCP server(s) into {bundle}")
    for rec in records:
        if rec["transport"] == "http":
            print(f"  {rec['name']}: http (config-only) -> {rec['config']['url']}")
        else:
            print(f"  {rec['name']}: stdio-npm {rec['package']} ({rec['entry']})")
    print("=" * 44)
    info("next: copy the bundle to the intranet machine, run install.bat")
    info("      (it merges MCP config into ~/.zcode/cli/config.json via _merge_mcp.py)")

def main():
    p = argparse.ArgumentParser(prog="pack.py", description="offline-bundle packer")
    sub = p.add_subparsers(dest="command", required=True)
    pa = sub.add_parser("add", help="add a skill to the bundle")
    pa.add_argument("skill_dir", help="skill directory (contains SKILL.md)")
    pa.add_argument("--manifest", help="manifest.json path (default: <skill_dir>/manifest.json)")
    pa.add_argument("--target", help='target override "py:3.12,os:win,arch:amd64,node:20"')
    pa.add_argument("--bundle", help="bundle output dir (default: ./offline-bundle)")
    pa.add_argument("--force", action="store_true", help="overwrite a skill already in the bundle")
    pa.set_defaults(func=cmd_add)
    pm = sub.add_parser("mcp", help="add MCP servers to the bundle")
    pm.add_argument("--manifest", required=True, help="MCP manifest json path (see templates/mcp.template.json)")
    pm.add_argument("--bundle", help="bundle output dir (default: ./offline-bundle)")
    pm.set_defaults(func=cmd_mcp)
    args = p.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
