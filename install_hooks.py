#!/usr/bin/env python3
"""
Installation script for LLM code review git hooks.
Automatically installs pre-commit and pre-push hooks.
"""

import os
import shutil
import sys
from pathlib import Path


def install_hooks():
    """Install git hooks to .git/hooks directory."""

    # Check if we're in a git repository
    git_dir = Path(".git")
    if not git_dir.exists():
        print("❌ Error: Not in a git repository.")
        print("   Please run this script from the root of a git repository.")
        return False

    # Check if hooks directory exists
    hooks_source = Path("hooks")
    if not hooks_source.exists():
        print("❌ Error: hooks directory not found.")
        print("   Please ensure hooks/ directory exists with hook scripts.")
        return False

    # Target hooks directory
    hooks_target = git_dir / "hooks"

    # Install hooks
    hooks_to_install = ["pre-commit", "pre-push"]
    installed_count = 0

    for hook_name in hooks_to_install:
        source_file = hooks_source / hook_name
        target_file = hooks_target / hook_name

        if not source_file.exists():
            print(f"⚠️  Warning: {hook_name} hook not found in hooks/ directory")
            continue

        try:
            # Remove existing hook
            if target_file.exists():
                target_file.unlink()
                print(f"🗑️  Removed existing {hook_name} hook")

            # Copy new hook
            shutil.copy(source_file, target_file)

            # Make executable
            os.chmod(target_file, 0o755)

            print(f"✅ Installed {hook_name} hook")
            installed_count += 1

        except Exception as e:
            print(f"❌ Error installing {hook_name} hook: {e}")
            return False

    if installed_count > 0:
        print(f"\n🎉 Successfully installed {installed_count} git hooks!")
        print("\n📋 Installed hooks:")
        print("   • pre-commit  - Reviews staged changes before commit")
        print("   • pre-push   - Comprehensive review before push")
        print("\n💡 Usage:")
        print("   • Git hooks run automatically")
        print("   • Manual review: python review.py --mode staged")
        print("   • Test connection: python review.py --test-connection")
        print("\n⚠️  To uninstall: delete files from .git/hooks/")
    else:
        print("\n⚠️  No hooks were installed.")
        return False

    return True


def check_existing_hooks():
    """Check for existing hooks and warn user."""
    hooks_target = Path(".git/hooks")
    hooks_to_check = ["pre-commit", "pre-push"]

    existing_hooks = []
    for hook_name in hooks_to_check:
        hook_file = hooks_target / hook_name
        if hook_file.exists():
            existing_hooks.append(hook_name)

    if existing_hooks:
        print(f"⚠️  Existing hooks found: {', '.join(existing_hooks)}")
        response = input("Replace existing hooks? (y/N): ").strip().lower()
        if response not in ["y", "yes"]:
            print("Installation cancelled.")
            return False

    return True


def main():
    """Main installation function."""
    print("🔧 Installing LLM Code Review Git Hooks")
    print("=" * 40)

    # Check existing hooks
    if not check_existing_hooks():
        return False

    # Install hooks
    if install_hooks():
        print("\n✅ Installation completed successfully!")
        return True
    else:
        print("\n❌ Installation failed!")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
