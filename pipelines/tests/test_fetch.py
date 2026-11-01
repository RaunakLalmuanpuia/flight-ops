import zipfile

from flightops.sources import fetch


def test_download_writes_file_and_skips_when_present(tmp_path):
    src = tmp_path / "src.csv"
    src.write_text("a\n")
    dest = tmp_path / "out" / "dest.csv"
    assert fetch.download(src.as_uri(), dest) is True
    assert dest.read_text() == "a\n"
    src.write_text("changed\n")
    assert fetch.download(src.as_uri(), dest) is False
    assert dest.read_text() == "a\n"
    assert not dest.with_name("dest.csv.part").exists()


def test_extract_csv_takes_only_csv_members(tmp_path):
    archive = tmp_path / "x.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("data.csv", "a\n")
        z.writestr("readme.html", "<p>")
    fetch.extract_csv(archive)
    assert (tmp_path / "data.csv").read_text() == "a\n"
    assert not (tmp_path / "readme.html").exists()
