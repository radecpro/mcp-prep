"""Download and verify the pinned macOS Ollama runtime into .local/."""

import hashlib
import tarfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v0.40.3"
SHA256 = "a2d1d906a2c8febd9cb18f5c183854d0a6db5dc522940d68b0c0ed048e8dfdea"
URL = f"https://github.com/ollama/ollama/releases/download/{VERSION}/ollama-darwin.tgz"


def main():
    import sys
    if sys.platform != "darwin":
        raise SystemExit("This runtime setup is for macOS only")
    archive = ROOT / ".local" / "ollama-darwin.tgz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        partial = archive.with_suffix(".part")
        try:
            with urlopen(URL, timeout=180) as response, partial.open("wb") as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
            partial.replace(archive)
        finally:
            partial.unlink(missing_ok=True)
    with archive.open("rb") as archive_file:
        digest = hashlib.file_digest(archive_file, "sha256").hexdigest()
    if digest != SHA256:
        raise SystemExit("Ollama checksum mismatch; remove the archive and retry")
    with tarfile.open(archive) as bundle:
        bundle.extractall(ROOT / ".local" / "ollama", filter="data")
    print(f"Installed Ollama {VERSION} in {ROOT / '.local' / 'ollama'}")


if __name__ == "__main__":
    main()
