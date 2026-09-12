import os
from pathlib import Path
import pytest

from breakheal.java_context import extract_java_context, scan_directory_for_java_methods
from breakheal.java_runner import find_maven_root, get_maven_executable, run_maven_test


def test_java_context_extraction():
    java_file = Path("demo_java/src/main/java/com/breakheal/demo/DiscountCalculator.java").resolve()
    assert java_file.exists(), "Java fixture DiscountCalculator.java must exist"

    ctx = extract_java_context(java_file)
    assert ctx.package_name == "com.breakheal.demo"
    assert ctx.class_name == "DiscountCalculator"
    assert ctx.method_name == "calculateDiscountedUnitPrice"
    assert ctx.start_line > 0
    assert ctx.end_line >= ctx.start_line
    assert "calculateDiscountedUnitPrice" in ctx.method_code
    assert ctx.maven_root is not None
    assert Path(ctx.maven_root).is_dir()


def test_java_scan_directory():
    demo_dir = Path("demo_java").resolve()
    methods = scan_directory_for_java_methods(demo_dir)
    assert len(methods) >= 1
    method_names = [m.method_name for m in methods]
    assert "calculateDiscountedUnitPrice" in method_names


def test_maven_root_discovery():
    java_file = Path("demo_java/src/main/java/com/breakheal/demo/DiscountCalculator.java").resolve()
    root = find_maven_root(java_file)
    assert root is not None
    assert (root / "pom.xml").exists()


def test_resolve_mvn_cmd():
    mvn_cmd = get_maven_executable()
    # If maven is installed in this environment, it should resolve
    assert mvn_cmd is not None
    assert "mvn" in mvn_cmd.lower()
