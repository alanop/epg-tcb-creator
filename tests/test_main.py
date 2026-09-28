import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

import json

from main import (
    add_channel_record,
    build_date_urls,
    delete_channel_record,
    extract_channel_name,
    extract_title_and_description,
    find_channel_record,
    load_channel_database,
    save_channel_database,
    update_channel_record,
)


class ExtractTitleAndDescriptionTests(unittest.TestCase):
    def test_extracts_description_below_the_title(self):
        row = (
            '<tr class="tbl_EPG_row">'
            '<td class="tbl_EPG_ProgramsColumn">'
            '<div class="div_program_title_on_channel"><span>SportsCenter</span></div>'
            '<div>Get the latest sports news, analysis and scores.</div>'
            '</td>'
            '</tr>'
        )

        title, description = extract_title_and_description(row)

        self.assertEqual(title, 'SportsCenter')
        self.assertEqual(description, 'Get the latest sports news, analysis and scores.')

    def test_leaves_description_blank_when_none_exists(self):
        row = (
            '<tr class="tbl_EPG_row">'
            '<td class="tbl_EPG_ProgramsColumn">'
            '<div class="div_program_title_on_channel"><span>SportsCenter</span></div>'
            '</td>'
            '</tr>'
        )

        title, description = extract_title_and_description(row)

        self.assertEqual(title, 'SportsCenter')
        self.assertEqual(description, '')

    def test_strips_canal_and_country_from_channel_name(self):
        name = extract_channel_name('Canal ESPN (República Dominicana) | ESPN', 'ESPN')

        self.assertEqual(name, 'ESPN')

    def test_builds_three_day_url_range_from_start_date(self):
        urls = build_date_urls('https://www.gatotv.com/canal/espn_republica_dominicana/2026-09-28', 3)

        self.assertEqual(
            urls,
            [
                'https://www.gatotv.com/canal/espn_republica_dominicana/2026-09-28',
                'https://www.gatotv.com/canal/espn_republica_dominicana/2026-09-29',
                'https://www.gatotv.com/canal/espn_republica_dominicana/2026-09-30',
            ],
        )

    def test_loads_and_finds_channel_database_record(self):
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / 'channels.json'
            database_path.write_text(
                json.dumps([{'name': 'ESPN', 'url': 'https://example.test/espn', 'days': 3}]),
                encoding='utf-8',
            )

            records = load_channel_database(database_path)
            record = find_channel_record(records, 'espn')

        self.assertEqual(record['name'], 'ESPN')
        self.assertEqual(record['days'], 3)

    def test_add_update_delete_channel_database_record(self):
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / 'channels.json'
            records = []
            add_channel_record(records, 'espn 2', 'https://example.test/espn', 3)
            update_channel_record(records, 'espn 2', 'https://example.test/espn-new', 5)
            save_channel_database(database_path, records)

            self.assertEqual(load_channel_database(database_path)[0]['days'], 5)
            self.assertEqual(load_channel_database(database_path)[0]['name'], 'ESPN 2')
            delete_channel_record(records, 'ESPN 2')

        self.assertEqual(records, [])

    def test_delete_reports_empty_database(self):
        with self.assertRaisesRegex(ValueError, 'There are no channels to delete'):
            delete_channel_record([], 'ESPN')

    def test_delete_reports_incorrect_channel_name(self):
        records = [{'name': 'ESPN', 'url': 'https://example.test/espn', 'days': 3}]

        with self.assertRaisesRegex(ValueError, 'Channel name not found: ESPN 2'):
            delete_channel_record(records, 'ESPN 2')

    @patch('main.fetch_bytes', return_value=b'<html>schedule</html>')
    def test_verifies_url_before_it_can_be_added(self, fetch_mock):
        from main import verify_source_url

        content_length = verify_source_url('https://example.test/espn')

        self.assertEqual(content_length, 21)
        fetch_mock.assert_called_once_with('https://example.test/espn', timeout=30)

    @patch('main.fetch_bytes', return_value=b'')
    def test_rejects_url_that_returns_no_content(self, fetch_mock):
        from main import verify_source_url

        with self.assertRaisesRegex(ValueError, r'URL is not working: https://example\.test/empty'):
            verify_source_url('https://example.test/empty')

        fetch_mock.assert_called_once_with('https://example.test/empty', timeout=30)

    @patch('main.fetch_bytes', side_effect=OSError('connection refused'))
    def test_reports_when_url_cannot_be_reached(self, fetch_mock):
        from main import verify_source_url

        with self.assertRaisesRegex(ValueError, r'URL is not working: https://example\.test/missing'):
            verify_source_url('https://example.test/missing')

        fetch_mock.assert_called_once_with('https://example.test/missing', timeout=30)


if __name__ == '__main__':
    unittest.main()
