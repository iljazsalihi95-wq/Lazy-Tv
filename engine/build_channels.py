import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

SOURCES_FILE = DATA / "sources.json"
OUTPUT_FILE = DATA / "channels.json"


def download(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 LazyTV/2.0",
            "Accept": "*/*"
        }
    )

    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read().decode("utf-8", errors="ignore")


def attr(line, name):
    m = re.search(rf'{re.escape(name)}="([^"]*)"', line)
    return m.group(1).strip() if m else ""


def parse_m3u(text, source):
    channels = []

    lines = text.replace("\r", "").split("\n")

    info = None

    for raw in lines:
        line = raw.strip()

        if not line:
            continue

        if line.startswith("#EXTINF"):
            name = line.split(",", 1)[1].strip() if "," in line else "Unknown"

            info = {
                "name": name,
                "logo": attr(line, "tvg-logo"),
                "group": attr(line, "group-title"),
                "tvg_id": attr(line, "tvg-id"),
                "country": source.get("country", ""),
                "language": source.get("language", ""),
                "source": source.get("name", "")
            }

        elif not line.startswith("#") and info:
            info["url"] = line
            channels.append(info)
            info = None

    return channels


def load_sources():
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data

    return data.get("sources", [])


def main():
    DATA.mkdir(parents=True, exist_ok=True)

    sources = load_sources()

    all_channels = []
    seen = set()

    print("LazyTV Engine")
    print("=" * 50)

    for source in sources:
        if source.get("enabled", True) is False:
            continue

        url = source.get("url", "").strip()

        if not url:
            continue

        print("Reading:", source.get("name", url))

        try:
            text = download(url)
            channels = parse_m3u(text, source)

            added = 0

            for channel in channels:
                stream = channel.get("url", "")

                if not stream or stream in seen:
                    continue

                seen.add(stream)
                all_channels.append(channel)
                added += 1

            print("  +", added, "channels")

        except Exception as e:
            print("  ERROR:", e)

    all_channels.sort(
        key=lambda x: (
            x.get("country", "").lower(),
            x.get("group", "").lower(),
            x.get("name", "").lower()
        )
    )

    result = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "total": len(all_channels),
        "channels": all_channels
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(
            result,
            f,
            ensure_ascii=False,
            indent=2
        )

    print("=" * 50)
    print("TOTAL:", len(all_channels))
    print("Saved:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
