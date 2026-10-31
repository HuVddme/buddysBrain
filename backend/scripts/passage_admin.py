"""Administer a deployed API without local ML dependencies or database credentials."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import requests
from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["setup", "status", "reprocess"])
    parser.add_argument("--api-base", required=True, help="Backend base URL, including /api on Vercel")
    parser.add_argument("--resource-id")
    parser.add_argument("--file", type=Path, help="The original PDF, DOCX or TXT for an existing document")
    args = parser.parse_args()
    base = args.api_base.rstrip("/")
    url = urlsplit(base)
    if (url.username or url.password or url.query or url.fragment or not url.hostname
            or not (url.scheme == "https" or
                    (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}))):
        parser.error("Use an HTTPS API base URL, or HTTP on localhost. Do not put credentials in the URL.")
    if args.action == "reprocess":
        if not args.resource_id or not re.fullmatch(r"[a-fA-F0-9]{24}", args.resource_id):
            parser.error("Reprocessing needs --resource-id with the existing document's 24-character ID.")
        if not args.file or not args.file.is_file():
            parser.error("Reprocessing needs --file pointing to the original document.")
        if args.file.suffix.lower() not in {".pdf", ".txt", ".docx"}:
            parser.error("Select a PDF, DOCX or TXT file.")
        if args.file.stat().st_size > 4_000_000:
            parser.error("Use a document under 4 MB for the deployed Vercel API.")
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    token = os.getenv("RESOURCE_ADMIN_TOKEN") or getpass.getpass("Resource admin token (hidden): ")
    if not token.strip():
        parser.error("An administrator token is required.")
    headers = {"Authorization": f"Bearer {token.strip()}"}
    try:
        # Do not follow redirects with an administrative credential.
        with requests.Session() as session:
            if args.action == "reprocess":
                with args.file.open("rb") as stream:
                    response = session.post(f"{base}/resources/{args.resource_id}/passages",
                                            files={"file": (args.file.name, stream)}, headers=headers,
                                            timeout=(10, 120), allow_redirects=False)
            else:
                response = session.request("POST" if args.action == "setup" else "GET",
                                           f"{base}/admin/passage-index", headers=headers,
                                           timeout=(10, 30), allow_redirects=False)
        try:
            payload = response.json()
        except ValueError:
            raise SystemExit(f"API returned HTTP {response.status_code} without JSON. Check the API URL and deployment access.")
        print(json.dumps(payload, indent=2))
        if not response.ok or response.is_redirect:
            raise SystemExit(1)
    except requests.RequestException as exc:
        raise SystemExit(f"API request failed ({type(exc).__name__}). Check connectivity; a timed-out update may have completed. Repeating the same file is safe.") from None


if __name__ == "__main__":
    main()
