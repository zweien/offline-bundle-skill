"""Manifest schema validation for offline-bundle-skill.

validate_manifest(manifest: dict) -> list[str]
    Returns a list of human-readable error strings. Empty list = valid.

This module is PURE: no I/O, no exceptions for validation failures.
pack.py imports it to validate manifests before acting on them.
"""
import re

# skill_name: lowercase, kebab-case-ish (letters/digits/dash/underscore)
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_VALID_TOOL_KINDS = {"auto", "manual"}
_REQUIRED_TARGET = ("python", "os", "arch", "node")


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
                errors.append(f"deps.tools[{i}] (manual) requires 'note'")

    return errors
