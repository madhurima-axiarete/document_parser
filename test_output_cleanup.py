#!/usr/bin/env python3
"""Test that output directory cleanup works correctly.

Verifies that old artifacts are removed before new extraction begins.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
from production_pipeline.pipeline import _cleanup_output_dir


def test_cleanup_removes_old_files():
    """Test that cleanup removes all old artifacts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)

        # Create test artifacts that would exist from a previous run
        old_files = [
            output_dir / "index.md",
            output_dir / "output.md",
            output_dir / "raw_blocks.json",
            output_dir / "some_other.json",
        ]

        for f in old_files:
            f.write_text("old content")

        # Create old directories
        old_sections = output_dir / "sections"
        old_sections.mkdir()
        (old_sections / "001_test.md").write_text("old section")

        old_profiles = output_dir / "profiles"
        old_profiles.mkdir()
        (old_profiles / "doc_profile.json").write_text("old profile")

        old_boundaries = output_dir / "boundaries"
        old_boundaries.mkdir()
        (old_boundaries / "boundary_risks.json").write_text("old boundaries")

        print(f"Before cleanup: {len(list(output_dir.glob('**/*')))} files/dirs")
        before = set(f.name for f in output_dir.glob("**/*") if f.is_file())

        # Run cleanup
        _cleanup_output_dir(output_dir)

        print(f"After cleanup: {len(list(output_dir.glob('**/*')))} files/dirs")
        after = set(f.name for f in output_dir.glob("**/*") if f.is_file())

        # Verify all old artifacts are gone
        removed = before - after
        print(f"Removed: {removed}")

        expected_removed = {
            "index.md",
            "output.md",
            "raw_blocks.json",
            "some_other.json",
            "001_test.md",
            "doc_profile.json",
            "boundary_risks.json",
        }

        if removed == expected_removed:
            print("✓ All old artifacts removed")
            return True
        else:
            print(f"ERROR: Expected to remove {expected_removed}, but removed {removed}")
            return False


def test_cleanup_handles_nonexistent_dir():
    """Test that cleanup doesn't error on nonexistent directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        nonexistent = Path(tmpdir) / "does_not_exist"

        try:
            _cleanup_output_dir(nonexistent)
            print("✓ Cleanup handled nonexistent directory")
            return True
        except Exception as e:
            print(f"ERROR: {e}")
            return False


def test_cleanup_keeps_untracked_files():
    """Test that cleanup doesn't remove files outside the known patterns."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)

        # Create known files (should be removed)
        (output_dir / "index.md").write_text("old")
        (output_dir / "raw_blocks.json").write_text("old")

        # Create unknown file (should be preserved)
        (output_dir / "custom_report.txt").write_text("keep me")

        _cleanup_output_dir(output_dir)

        if (output_dir / "custom_report.txt").exists():
            print("✓ Custom files preserved during cleanup")
            return True
        else:
            print("ERROR: Custom files were removed")
            return False


def main():
    print("Testing output directory cleanup...\n")

    tests = [
        ("Remove old artifacts", test_cleanup_removes_old_files),
        ("Handle nonexistent dir", test_cleanup_handles_nonexistent_dir),
        ("Preserve custom files", test_cleanup_keeps_untracked_files),
    ]

    results = []
    for name, test_fn in tests:
        print(f"\n{name}:")
        try:
            result = test_fn()
            results.append(result)
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    passed = sum(results)
    total = len(results)

    print(f"\n\nResults: {passed}/{total} tests passed")

    if passed == total:
        print("✓ All cleanup tests passed!")
        return 0
    else:
        print("✗ Some cleanup tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
