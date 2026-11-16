"""Create and restore a private, verified deployment snapshot before API startup."""
import argparse
import base64
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import secrets
import sqlite3
import tarfile
import tempfile


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def export_data(source, output, credentials_path=None):
    source = source.resolve()
    if output.exists():
        raise ValueError("The output archive already exists.")
    if credentials_path and credentials_path.exists():
        raise ValueError("The credentials file already exists.")
    with tempfile.TemporaryDirectory(prefix="salcobrand-export-") as folder:
        snapshot = Path(folder)
        with closing(sqlite3.connect(source.joinpath("data.db").as_uri() + "?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(snapshot / "data.db")) as destination, destination:
                original.backup(destination)
                credentials = {}
                if credentials_path:
                    for (username,) in destination.execute("SELECT username FROM users").fetchall():
                        password, salt = secrets.token_urlsafe(24), secrets.token_hex(16)
                        hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
                        destination.execute("UPDATE users SET password_hash=?, salt=?, auth_version=auth_version+1 WHERE username=?",
                                            (base64.b64encode(hashed).decode(), salt, username))
                        credentials[username] = password
        uploads = source / "uploads"
        if uploads.exists():
            shutil.copytree(uploads, snapshot / "uploads")
        files = sorted(path for path in snapshot.rglob("*") if path.is_file())
        manifest = {path.relative_to(snapshot).as_posix(): digest(path) for path in files}
        (snapshot / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        if credentials_path:
            credentials_path.parent.mkdir(parents=True, exist_ok=True)
            credentials_path.write_text(json.dumps(credentials, indent=2), encoding="utf-8")
        with tarfile.open(output, "w:gz") as archive:
            for path in sorted(snapshot.rglob("*")):
                archive.add(path, arcname=path.relative_to(snapshot).as_posix(), recursive=False)
    return {"archive": str(output), "sha256": digest(output), "files": len(manifest)}


def restore_data(archive_path, destination):
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("Restore requires an empty data directory before API startup.")
    # Stage and verify every member before touching the mounted data directory.
    with tempfile.TemporaryDirectory(prefix="salcobrand-restore-", dir=destination.parent) as folder:
        staging = Path(folder)
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(staging, filter="data")
        manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
        actual = {path.relative_to(staging).as_posix(): digest(path)
                  for path in staging.rglob("*") if path.is_file() and path != staging / "manifest.json"}
        if actual != manifest or "data.db" not in manifest:
            raise ValueError("The archive does not match its manifest.")
        with closing(sqlite3.connect((staging / "data.db").as_uri() + "?mode=ro", uri=True)) as database:
            if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("The source SQLite snapshot failed its integrity check.")
        # A single rename publishes the verified snapshot. The destination is empty.
        destination.rmdir()
        staging.rename(destination)
    return {"restored_files": len(manifest), "destination": str(destination)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--source", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--credentials-file", type=Path,
                        help="Generate new account passwords in the exported copy and write them to this private file.")
    restore = commands.add_parser("restore")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    result = export_data(args.source, args.output, args.credentials_file) if args.command == "export" else restore_data(args.archive, args.destination)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
