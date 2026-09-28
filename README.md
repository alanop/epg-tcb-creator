# EPG TCB Creator

A simple Python application that downloads a channel programming calendar (EPG) from a URL or local XML file and writes a clean XMLTV-compatible output file.

## Features

- Connects to an HTTP/HTTPS URL or a local file.
- Reads XMLTV-style EPG data.
- Copies the channel and programme information into a new XML file.
- Optionally filters by a specific channel ID.
- Works without extra dependencies.

## Requirements

- Python 3.9+

## Usage

From the project root, run:

```bash
python main.py --source-url "https://example.com/epg.xml" --output epg.xml
```

To export only one channel:

```bash
python main.py --source-url "https://example.com/epg.xml" --channel-id "channel.example" --output channel_epg.xml
```

You can also use a local file path:

```bash
python main.py --source-url "C:/path/to/epg.xml" --output epg.xml
```

## Channel database

The `channels.json` file stores the configured channel name, source URL, and number of consecutive days to download:

```json
[
  {
    "name": "ESPN",
    "url": "https://www.gatotv.com/canal/espn_republica_dominicana/2026-09-28",
    "days": 3
  }
]
```

Export a configured channel by name:

```bash
python main.py --channel ESPN
```

Run the interactive channel database menu:

```bash
python main.py
```

The menu lets you add a channel, update its URL or number of days, delete a channel, or generate XML files for every channel in `channels.json`. Use `--manage` to open the same menu explicitly.

Use another database file when needed:

```bash
python main.py --database channels.json --channel ESPN
```

## Expected source format

The source should contain XMLTV-style data such as:

```xml
<tv>
  <channel id="channel.example">
    <display-name>Example Channel</display-name>
  </channel>

  <programme start="20260928090000 +0000" stop="20260928093000 +0000" channel="channel.example">
    <title>My Program</title>
    <desc>Program description</desc>
  </programme>
</tv>
```

## Output

The app writes a new XML file that keeps the original channel/programme data and adds a generator attribute.

## Example with a local sample file

```bash
python main.py --source-url "samples/sample_epg.xml" --output output/epg.xml
```
