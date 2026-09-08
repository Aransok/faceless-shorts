"""One-time interactive OAuth setup for YouTube uploads (Phase 8 prep).

Opens a browser for you to log in and click Allow, then saves a refresh
token so the rest of the pipeline can upload videos and read stats without
prompting again. Run this once locally:

    python scripts/get_youtube_token.py

Needs credentials/client_secret.json (downloaded from Google Cloud
Console: APIs & Services > Credentials > your OAuth client > Download
JSON). That file and the token this script produces are both gitignored
via credentials/ — never commit either.
"""

from __future__ import annotations

import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLIENT_SECRET_PATH = PROJECT_ROOT / "credentials" / "client_secret.json"
TOKEN_OUTPUT_PATH = PROJECT_ROOT / "credentials" / "youtube_token.json"

# Matches what the branding privacy policy declares: upload videos, read
# view/like/comment counts for them, and manage their own metadata (title/
# description/tags) after upload. youtube.upload + youtube.readonly alone
# aren't enough for videos.update/delete — force-ssl is the scope that
# actually covers managing your own already-uploaded content.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def main() -> None:
    if not CLIENT_SECRET_PATH.exists():
        raise SystemExit(
            f"client secret not found at {CLIENT_SECRET_PATH} — download it from "
            "Google Cloud Console (APIs & Services > Credentials) and place it there"
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    print("Opening your browser — log in and click Allow to continue...")
    credentials = flow.run_local_server(port=0)

    token_data = {
        "refresh_token": credentials.refresh_token,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "token_uri": credentials.token_uri,
        "scopes": credentials.scopes,
    }
    TOKEN_OUTPUT_PATH.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
    print(f"\nSaved refresh token to {TOKEN_OUTPUT_PATH}")
    print("Keep this file secret — it's already gitignored, never commit it.")


if __name__ == "__main__":
    main()
