from datetime import datetime
from zoneinfo import ZoneInfo

from icalendar import Calendar

from montreal_visual_art_calendar import ArtEvent, _french_occurrences, build_calendar, deduplicate


NOW = datetime(2026, 10, 10, 12, tzinfo=ZoneInfo("America/Toronto"))


def test_french_occasion_parser():
    values = _french_occurrences("Vernissage le jeudi 15 octobre à 17h 30.", NOW)
    assert values[0][0] == "Vernissage"
    assert values[0][1].isoformat() == "2026-10-15T17:30:00-04:00"


def test_deduplication_and_calendar_timezone():
    event = ArtEvent("test", "1", "Vernissage: Show", "2026-10-15T17:00:00-04:00", None, "Gallery", "Montréal", "https://example.test")
    assert len(deduplicate([event, event])) == 1
    parsed = Calendar.from_ical(build_calendar([event], NOW))
    assert parsed.walk("VEVENT")[0].decoded("DTSTART").tzinfo.key == "America/Toronto"
