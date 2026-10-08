import os

from brewreview.details import DetailsLoader, disk_usage, last_used


def test_disk_usage(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "file").write_bytes(b"x" * 10_000)
    assert disk_usage(tmp_path) >= 10_000
    assert disk_usage(tmp_path / "missing") == 0


def test_last_used_picks_newest_executable(tmp_path):
    (tmp_path / "bin").mkdir()
    for name, atime in (("old", 1_000), ("new", 2_000)):
        path = tmp_path / "bin" / name
        path.touch()
        os.utime(path, (atime, atime))
    assert last_used(tmp_path).timestamp() == 2_000


def test_last_used_without_executables(tmp_path):
    assert last_used(tmp_path) is None


def test_loader_computes_in_background(inventory):
    keg = inventory.cellar / "app" / "1.0"
    keg.mkdir(parents=True)
    (keg / "data").write_bytes(b"x" * 5_000)
    loader = DetailsLoader(inventory, inventory.candidates())
    try:
        assert loader.size("app") >= 5_000
        assert loader.size("lib1") == 0  # not a candidate, but still sized
        assert loader.last_used("app") is None
    finally:
        loader.close()
