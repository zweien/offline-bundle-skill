"""Manifest schema validation for offline-bundle-skill.

validate_manifest(manifest: dict) -> list[str]
validate_mcp_manifest(manifest: dict) -> list[str]
    Returns a list of human-readable error strings. Empty list = valid.

This module is PURE: no I/O, no exceptions for validation failures.
pack.py imports it to validate manifests before acting on them.
"""
import re

# skill_name / mcp server name: lowercase, kebab-case-ish (letters/digits/dash/underscore)
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_VALID_TOOL_KINDS = {"auto", "manual"}
_REQUIRED_TARGET = ("python", "os", "arch", "node")
_VALID_MCP_TRANSPORTS = {"http", "stdio-npm"}


def _err(msg):
    return [msg]


def validate_manifest(m):
    """Return list of error strings. Empty = valid."""
    errors = []
    if not isinstance(m, dict):
        return ["manifest must be a JSON object"]

    # --- skill_name ---
    name = m.get("skill_name")
    if not name:
        errors.append("skill_name is required")
    elif not isinstance(name, str) or not _NAME_RE.match(name):
        errors.append(
            "skill_name must be lowercase kebab-case (letters/digits/-/_): "
            f"got {name!r}"
        )

    # --- skill_source ---
    src = m.get("skill_source")
    if not isinstance(src, dict):
        errors.append("skill_source is required and must be an object")
    else:
        stype = src.get("type")
        if stype == "local":
            if not src.get("path"):
                errors.append("skill_source (local) requires a 'path'")
        elif stype == "git":
            if not src.get("url"):
                errors.append("skill_source (git) requires a 'url'")
        else:
            errors.append(
                f"skill_source.type must be 'local' or 'git': got {stype!r}"
            )

    # --- target ---
    target = m.get("target")
    if not isinstance(target, dict):
        errors.append("target is required and must be an object")
    else:
        for field in _REQUIRED_TARGET:
            if not target.get(field):
                errors.append(f"target.{field} is required")

    # --- deps ---
    deps = m.get("deps")
    if not isinstance(deps, dict):
        errors.append("deps is required and must be an object")
        return errors  # can't validate sub-entries without deps

    for required_dep in ("pip", "npm", "tools"):
        if required_dep not in deps:
            errors.append(f"deps.{required_dep} is required (use [] if none)")

    # --- deps.pip ---
    for i, entry in enumerate(deps.get("pip", [])):
        if not isinstance(entry, dict) or not entry.get("name"):
            errors.append(f"deps.pip[{i}] requires a 'name'")

    # --- deps.npm ---
    for i, entry in enumerate(deps.get("npm", [])):
        if not isinstance(entry, dict) or not entry.get("name"):
            errors.append(f"deps.npm[{i}] requires a 'name'")

    # --- deps.playwright (optional) ---
    if "playwright" in deps:
        pw = deps["playwright"]
        if not isinstance(pw, dict):
            errors.append("deps.playwright must be an object {browsers, version}")

    # --- deps.tools ---
    for i, tool in enumerate(deps.get("tools", [])):
        if not isinstance(tool, dict) or not tool.get("name"):
            errors.append(f"deps.tools[{i}] requires a 'name'")
            continue
        kind = tool.get("kind")
        if kind not in _VALID_TOOL_KINDS:
            errors.append(
                f"deps.tools[{i}].kind must be 'auto' or 'manual': got {kind!r}"
            )
            continue
        if kind == "auto":
            if not tool.get("url_template"):
                errors.append(f"deps.tools[{i}] (auto) requires 'url_template'")
            if not tool.get("version"):
                errors.append(f"deps.tools[{i}] (auto) requires 'version'")
        elif kind == "manual":
            if not tool.get("note"):
                errors.append(f"deps.tools[{i}] (manual) requires a 'note'")

    return errors


def validate_mcp_manifest(m):
    """Validate an MCP server manifest (pack.py mcp). Return list of errors.

    Shape: {"servers": [{"name", "transport": "http"|"stdio-npm", ...}]}
      - http: requires url; optional headers {name: str}, timeoutMs int.
        Nothing is downloaded; only a zcode config fragment is generated.
      - stdio-npm: requires package {name, version?}; optional env {name: str}.
        The whole dep tree is packed under bundle/mcp/<name>/.
    Any string value in headers/env may be "ask:VAR_NAME": prompted at intranet
    install time (secrets are created on the intranet, e.g. NocoDB MCP tokens).
    """
    errors = []
    if not isinstance(m, dict):
        return ["mcp manifest must be a JSON object"]

    servers = m.get("servers")
    if not isinstance(servers, list):
        return errors + ["servers is required and must be a list"]

    seen = set()
    for i, srv in enumerate(servers):
        where = f"servers[{i}]"
        if not isinstance(srv, dict):
            errors.append(f"{where} must be an object")
            continue

        name = srv.get("name")
        if not name:
            errors.append(f"{where} requires a 'name'")
        elif not isinstance(name, str) or not _NAME_RE.match(name):
            errors.append(
                f"{where}.name must be lowercase kebab-case (letters/digits/-/_): "
                f"got {name!r}"
            )
        elif name in seen:
            errors.append(f"duplicate server name {name!r}")
        else:
            seen.add(name)

        transport = srv.get("transport")
        if transport not in _VALID_MCP_TRANSPORTS:
            errors.append(
                f"{where}.transport must be 'http' or 'stdio-npm': got {transport!r}"
            )
            continue

        if transport == "http":
            url = srv.get("url")
            if not url:
                errors.append(f"{where} (http) requires a 'url'")
            elif not isinstance(url, str) or not (
                url.startswith("http://") or url.startswith("https://")
            ):
                errors.append(f"{where}.url must start with http:// or https://")
            headers = srv.get("headers")
            if headers is not None:
                if not isinstance(headers, dict):
                    errors.append(f"{where}.headers must be an object of name->string")
                else:
                    for k, v in headers.items():
                        if not isinstance(v, str):
                            errors.append(
                                f"{where}.headers[{k!r}] must be a string "
                                "(use 'ask:VAR' for secrets)"
                            )
        else:  # stdio-npm
            pkg = srv.get("package")
            if not isinstance(pkg, dict) or not pkg.get("name"):
                errors.append(
                    f"{where} (stdio-npm) requires a 'package' object with a 'name'"
                )
            # optional bin selector: which entry of the package's "bin" map to
            # expose (e.g. nocodb-mcp vs nocodb-mcp-http). Defaults to the bin
            # key matching the package name, else the first bin entry.
            if "bin" in srv and not isinstance(srv["bin"], str):
                errors.append(f"{where}.bin must be a string (a key of package bin)")
            env = srv.get("env")
            if env is not None:
                if not isinstance(env, dict):
                    errors.append(f"{where}.env must be an object of name->string")
                else:
                    for k, v in env.items():
                        if not isinstance(v, str):
                            errors.append(
                                f"{where}.env[{k!r}] must be a string "
                                "(use 'ask:VAR' for secrets)"
                            )

        timeout = srv.get("timeoutMs")
        if timeout is not None and not isinstance(timeout, int):
            errors.append(f"{where}.timeoutMs must be an integer")

    return errors
