from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from icalendar import Calendar, Event

TIMEZONE = ZoneInfo("America/Toronto")
RCAAQ_EVENTS = "https://reseauartactuel.org/wp-json/wp/v2/event"
RCAAQ_MEMBERS = "https://reseauartactuel.org/wp-json/wp/v2/members"
CCA = "https://www.cca.qc.ca/en/calendar/"
UQAM_DESIGN = "https://centrededesign.com/"
USER_AGENT = "MontrealVisualArtCalendar/1.0 (+https://github.com/k10sj02/montreal-visual-art-calendar)"
FR_MONTHS = {"jan": 1, "fev": 2, "mar": 3, "avr": 4, "mai": 5, "juin": 6, "juil": 7, "aou": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
EN_MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}
OCCASION = re.compile(r"vernissage|finissage|artist(?:e)? talk|rencontre|présentation d.artiste|visite|atelier|table ronde|lancement|opening|tour|talk|workshop", re.I)


@dataclass(frozen=True)
class ArtEvent:
    source: str
    source_id: str
    title: str
    start: str
    end: str | None
    venue: str
    address: str
    url: str
    description: str = ""
    status: str = "CONFIRMED"

    @property
    def uid(self) -> str:
        return hashlib.sha256(f"{self.source}|{self.source_id}".encode()).hexdigest()[:28] + "@montreal-visual-art"


class Fetcher:
    def __init__(self):
        self.client = httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT, "Accept-Language": "fr-CA,fr;q=.9,en;q=.8"})

    def get(self, url: str) -> str:
        response = self.client.get(url)
        response.raise_for_status()
        return response.text


def _plain(value: str) -> str:
    return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)


def _fr_month(value: str) -> int | None:
    normalized = unicodedata.normalize("NFKD", value.casefold()).encode("ascii", "ignore").decode()
    return FR_MONTHS.get(normalized[:3])


def _infer_year(month: int, now: datetime) -> int:
    return now.year + (month < now.month - 2)


def _french_occurrences(text: str, now: datetime) -> list[tuple[str, datetime]]:
    output = []
    pattern = re.compile(r"(vernissage|finissage|rencontre|présentation d.artiste|visite(?: guidée)?|atelier|table ronde|lancement)[^.!?]{0,120}?(\d{1,2})(?:er)?\s+([A-Za-zÀ-ÿ.]+)[^.!?]{0,50}?(?:à|,|de)\s*(\d{1,2})\s*h\s*(\d{2})?", re.I)
    for kind, day, month_name, hour, minute in pattern.findall(text):
        month = _fr_month(month_name)
        if not month:
            continue
        output.append((kind.capitalize(), datetime(_infer_year(month, now), month, int(day), int(hour), int(minute or 0), tzinfo=TIMEZONE)))
    return output


def rcaaq_events(fetcher: Fetcher, now: datetime, final_day: date) -> list[ArtEvent]:
    posts = json.loads(fetcher.get(f"{RCAAQ_EVENTS}?per_page=100&_fields=id,link,title,content,acf"))
    member_ids = sorted({member for post in posts for member in (((post.get("acf") or {}).get("event") or {}).get("infos") or {}).get("members", [])})
    members = {}
    for index in range(0, len(member_ids), 50):
        include = ",".join(map(str, member_ids[index:index + 50]))
        for item in json.loads(fetcher.get(f"{RCAAQ_MEMBERS}?per_page=100&include={include}&_fields=id,title,acf")):
            info = (((item.get("acf") or {}).get("member") or {}).get("infos") or {})
            members[item["id"]] = {"name": _plain(item.get("title", {}).get("rendered", "")), **info}
    output = []
    for post in posts:
        info = (((post.get("acf") or {}).get("event") or {}).get("infos") or {})
        member = next((members.get(member_id) for member_id in info.get("members", []) if members.get(member_id, {}).get("city", "").casefold() in {"montréal", "montreal"}), None)
        if not member:
            continue
        title = _plain(post.get("title", {}).get("rendered", "Visual art event"))
        content = _plain(post.get("content", {}).get("rendered", ""))
        description = _plain(info.get("desc", ""))
        occasions = _french_occurrences(f"{description}. {content}", now)
        if info.get("single_event") and info.get("start_date"):
            begins = datetime.strptime(info["start_date"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TIMEZONE)
            if begins.hour or begins.minute:
                occasions.append(("Event", begins))
        seen = set()
        for kind, begins in occasions:
            if begins in seen or not now.date() <= begins.date() <= final_day:
                continue
            seen.add(begins)
            venue = info.get("place") or member.get("name") or "Montréal"
            address = ", ".join(filter(None, [member.get("address", ""), member.get("city", ""), member.get("postal_code", "")]))
            output.append(ArtEvent(
                source="reseau-art-actuel", source_id=f"{post['id']}-{begins.isoformat()}",
                title=f"{kind}: {title}", start=begins.isoformat(), end=None, venue=venue,
                address=address, url=post["link"], description=description or content[:500],
            ))
    if not output:
        raise RuntimeError("No current Montréal Réseau Art Actuel occasions found")
    return output


def cca_events(fetcher: Fetcher, now: datetime, final_day: date) -> list[ArtEvent]:
    soup = BeautifulSoup(fetcher.get(CCA), "html.parser")
    output = []
    seen = set()
    pattern = re.compile(r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)(?:\s+(20\d{2}))?\s*,\s*(\d{1,2})(?::(\d{2}))?(am|pm)", re.I)
    for link in soup.select("a.calendar-event-link[href]"):
        url = urljoin(CCA, link["href"])
        if url in seen:
            continue
        date_node = link.find_next("div", class_="date")
        if not date_node or "Call for Applications" in date_node.get_text(" ", strip=True):
            continue
        match = pattern.search(date_node.get_text(" ", strip=True))
        if not match:
            continue
        day, month_name, year, hour, minute, suffix = match.groups()
        hour = int(hour) % 12 + (12 if suffix.lower() == "pm" else 0)
        month = EN_MONTHS[month_name.casefold()]
        begins = datetime(int(year or _infer_year(month, now)), month, int(day), hour, int(minute or 0), tzinfo=TIMEZONE)
        if not now.date() <= begins.date() <= final_day:
            continue
        seen.add(url)
        category = date_node.select_one(".cat")
        output.append(ArtEvent(
            source="cca", source_id=f"{url.rstrip('/').rsplit('/', 1)[-1]}-{begins.isoformat()}",
            title=link.get("data-title") or link.get_text(" ", strip=True), start=begins.isoformat(), end=None,
            venue="Canadian Centre for Architecture", address="1920 rue Baile, Montréal, QC H3H 2S6",
            url=url, description=category.get_text(" ", strip=True).strip(" ,") if category else "Architecture and visual culture event.",
        ))
    if not output:
        raise RuntimeError("No current CCA events found")
    return output


def uqam_design_events(fetcher: Fetcher, now: datetime, final_day: date) -> list[ArtEvent]:
    soup = BeautifulSoup(fetcher.get(UQAM_DESIGN), "html.parser")
    output = []
    for article in soup.find_all("article"):
        heading = article.select_one("h2.entry-title a[href]")
        if not heading:
            continue
        text = article.get_text(" ", strip=True)
        title = heading.get_text(" ", strip=True)
        for kind, begins in _french_occurrences(text, now):
            if now.date() <= begins.date() <= final_day:
                output.append(ArtEvent(
                    source="uqam-design", source_id=f"{heading['href'].rstrip('/').rsplit('/', 1)[-1]}-{begins.isoformat()}",
                    title=f"{kind}: {title}" if kind.casefold() not in title.casefold() else title,
                    start=begins.isoformat(), end=None, venue="Centre de design de l’UQAM",
                    address="1440 rue Sanguinet, Montréal, QC H2X 3X9", url=heading["href"], description=text[:500],
                ))
    if not output:
        raise RuntimeError("No current Centre de design events found")
    return output


def deduplicate(events: list[ArtEvent]) -> list[ArtEvent]:
    unique = {}
    for event in events:
        normalized = unicodedata.normalize("NFKD", event.title.casefold())
        title = re.sub(r"^(vernissage|finissage|opening|event):", "", "".join(c for c in normalized if c.isalnum() or c == ":"))
        unique.setdefault((title, event.start[:16]), event)
    return list(unique.values())


def merge_state(current: list[ArtEvent], path: Path, now: datetime, successful: set[str]) -> list[ArtEvent]:
    old = {}
    if path.exists():
        try:
            old = json.loads(path.read_text()).get("events", {})
        except (OSError, json.JSONDecodeError):
            pass
    merged = {event.uid: {**asdict(event), "missing_runs": 0} for event in current}
    for uid, item in old.items():
        if uid in merged:
            continue
        try:
            begins = datetime.fromisoformat(item["start"])
        except (KeyError, ValueError):
            continue
        missing = int(item.get("missing_runs", 0)) + (item.get("source") in successful)
        if begins >= now - timedelta(days=1):
            merged[uid] = {**item, "missing_runs": missing, "status": "CANCELLED" if missing >= 2 else item.get("status", "CONFIRMED")}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"updated": now.isoformat(), "events": merged}, ensure_ascii=False, indent=2) + "\n")
    return [ArtEvent(**{key: value for key, value in item.items() if key != "missing_runs"}) for item in merged.values()]


def build_calendar(events: list[ArtEvent], generated: datetime) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", "-//Montréal Visual Art and Vernissages Calendar//EN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", "Montréal Visual Art & Vernissages")
    calendar.add("x-wr-timezone", "America/Toronto")
    calendar.add("refresh-interval", timedelta(hours=6), parameters={"VALUE": "DURATION"})
    for item in sorted(events, key=lambda value: (value.start, value.title)):
        event = Event()
        event.add("uid", item.uid)
        event.add("dtstamp", generated)
        event.add("dtstart", datetime.fromisoformat(item.start).astimezone(TIMEZONE))
        if item.end:
            event.add("dtend", datetime.fromisoformat(item.end).astimezone(TIMEZONE))
        event.add("summary", item.title)
        event.add("location", ", ".join(filter(None, [item.venue, item.address])))
        event.add("description", "\n".join(filter(None, [item.description, f"Original listing: {item.url}"])))
        event.add("url", item.url)
        event.add("status", item.status)
        event.add("categories", "Visual Art,Vernissage,Gallery")
        event.add("x-montreal-visual-art-source", item.source)
        calendar.add_component(event)
    return calendar.to_ical()


def main() -> None:
    root = Path.cwd()
    now = datetime.now(TIMEZONE)
    final_day = now.date() + timedelta(days=120)
    fetcher = Fetcher()
    collected, successful, errors, counts = [], set(), {}, {}
    for name, loader in (("reseau-art-actuel", rcaaq_events), ("cca", cca_events), ("uqam-design", uqam_design_events)):
        try:
            found = loader(fetcher, now, final_day)
            collected.extend(found)
            successful.add(name)
            counts[name] = len(found)
        except Exception as exc:
            errors[name] = str(exc)
    if not collected:
        raise RuntimeError("No current visual-art occasions found; refusing to publish an empty calendar")
    events = merge_state(deduplicate(collected), root / "data/state.json", now, successful)
    public = root / "public"
    public.mkdir(exist_ok=True)
    (public / "montreal-visual-art.ics").write_bytes(build_calendar(events, now))
    status = {"generated": now.isoformat(), "count": sum(e.status != "CANCELLED" for e in events), "cancelled": sum(e.status == "CANCELLED" for e in events), "sources": counts, "errors": errors}
    (public / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(status, ensure_ascii=False))
