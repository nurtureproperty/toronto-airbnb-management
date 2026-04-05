"""
Google Drive Helper - Read/Write any file type in Google Drive.

Supports Shared Drives (starts with 0A) and My Drive.

Usage:
  python scripts/gdrive.py ls [folder_id]              # List files in folder
  python scripts/gdrive.py search "query"               # Search for files by name
  python scripts/gdrive.py read <file_id>               # Read file content (text/docs/sheets)
  python scripts/gdrive.py download <file_id> [path]    # Download file to local path
  python scripts/gdrive.py upload <local_path> [folder_id] [name]  # Upload file
  python scripts/gdrive.py update <file_id> <local_path>  # Update existing file
  python scripts/gdrive.py mkdir <name> [parent_id]     # Create folder
  python scripts/gdrive.py info <file_id>               # Get file metadata

Auth: Uses GSHEETS_REFRESH_TOKEN from .env (same token as Sheets MCP, has Drive scope).
"""

import os
import sys
import json
import mimetypes
import argparse
from dotenv import load_dotenv
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID")
CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("GSHEETS_REFRESH_TOKEN")

DRIVE_API = "https://www.googleapis.com/drive/v3"

EXPORT_MIMES = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}


def get_access_token():
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
        "grant_type": "refresh_token",
    })
    data = resp.json()
    if "access_token" not in data:
        print(f"ERROR: {data}")
        sys.exit(1)
    return data["access_token"]


def headers():
    return {"Authorization": f"Bearer {get_access_token()}"}


def list_files(folder_id=None):
    q = f"'{folder_id}' in parents and trashed = false" if folder_id else "trashed = false"
    params = {
        "q": q,
        "pageSize": 100,
        "fields": "files(id,name,mimeType,size,modifiedTime,parents)",
        "orderBy": "modifiedTime desc",
        "includeItemsFromAllDrives": "true",
        "supportsAllDrives": "true",
        "corpora": "allDrives",
    }
    all_files = []
    while True:
        resp = requests.get(f"{DRIVE_API}/files", headers=headers(), params=params)
        if resp.status_code != 200:
            print(f"Error {resp.status_code}: {resp.text[:200]}")
            return []
        data = resp.json()
        all_files.extend(data.get("files", []))
        token = data.get("nextPageToken")
        if not token:
            break
        params["pageToken"] = token

    for f in all_files:
        size = f.get("size", "")
        size_str = f" ({int(size):,} bytes)" if size else ""
        icon = "📁" if "folder" in f.get("mimeType", "") else "📄"
        print(f"  {icon} {f['name']}{size_str}")
        print(f"     ID: {f['id']}")
        print(f"     Type: {f['mimeType']}")
        print(f"     Modified: {f.get('modifiedTime', 'unknown')}")
        print()

    print(f"Total: {len(all_files)} files")
    return all_files


def search_files(query):
    params = {
        "q": f"name contains '{query}' and trashed = false",
        "pageSize": 20,
        "fields": "files(id,name,mimeType,size,modifiedTime)",
        "orderBy": "modifiedTime desc",
        "includeItemsFromAllDrives": "true",
        "supportsAllDrives": "true",
        "corpora": "allDrives",
    }
    resp = requests.get(f"{DRIVE_API}/files", headers=headers(), params=params)
    if resp.status_code != 200:
        print(f"Error {resp.status_code}: {resp.text[:200]}")
        return []
    files = resp.json().get("files", [])
    for f in files:
        print(f"  {f['name']}")
        print(f"     ID: {f['id']}  Type: {f['mimeType']}")
    print(f"\n{len(files)} results")
    return files


def read_file(file_id):
    resp = requests.get(f"{DRIVE_API}/files/{file_id}",
                       headers=headers(),
                       params={"fields": "id,name,mimeType,size", "supportsAllDrives": "true"})
    if resp.status_code != 200:
        print(f"Error: {resp.text[:200]}")
        return None
    meta = resp.json()
    mime = meta["mimeType"]
    print(f"File: {meta['name']} ({mime})")
    print("=" * 60)

    if mime in EXPORT_MIMES:
        export_mime, _ = EXPORT_MIMES[mime]
        resp = requests.get(f"{DRIVE_API}/files/{file_id}/export",
                           headers=headers(),
                           params={"mimeType": export_mime})
    else:
        resp = requests.get(f"{DRIVE_API}/files/{file_id}",
                           headers=headers(),
                           params={"alt": "media", "supportsAllDrives": "true"})

    if resp.status_code != 200:
        print(f"Error: {resp.status_code} {resp.text[:200]}")
        return None

    try:
        text = resp.content.decode("utf-8")
        print(text)
        return text
    except UnicodeDecodeError:
        print(f"[Binary file, {len(resp.content):,} bytes. Use 'download' instead.]")
        return resp.content


def download_file(file_id, local_path=None):
    resp = requests.get(f"{DRIVE_API}/files/{file_id}",
                       headers=headers(),
                       params={"fields": "id,name,mimeType", "supportsAllDrives": "true"})
    meta = resp.json()
    mime = meta["mimeType"]

    if not local_path:
        local_path = meta["name"]

    if mime in EXPORT_MIMES:
        export_mime, ext = EXPORT_MIMES[mime]
        if not local_path.endswith(ext):
            local_path += ext
        resp = requests.get(f"{DRIVE_API}/files/{file_id}/export",
                           headers=headers(),
                           params={"mimeType": export_mime})
    else:
        resp = requests.get(f"{DRIVE_API}/files/{file_id}",
                           headers=headers(),
                           params={"alt": "media", "supportsAllDrives": "true"})

    if resp.status_code != 200:
        print(f"Error: {resp.status_code}")
        return

    with open(local_path, "wb") as f:
        f.write(resp.content)
    print(f"Downloaded: {local_path} ({len(resp.content):,} bytes)")


def upload_file(local_path, folder_id=None, name=None):
    if not os.path.exists(local_path):
        print(f"File not found: {local_path}")
        return None

    if not name:
        name = os.path.basename(local_path)
    mime_type = mimetypes.guess_type(local_path)[0] or "application/octet-stream"

    metadata = {"name": name}
    if folder_id:
        metadata["parents"] = [folder_id]

    resp = requests.post(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&supportsAllDrives=true",
        headers={"Authorization": f"Bearer {get_access_token()}"},
        files={
            "metadata": ("metadata", json.dumps(metadata), "application/json"),
            "file": (name, open(local_path, "rb"), mime_type),
        },
    )

    if resp.status_code == 200:
        data = resp.json()
        print(f"Uploaded: {name}")
        print(f"  ID: {data['id']}")
        print(f"  Link: https://drive.google.com/file/d/{data['id']}/view")
        return data
    else:
        print(f"Upload error {resp.status_code}: {resp.text[:200]}")
        return None


def update_file(file_id, local_path):
    if not os.path.exists(local_path):
        print(f"File not found: {local_path}")
        return None
    mime_type = mimetypes.guess_type(local_path)[0] or "application/octet-stream"
    resp = requests.patch(
        f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media&supportsAllDrives=true",
        headers={
            "Authorization": f"Bearer {get_access_token()}",
            "Content-Type": mime_type,
        },
        data=open(local_path, "rb").read(),
    )
    if resp.status_code == 200:
        print(f"Updated: {resp.json()['name']}")
        return resp.json()
    else:
        print(f"Update error {resp.status_code}: {resp.text[:200]}")
        return None


def create_folder(name, parent_id=None):
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]
    resp = requests.post(
        f"{DRIVE_API}/files?supportsAllDrives=true",
        headers={**headers(), "Content-Type": "application/json"},
        json=metadata,
    )
    if resp.status_code == 200:
        data = resp.json()
        print(f"Created folder: {name}")
        print(f"  ID: {data['id']}")
        return data
    else:
        print(f"Error {resp.status_code}: {resp.text[:200]}")
        return None


def file_info(file_id):
    resp = requests.get(
        f"{DRIVE_API}/files/{file_id}",
        headers=headers(),
        params={"fields": "*", "supportsAllDrives": "true"},
    )
    if resp.status_code != 200:
        print(f"Error: {resp.text[:200]}")
        return
    meta = resp.json()
    print(f"Name: {meta.get('name')}")
    print(f"ID: {meta.get('id')}")
    print(f"Type: {meta.get('mimeType')}")
    print(f"Size: {meta.get('size', 'N/A')} bytes")
    print(f"Created: {meta.get('createdTime')}")
    print(f"Modified: {meta.get('modifiedTime')}")
    print(f"Link: {meta.get('webViewLink', 'N/A')}")
    print(f"Parents: {meta.get('parents', [])}")
    return meta


def main():
    parser = argparse.ArgumentParser(description="Google Drive helper")
    parser.add_argument("command", choices=["ls", "search", "read", "download", "upload", "update", "mkdir", "info"])
    parser.add_argument("args", nargs="*")
    args = parser.parse_args()

    if args.command == "ls":
        list_files(args.args[0] if args.args else None)
    elif args.command == "search":
        if not args.args:
            print("Usage: gdrive.py search <query>")
            return
        search_files(args.args[0])
    elif args.command == "read":
        if not args.args:
            print("Usage: gdrive.py read <file_id>")
            return
        read_file(args.args[0])
    elif args.command == "download":
        if not args.args:
            print("Usage: gdrive.py download <file_id> [local_path]")
            return
        local_path = args.args[1] if len(args.args) > 1 else None
        download_file(args.args[0], local_path)
    elif args.command == "upload":
        if not args.args:
            print("Usage: gdrive.py upload <local_path> [folder_id] [name]")
            return
        folder_id = args.args[1] if len(args.args) > 1 else None
        name = args.args[2] if len(args.args) > 2 else None
        upload_file(args.args[0], folder_id, name)
    elif args.command == "update":
        if len(args.args) < 2:
            print("Usage: gdrive.py update <file_id> <local_path>")
            return
        update_file(args.args[0], args.args[1])
    elif args.command == "mkdir":
        if not args.args:
            print("Usage: gdrive.py mkdir <name> [parent_id]")
            return
        parent_id = args.args[1] if len(args.args) > 1 else None
        create_folder(args.args[0], parent_id)
    elif args.command == "info":
        if not args.args:
            print("Usage: gdrive.py info <file_id>")
            return
        file_info(args.args[0])


if __name__ == "__main__":
    main()
