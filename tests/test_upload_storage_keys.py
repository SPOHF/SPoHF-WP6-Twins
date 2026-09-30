"""`stored_key` normalises a manual_uploads.file_path value to an object key.

Pure logic, so it belongs in the fast suite. The failure it prevents is silent:
rows written before uploads moved to object storage (issue 061 phase 3) hold an
absolute filesystem path, and `prune` reads that column back. Without
normalisation those rows would ask the store to delete a key that cannot exist,
leave the migrated object orphaned, and still mark the row pruned.
"""

from wp6_data.shared.upload_storage import stored_key


def test_a_key_passes_through():
    assert stored_key("sijia/abc123.xlsx") == "sijia/abc123.xlsx"


def test_a_legacy_red_path_becomes_a_key():
    assert stored_key("/data/manual-uploads/sijia/abc123.xlsx") == "sijia/abc123.xlsx"


def test_a_legacy_blue_path_becomes_a_key():
    assert (
        stored_key("/data/blue-manual-uploads/insect_counts/def456.csv")
        == "insect_counts/def456.csv"
    )


def test_a_relative_dev_path_becomes_a_key():
    """A dev machine wrote uploads-red/<source>/<hash>.xlsx."""
    assert stored_key("uploads-red/sijia/abc.xlsx") == "sijia/abc.xlsx"


def test_a_windows_style_path_becomes_a_key():
    assert stored_key(r"C:\data\uploads\sijia\abc.xlsx") == "sijia/abc.xlsx"


def test_a_bare_name_is_left_alone():
    """Nothing sensible to strip; passing it through beats mangling it."""
    assert stored_key("abc123.xlsx") == "abc123.xlsx"


def test_trailing_and_doubled_separators_are_ignored():
    assert stored_key("/data//manual-uploads//sijia//abc.xlsx") == "sijia/abc.xlsx"
