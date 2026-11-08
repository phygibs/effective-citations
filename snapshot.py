#!/usr/bin/env python3
"""Download the citation snapshot, with an optional deployed-version check."""

import argparse
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile

SNAPSHOT_URL = "https://networks.skewed.de/net/inspire_hep/files/citations.csv.zip"


def deployed_etag(site_url):
    """Read the version of the archive that produced the live scores."""
    url = f"{site_url.rstrip('/')}/snapshot.json"
    try:
        with urlopen(url, timeout=15) as response:
            metadata = json.load(response)
    except (OSError, ValueError):
        # With no confirmed live version, rebuild rather than skip an update.
        return None
    if isinstance(metadata, dict) and metadata.get("source") == SNAPSHOT_URL:
        etag = metadata.get("etag")
        if isinstance(etag, str) and etag:
            return etag
    return None


def download_snapshot(path, etag=None):
    """Return metadata for a downloaded archive or None if it is unchanged."""
    headers = {"If-None-Match": etag} if etag else {}
    request = Request(SNAPSHOT_URL, headers=headers)
    try:
        response = urlopen(request, timeout=90)
    except HTTPError as error:
        if error.code == 304 and etag:
            error.close()
            return None
        raise

    with response:
        current_etag = response.headers.get("ETag")
        if etag and current_etag == etag:
            return None
        modified = response.headers.get("Last-Modified")
        print(f"Downloading the INSPIRE snapshot to {path}", flush=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
            partial = Path(file.name)
        try:
            with partial.open("wb") as file:
                shutil.copyfileobj(response, file)
            with ZipFile(partial) as archive:
                if not {"nodes.csv", "edges.csv"}.issubset(archive.namelist()):
                    raise ValueError("The download is missing the citation graph files")
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)

    return {
        "source": SNAPSHOT_URL,
        "etag": current_etag,
        "archive_last_modified": parsedate_to_datetime(modified).isoformat() if modified else None,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", help="Pages URL to check before downloading")
    parser.add_argument("--snapshot", type=Path, default=Path("citations.csv.zip"))
    parser.add_argument("--metadata", type=Path, default=Path("snapshot.json"))
    parser.add_argument("--repository", required=True, help="GitHub owner/repository")
    args = parser.parse_args()

    etag = deployed_etag(args.site) if args.site else None
    metadata = download_snapshot(args.snapshot, etag)
    if metadata:
        metadata["repository"] = args.repository
        args.metadata.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        print("Snapshot ready for scoring")
    else:
        print("The live scores already use this snapshot")

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as file:
            file.write(f"build={'true' if metadata else 'false'}\n")


if __name__ == "__main__":
    main()
