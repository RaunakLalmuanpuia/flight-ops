import shutil
import urllib.request
import zipfile
from pathlib import Path


def download(url: str, dest: Path) -> bool:
    if dest.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")  # never leave a partial file under the real name
    with urllib.request.urlopen(url) as response, part.open("wb") as out:
        shutil.copyfileobj(response, out)
    part.rename(dest)
    return True


def extract_csv(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if name.lower().endswith(".csv"):
                z.extract(name, zip_path.parent)
