from alt_asset_explorer.git_checks import binary_paths


def test_binary_paths_recognizes_only_git_binary_numstat_rows():
    numstat = "12\t3\tsrc/code.py\n-\t-\tdata/cache/archive.parquet\n0\t1\tdocs/note.md\n"
    assert binary_paths(numstat) == ["data/cache/archive.parquet"]
