#!/usr/bin/env python3
"""Fetch a channel EPG source URL and export a valid XMLTV-like file."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


DEFAULT_OUTPUT = "epg.xml"
DEFAULT_DATABASE = "channels.json"


def fetch_bytes(source_url: str, timeout: int = 30) -> bytes:
    """Download content from a local path, HTTP URL or file URL."""
    if not source_url.strip():
        raise ValueError("A source URL or file path is required.")

    if len(source_url) >= 2 and source_url[1] == ":" and source_url[0].isalpha():
        path = Path(source_url)
        return path.read_bytes()

    parsed = urlparse(source_url)

    if parsed.scheme in {"http", "https"}:
        request = Request(source_url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=timeout) as response:
            return response.read()

    if parsed.scheme == "file":
        file_path = Path(parsed.path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        return file_path.read_bytes()

    if parsed.scheme == "":
        path = Path(source_url)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return path.read_bytes()

    raise ValueError(f"Unsupported source URL type: {source_url}")


def verify_source_url(source_url: str, timeout: int = 30) -> int:
    """Verify that a source can be fetched and returns content."""
    try:
        content_length = len(fetch_bytes(source_url, timeout=timeout))
    except Exception as exc:
        raise ValueError(f"URL is not working: {source_url} ({exc})") from exc
    if content_length == 0:
        raise ValueError(f"URL is not working: {source_url} returned no content.")
    return content_length


def strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value, flags=re.S)


def clean_text(value: str) -> str:
    text = html.unescape(value)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_title_and_description(row: str) -> tuple[str, str]:
    title_match = re.search(
        r'<div[^>]*class="[^"]*div_program_title_on_channel[^"]*"[^>]*>.*?<span[^>]*>(.*?)</span>',
        row,
        re.S | re.I,
    )
    if title_match:
        title = clean_text(strip_tags(title_match.group(1)))
    else:
        first_span = re.search(r'<span[^>]*>(.*?)</span>', row, re.S | re.I)
        title = clean_text(strip_tags(first_span.group(1))) if first_span else "Program"

    description = ""
    if title_match:
        after_title = row[title_match.end() :]
        description_match = re.search(r"(.*?)(?:</div>\s*</td>|</div>\s*$)", after_title, re.S | re.I)
        if description_match:
            raw_description = description_match.group(1)
            description = clean_text(strip_tags(raw_description))
    return title, description


def parse_time_to_dt(date_str: str, time_text: str) -> datetime:
    """Parse an input like '12:00 AM' and combine it with YYYY-MM-DD."""
    parsed_time = datetime.strptime(time_text.strip().upper(), "%I:%M %p").time()
    return datetime.strptime(date_str, "%Y-%m-%d").replace(hour=parsed_time.hour, minute=parsed_time.minute)


def guess_channel_name(source_url: str) -> tuple[str, str]:
    parsed = urlparse(source_url)
    path = parsed.path.strip("/")
    slug = path.split("/")[-2] if "/canal/" in path else path.split("/")[-1]
    slug = slug or "channel"
    label = slug.replace("_", " ").title()
    return slug, label


def extract_channel_name(html_text: str, fallback_slug: str) -> str:
    match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html_text, re.I)
    if match:
        title = match.group(1)
        title = title.replace("&amp;", "&")
        title = re.sub(r"\s+Lunes\s+\d+\s+de\s+\w+\s+de\s+\d{4}.*$", "", title, flags=re.I)
        title = re.sub(r"\s+\|\s+.*$", "", title)
        title = re.sub(r"^\s*Canal\s+", "", title, flags=re.I)
        title = re.sub(r"\s*\([^)]*\)\s*$", "", title)
        title = title.strip()
        if title and title.strip() != "":
            if " " not in title:
                return title.upper()
            return title
    fallback_name = fallback_slug.replace("_", " ")
    return fallback_name.upper() if " " not in fallback_name else fallback_name.title()


def build_date_urls(source_url: str, days: int = 3) -> list[str]:
    parsed = urlparse(source_url)
    match = re.search(r"/canal/.+/(\d{4}-\d{2}-\d{2})$", source_url)
    if not match:
        return [source_url]

    start_date = datetime.strptime(match.group(1), "%Y-%m-%d")
    base = source_url.rsplit("/", 1)[0]
    return [f"{base}/{(start_date + timedelta(days=offset)).strftime('%Y-%m-%d')}" for offset in range(days)]


def format_duration(start_dt: datetime, end_dt: datetime) -> str:
    delta = max(int((end_dt - start_dt).total_seconds()), 0)
    hours, remainder = divmod(delta, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}{minutes:02d}{seconds:02d}"


def build_html_epg(source_url: str, source_html: str, channel_id: str | None) -> ET.Element:
    date_match = re.search(r"/canal/.+/(\d{4}-\d{2}-\d{2})$|/canal/.+/(\d{4}-\d{2}-\d{2})/", source_url)
    date_str = (date_match.group(1) or date_match.group(2)) if date_match else "2026-09-28"

    final_channel_name = extract_channel_name(source_html, channel_id or "ESPN")

    root = ET.Element("BroadcastData")
    root.set("code", "1100000000")
    root.set("creationtime", datetime.now().strftime("%Y%m%d%H%M%S"))
    root.set("version", "2.0")

    scheduler = ET.SubElement(root, "SchedulerData")
    scheduler.set("type", "PROGRAM")

    channel_el = ET.SubElement(scheduler, "Channel")
    channel_text = ET.SubElement(channel_el, "ChannelText")
    channel_text.set("language", "spa")
    channel_name = ET.SubElement(channel_text, "ChannelName")
    channel_name.text = final_channel_name

    rows = re.findall(r'<tr class="tbl_EPG_(?:row|rowAlternate)">.*?</tr>', source_html, re.S)
    if not rows:
        raise ValueError("No schedule rows were found in the page source.")

    event_index = 1
    for row in rows:
        times = re.findall(r'<time datetime="([^"]+)">([^<]+)</time>', row, re.S)
        if len(times) < 2:
            continue

        start_value = clean_text(times[0][1])
        end_value = clean_text(times[1][1])
        try:
            start_dt = parse_time_to_dt(date_str, start_value)
            end_dt = parse_time_to_dt(date_str, end_value)
        except ValueError:
            continue

        title, description = extract_title_and_description(row)

        event = ET.SubElement(channel_el, "Event")
        event.set("eventod", str(event_index))
        event.set("begintime", start_dt.strftime("%Y%m%d%H%M%S"))
        event.set("duration", format_duration(start_dt, end_dt))
        event.set("eventtype", "00")

        event_text = ET.SubElement(event, "EventText")
        event_text.set("language", "spa")

        title_elem = ET.SubElement(event_text, "Name")
        title_elem.text = title

        short_desc = ET.SubElement(event_text, "ShortDescription")
        short_desc.text = description

        extended_info = ET.SubElement(event_text, "ExtendedInfo")
        extended_info.set("itemname", "Actors")
        extended_info.set("itemcontent", "S/D")

        event_index += 1

    if len(channel_el.findall("Event")) == 0:
        raise ValueError("The page was fetched but no programmes could be parsed from the schedule table.")

    ET.indent(root, space="  ")
    return root


def write_xml_file(output_path: Path, root: ET.Element) -> None:
    xml_text = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    declaration = '<?xml version="1.0" encoding="gb2312" standalone="yes"?>\n'.encode("gb2312")
    safe_bytes = xml_text.encode("gb2312", "xmlcharrefreplace")
    output_path.write_bytes(declaration + safe_bytes)


def build_output_xml(source_url: str, source_bytes: bytes, channel_id: str | None) -> ET.Element:
    source_text = source_bytes.decode("utf-8", errors="replace")

    if "<BroadcastData" in source_text:
        try:
            root = ET.fromstring(source_bytes)
        except ET.ParseError:
            root = ET.fromstring(source_text.encode("utf-8"))
        if len(root.findall(".//Event")) == 0:
            raise ValueError("No programme entries were found in the source XML.")
        return root

    if "<tv" in source_text:
        try:
            root = ET.fromstring(source_bytes)
        except ET.ParseError:
            root = ET.fromstring(source_text.encode("utf-8"))
        tv_root = next((element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "tv"), None)
        if tv_root is None:
            raise ValueError("The source XML does not contain a valid <tv> root element.")

        samples = build_html_epg(source_url, source_text, channel_id)
        if len(samples.findall(".//Event")) > 0:
            return samples
        raise ValueError("The XML source does not have any programme entries to export.")

    return build_html_epg(source_url, source_text, channel_id)


def build_multi_day_output(source_url: str, days: int = 3, channel_id: str | None = None) -> ET.Element:
    urls = build_date_urls(source_url, days)
    if not urls:
        raise ValueError(f"Could not determine the date range from: {source_url}")

    first_page = fetch_bytes(urls[0])
    first_root = build_output_xml(urls[0], first_page, channel_id)
    channel_name = first_root.find("./SchedulerData/Channel/ChannelText/ChannelName")
    if channel_name is not None and channel_name.text:
        channel_name.text = channel_name.text.strip()

    event_counter = 1
    for url in urls[1:]:
        page = fetch_bytes(url)
        root = build_output_xml(url, page, channel_id)
        events = root.findall("./SchedulerData/Channel/Event")
        for event in events:
            cloned = ET.fromstring(ET.tostring(event, encoding="unicode"))
            event_od = cloned.get("eventod")
            if event_od is not None:
                cloned.set("eventod", str(event_counter))
            first_root.find("./SchedulerData/Channel").append(cloned)
            event_counter += 1

    for idx, event in enumerate(first_root.findall("./SchedulerData/Channel/Event"), start=1):
        event.set("eventod", str(idx))

    return first_root


def load_channel_database(database_path: Path) -> list[dict[str, object]]:
    """Load channel records from the JSON database."""
    with database_path.open("r", encoding="utf-8") as database_file:
        records = json.load(database_file)

    if not isinstance(records, list):
        raise ValueError(f"Channel database must contain a list: {database_path}")

    validated_records: list[dict[str, object]] = []
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"Channel record {index} must be an object.")
        validate_channel_record(record, f"Channel record {index}")
        record["name"] = str(record["name"]).strip().upper()
        validated_records.append(record)
    return validated_records


def validate_channel_record(record: dict[str, object], label: str = "Channel") -> None:
    """Validate one channel database record."""
    if not isinstance(record.get("name"), str) or not str(record["name"]).strip():
        raise ValueError(f"{label} needs a non-empty 'name'.")
    if not isinstance(record.get("url"), str) or not str(record["url"]).strip():
        raise ValueError(f"{label} needs a non-empty 'url'.")
    days = record.get("days")
    if isinstance(days, bool) or not isinstance(days, int) or days < 1:
        raise ValueError(f"{label} needs a positive integer 'days'.")


def save_channel_database(database_path: Path, records: list[dict[str, object]]) -> None:
    """Save channel records to the JSON database."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_records = []
    for record in records:
        normalized_record = dict(record)
        normalized_record["name"] = str(normalized_record["name"]).strip().upper()
        normalized_records.append(normalized_record)
    with database_path.open("w", encoding="utf-8") as database_file:
        json.dump(normalized_records, database_file, ensure_ascii=False, indent=2)
        database_file.write("\n")


def find_channel_record(records: list[dict[str, object]], channel_name: str) -> dict[str, object]:
    """Find a channel by its configured name, case-insensitively."""
    wanted_name = channel_name.strip().casefold()
    if not wanted_name:
        raise ValueError("A channel name is required.")
    for record in records:
        name = str(record["name"])
        if name.casefold() == wanted_name:
            return record
    available = ", ".join(str(record["name"]) for record in records)
    raise ValueError(f"Channel name not found: {channel_name}. Available channels: {available or 'none'}")


def add_channel_record(records: list[dict[str, object]], name: str, url: str, days: int) -> None:
    """Add a channel, rejecting duplicate names."""
    if any(str(record["name"]).casefold() == name.strip().casefold() for record in records):
        raise ValueError(f"Channel already exists: {name}")
    record: dict[str, object] = {"name": name.strip().upper(), "url": url.strip(), "days": days}
    validate_channel_record(record)
    records.append(record)


def update_channel_record(
    records: list[dict[str, object]], channel_name: str, url: str | None = None, days: int | None = None
) -> None:
    """Update the URL and/or day count for an existing channel."""
    record = find_channel_record(records, channel_name)
    if url is not None and url.strip():
        record["url"] = url.strip()
    if days is not None:
        record["days"] = days
    validate_channel_record(record)


def delete_channel_record(records: list[dict[str, object]], channel_name: str) -> None:
    """Delete an existing channel by name."""
    if not records:
        raise ValueError("There are no channels to delete.")
    record = find_channel_record(records, channel_name)
    records.remove(record)


def generate_channel_file(record: dict[str, object], timeout: int = 30) -> Path:
    """Generate the default output file for one configured channel."""
    source_url = str(record["url"])
    configured_name = str(record["name"]).strip()
    days = int(record["days"])
    source_bytes = fetch_bytes(source_url, timeout=timeout)
    output_path = Path("output") / f"{configured_name.replace('/', '-').replace('\\', '-').strip()}.xml"
    root = build_multi_day_output(source_url, days=days, channel_id=None)
    channel_name = root.find("./SchedulerData/Channel/ChannelText/ChannelName")
    if channel_name is not None:
        channel_name.text = configured_name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_xml_file(output_path, root)
    print(f"Generated {output_path.resolve()} ({len(root.findall('.//Event'))} programme(s), {days} day(s))")
    return output_path


def interactive_database_menu(database_path: Path, timeout: int = 30) -> int:
    """Manage the channel database and generate configured channel files."""
    if database_path.exists():
        records = load_channel_database(database_path)
    else:
        records = []
        save_channel_database(database_path, records)

    while True:
        print("\nChannel database")
        print("1. Add channel")
        print("2. Update channel URL or days")
        print("3. Delete channel")
        print("4. Generate files for all channels")
        print("0. Exit")
        choice = input("Choose an option: ").strip()

        try:
            if choice == "1":
                name = input("Channel name: ").strip()
                url = input("URL: ").strip()
                days = int(input("Days: ").strip())
                verify_source_url(url, timeout=timeout)
                add_channel_record(records, name, url, days)
                save_channel_database(database_path, records)
                print(f"Added channel: {name}")
            elif choice == "2":
                channel_name = input("Channel name to update: ").strip()
                record = find_channel_record(records, channel_name)
                url = input(f"New URL (Enter to keep {record['url']}): ").strip()
                days_text = input(f"New days (Enter to keep {record['days']}): ").strip()
                days = int(days_text) if days_text else None
                if url:
                    verify_source_url(url, timeout=timeout)
                update_channel_record(records, channel_name, url or None, days)
                save_channel_database(database_path, records)
                print(f"Updated channel: {record['name']}")
            elif choice == "3":
                if not records:
                    raise ValueError("There are no channels to delete.")
                channel_name = input("Channel name to delete: ").strip()
                delete_channel_record(records, channel_name)
                save_channel_database(database_path, records)
                print(f"Deleted channel: {channel_name}")
            elif choice == "4":
                if not records:
                    print("The database has no channels.")
                for record in records:
                    generate_channel_file(record, timeout=timeout)
            elif choice == "0":
                return 0
            else:
                print("Invalid option.")
        except (ValueError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download an EPG source and create a local XML file for a channel."
    )
    parser.add_argument("--source-url", help="URL or local path to the source EPG XML/HTML file.")
    parser.add_argument("--database", default=DEFAULT_DATABASE, help=f"JSON channel database (default: {DEFAULT_DATABASE}).")
    parser.add_argument("--channel", help="Configured channel name to export from the JSON database.")
    parser.add_argument("--manage", action="store_true", help="Open the interactive channel database menu.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"Output XML file path (default: {DEFAULT_OUTPUT}).")
    parser.add_argument("--channel-id", help="Optional channel ID used when exporting only one channel.")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds.")
    parser.add_argument("--days", type=int, default=3, help="Number of consecutive days to export (default: 3).")
    args = parser.parse_args()

    try:
        if args.manage or (not args.channel and not args.source_url):
            return interactive_database_menu(Path(args.database), timeout=args.timeout)

        configured_name = None
        if args.channel:
            records = load_channel_database(Path(args.database))
            record = find_channel_record(records, args.channel)
            source_url = str(record["url"])
            days = int(record["days"])
            configured_name = str(record["name"]).strip()
        elif args.source_url:
            source_url = args.source_url
            days = max(args.days, 1)
        else:
            raise ValueError("Provide --source-url or --channel.")

        source_bytes = fetch_bytes(source_url, timeout=args.timeout)
        inferred_channel_name = configured_name or extract_channel_name(
            source_bytes.decode("utf-8", errors="replace"), args.channel_id or "channel"
        )
        default_name = inferred_channel_name.replace("/", "-").replace("\\", "-").strip()
        default_output = Path(args.output)

        if args.output == DEFAULT_OUTPUT:
            output_dir = Path("output")
            output_dir.mkdir(parents=True, exist_ok=True)
            default_output = output_dir / f"{default_name}.xml"

        root = build_multi_day_output(source_url, days=days, channel_id=args.channel_id)
        if configured_name:
            channel_name = root.find("./SchedulerData/Channel/ChannelText/ChannelName")
            if channel_name is not None:
                channel_name.text = configured_name

        output_path = default_output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_xml_file(output_path, root)

        programmes_found = len(root.findall(".//Event"))
        print(f"Downloaded {len(source_bytes)} bytes from {source_url}")
        print(f"Found {programmes_found} programme(s) across {days} day(s)")
        print(f"Saved XML to: {output_path.resolve()}")
        return 0
    except Exception as exc:  # pragma: no cover - CLI error handling
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
