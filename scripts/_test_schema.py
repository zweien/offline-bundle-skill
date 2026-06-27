"""Tests for _schema.validate_manifest. Run: python _test_schema.py"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _schema import validate_manifest


def _base():
    """A minimal valid manifest to mutate in tests."""
    return {
        "skill_name": "docx",
        "skill_source": {"type": "local", "path": "C:/x/docx"},
        "target": {"python": "3.12", "os": "win", "arch": "amd64", "node": "20"},
        "deps": {"pip": [], "npm": [], "tools": []},
    }


def test_valid_minimal_manifest():
    assert validate_manifest(_base()) == []


def test_missing_skill_name():
    m = _base(); del m["skill_name"]
    assert "skill_name" in validate_manifest(m)[0]


def test_skill_name_must_be_kebab_safe():
    m = _base(); m["skill_name"] = "Bad Name!"
    errs = validate_manifest(m)
    assert any("skill_name" in e and ("lowercase" in e or "kebab" in e) for e in errs)


def test_skill_source_type_invalid():
    m = _base(); m["skill_source"]["type"] = "ftp"
    assert any("skill_source" in e for e in validate_manifest(m))


def test_local_source_needs_path():
    m = _base(); m["skill_source"] = {"type": "local"}
    assert any("path" in e for e in validate_manifest(m))


def test_git_source_needs_url():
    m = _base(); m["skill_source"] = {"type": "git", "ref": "main"}
    assert any("url" in e for e in validate_manifest(m))


def test_target_required_fields():
    m = _base(); m["target"] = {"python": "3.12"}
    errs = validate_manifest(m)
    assert any("os" in e for e in errs)
    assert any("arch" in e for e in errs)


def test_pip_entry_needs_name():
    m = _base(); m["deps"]["pip"] = [{"version": "1.0"}]
    assert any("pip" in e and "name" in e for e in validate_manifest(m))


def test_npm_entry_needs_name():
    m = _base(); m["deps"]["npm"] = [{}]
    assert any("npm" in e and "name" in e for e in validate_manifest(m))


def test_tool_kind_invalid():
    m = _base(); m["deps"]["tools"] = [{"name": "x", "kind": "weird"}]
    assert any("kind" in e for e in validate_manifest(m))


def test_auto_tool_needs_url_template():
    m = _base()
    m["deps"]["tools"] = [{"name": "x", "kind": "auto", "version": "1.0"}]
    assert any("url_template" in e for e in validate_manifest(m))


def test_auto_tool_needs_version():
    m = _base()
    m["deps"]["tools"] = [{"name": "x", "kind": "auto", "url_template": "http://x"}]
    assert any("version" in e for e in validate_manifest(m))


def test_manual_tool_needs_note():
    m = _base(); m["deps"]["tools"] = [{"name": "x", "kind": "manual"}]
    assert any("note" in e for e in validate_manifest(m))


def test_playwright_must_be_object_or_absent():
    m = _base(); m["deps"]["playwright"] = "chromium"
    assert any("playwright" in e for e in validate_manifest(m))


def test_deps_top_level_keys():
    m = _base(); m["deps"] = {"pip": []}
    # npm and tools are required even if empty
    errs = validate_manifest(m)
    assert any("npm" in e for e in errs)
    assert any("tools" in e for e in errs)


def run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t(); print(f"  PASS {t.__name__}"); passed += 1
        except AssertionError as e:
            print(f"  FAIL {t.__name__}: {e}"); raise
        except Exception as e:
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}"); raise
    print(f"\n{passed}/{len(tests)} tests passed")


if __name__ == "__main__":
    run_all()
