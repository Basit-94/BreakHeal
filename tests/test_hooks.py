import tempfile
from pathlib import Path
from breakheal.hooks import ASTCache, get_staged_files


def test_ast_cache_save_and_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir)
        cache = ASTCache(cache_dir=cache_dir)

        code_1 = "def foo():\n    return 42\n"
        cache.update("foo_key", code_1, "CLEAN")

        assert cache.is_cached("foo_key", code_1) is True

        # Modified code should not match
        code_2 = "def foo():\n    return 43\n"
        assert cache.is_cached("foo_key", code_2) is False

        # Reload cache from disk
        reloaded_cache = ASTCache(cache_dir=cache_dir)
        assert reloaded_cache.is_cached("foo_key", code_1) is True


def test_get_staged_files_smoke():
    files = get_staged_files(extensions=[".py"])
    assert isinstance(files, list)
