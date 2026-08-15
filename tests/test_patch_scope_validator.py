"""
Tests for patch-scope-validator Skill
"""

import pytest

from agentloom.skills.patch_scope_validator import (
    matches_allowed_pattern,
    parse_unified_diff_paths,
    validate_patch_scope,
)


def test_parse_unified_diff_paths_simple() -> None:
    """Test parsing paths from a simple unified diff."""
    patch = """--- a/src/module.py
+++ b/src/module.py
@@ -1 +1 @@
-old line
+new line
"""
    paths = parse_unified_diff_paths(patch)
    assert paths == {"src/module.py"}


def test_parse_unified_diff_paths_multiple_files() -> None:
    """Test parsing paths from a multi-file diff."""
    patch = """--- a/src/file1.py
+++ b/src/file1.py
@@ -1,1 +1,1 @@
-old
+new
--- a/src/file2.py
+++ b/src/file2.py
@@ -1,1 +1,1 @@
-old
+new
"""
    paths = parse_unified_diff_paths(patch)
    assert paths == {"src/file1.py", "src/file2.py"}


def test_parse_unified_diff_paths_new_file() -> None:
    """Test parsing a new file creation."""
    patch = """--- /dev/null
+++ b/src/newfile.py
@@ -0,0 +1,1 @@
+new content
"""
    paths = parse_unified_diff_paths(patch)
    assert "src/newfile.py" in paths


def test_parse_unified_diff_paths_rejects_unpaired_file_headers() -> None:
    patch = """--- a/src/allowed.py
--- a/src/forbidden.py
@@ -1 +1 @@
-old
+new
"""

    with pytest.raises(ValueError, match="file header"):
        parse_unified_diff_paths(patch)


def test_parse_unified_diff_paths_does_not_treat_hunk_content_as_headers() -> None:
    patch = """--- a/src/allowed.py
+++ b/src/allowed.py
@@ -1 +1 @@
--- forbidden.py
+++ forbidden.py
"""

    assert parse_unified_diff_paths(patch) == {"src/allowed.py"}


def test_matches_allowed_pattern_exact() -> None:
    """Test exact path matching."""
    assert matches_allowed_pattern("src/module.py", ["src/module.py"])
    assert not matches_allowed_pattern("src/other.py", ["src/module.py"])


def test_matches_allowed_pattern_wildcard() -> None:
    """Test wildcard pattern matching."""
    assert matches_allowed_pattern("src/module.py", ["src/*.py"])
    assert matches_allowed_pattern("src/subdir/file.py", ["src/**/*.py"])
    assert not matches_allowed_pattern("tests/test.py", ["src/**/*.py"])


def test_matches_allowed_pattern_directory() -> None:
    """Test directory pattern matching."""
    assert matches_allowed_pattern("src/module.py", ["src/**"])
    assert matches_allowed_pattern("src/subdir/file.py", ["src/**"])
    assert not matches_allowed_pattern("tests/test.py", ["src/**"])


def test_matches_allowed_pattern_rejects_oversized_pattern() -> None:
    with pytest.raises(ValueError, match="length boundary"):
        matches_allowed_pattern("src/module.py", ["src/" + "a" * 1_025])


def test_parse_unified_diff_paths_rejects_oversized_path() -> None:
    oversized_path = "src/" + "a" * 1_025
    patch = (
        f"--- a/{oversized_path}\n"
        f"+++ b/{oversized_path}\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    with pytest.raises(ValueError, match="length boundary"):
        parse_unified_diff_paths(patch)


def test_validate_patch_scope_passed() -> None:
    """Test validation passes when all paths are allowed."""
    patch = """--- a/src/severity.py
+++ b/src/severity.py
@@ -1,2 +1,2 @@
 def normalize_severity(level):
-    return level.upper()
+    return level.lower()
"""
    result = validate_patch_scope(
        patch_content=patch,
        allowed_paths=["src/severity.py"],
        patch_hash="test_hash_123"
    )

    assert result.verdict == "PASSED"
    assert result.actual_modified_paths == ["src/severity.py"]
    assert len(result.violations) == 0
    assert result.patch_hash == "test_hash_123"


def test_validate_patch_scope_failed() -> None:
    """Test validation fails when paths are not allowed."""
    patch = """--- a/src/allowed.py
+++ b/src/allowed.py
@@ -1,1 +1,1 @@
-old
+new
--- a/src/forbidden.py
+++ b/src/forbidden.py
@@ -1,1 +1,1 @@
-old
+new
"""
    result = validate_patch_scope(
        patch_content=patch,
        allowed_paths=["src/allowed.py"],
        patch_hash="test_hash_456"
    )

    assert result.verdict == "FAILED"
    assert "src/forbidden.py" in result.actual_modified_paths
    assert len(result.violations) == 1
    assert result.violations[0].file_path == "src/forbidden.py"
    assert result.violations[0].violation_type == "modified"


def test_validate_patch_scope_wildcard_allowed() -> None:
    """Test validation with wildcard patterns."""
    patch = """--- a/src/module1.py
+++ b/src/module1.py
@@ -1,1 +1,1 @@
-old
+new
--- a/src/module2.py
+++ b/src/module2.py
@@ -1,1 +1,1 @@
-old
+new
"""
    result = validate_patch_scope(
        patch_content=patch,
        allowed_paths=["src/*.py"],
        patch_hash="test_hash_789"
    )

    assert result.verdict == "PASSED"
    assert len(result.violations) == 0


def test_validate_patch_scope_mixed_violations() -> None:
    """Test validation with some allowed and some forbidden paths."""
    patch = """--- a/src/severity.py
+++ b/src/severity.py
@@ -1,1 +1,1 @@
-old
+new
--- a/config/settings.py
+++ b/config/settings.py
@@ -1,1 +1,1 @@
-old
+new
--- a/tests/test_severity.py
+++ b/tests/test_severity.py
@@ -1,1 +1,1 @@
-old
+new
"""
    result = validate_patch_scope(
        patch_content=patch,
        allowed_paths=["src/**/*.py"],
        patch_hash="test_hash_mixed"
    )

    assert result.verdict == "FAILED"
    assert len(result.violations) == 2
    violation_paths = {v.file_path for v in result.violations}
    assert "config/settings.py" in violation_paths
    assert "tests/test_severity.py" in violation_paths
    assert "src/severity.py" not in violation_paths


def test_parse_unified_diff_empty() -> None:
    """Test parsing an empty diff."""
    paths = parse_unified_diff_paths("")
    assert paths == set()


def test_matches_allowed_pattern_multiple_patterns() -> None:
    """Test matching against multiple patterns."""
    patterns = ["src/*.py", "tests/*.py"]
    assert matches_allowed_pattern("src/module.py", patterns)
    assert matches_allowed_pattern("tests/test.py", patterns)
    assert not matches_allowed_pattern("docs/readme.md", patterns)
