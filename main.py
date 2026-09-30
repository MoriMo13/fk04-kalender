#!/usr/bin/env python3
"""Filtered, regularly refreshed FK04/12ME WebUntis -> iCalendar export."""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone, time
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent

def norm(value):
    s = unicodedata.normalize("NFKD", str(value or "").casefold().replace("ß", "ss"))
    return " ".join(re.findall("[a-z0-9]+", "".join(x for x in s if not unicodedata.combining(x))))

def names(items):
    out = []
    for obj in items or ():
        if isinstance(obj, str):
            out.append(obj)
            continue
        for field in ("long_name", "longname", "name", "alternate_name"):
            value = getattr(obj, field, None)
            if value and str(value) not in out:
                out.append(str(value))
    return out

def course_for(subjects, courses):
    for course, aliases in courses.items():
        for subject in subjects:
            actual = norm(subject)
            for alias in aliases:
                needle = norm(alias)
                if not needle:
                    continue
                if re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", actual):
                    return course
                if " " not in needle and len(needle) >= 7 and re.search(r"(?<![a-z0-9])" + re.escape(needle), actual):
                    return course
    return None

def localized(day, clock, tz):
    if isinstance(clock, datetime):
        return clock.replace(tzinfo=tz) if clock.tzinfo is None else clock.astimezone(tz)
    if isinstance(day, int):
        day = datetime.strptime(str(day), "%Y%m%d").date()
    elif isinstance(day, str):
        day = date.fromisoformat(day)
    if isinstance(clock, int):
        clock = time(hour=clock // 100, minute=clock % 100)
    elif isinstance(clock, str):
        clock = time.fromisoformat(clock)
    return datetime.combine(day, clock, tzinfo=tz)

def cancelled(period):
    if any(getattr(period, flag, False) is True for flag in ("is_cancelled", "cancelled")):
        return True
    return any(norm(getattr(period, key, "")) in ("cancelled", "canceled", "entfall", "ausfall")
               for key in ("code", "status"))

def row(period, source, tz):
    if source == "public":
        start = localized(period.date, period.start_time, tz)
        end = localized(period.date, period.end_time, tz)
        lesson = getattr(period, "lesson_id", None)
    else:
        start = localized(None, period.start, tz)
        end = localized(None, period.end, tz)
        lesson = getattr(period, "lsnumber", None)
    if end <= start:
        end += timedelta(days=1)
    return dict(start=start, end=end, subjects=names(getattr(period, "subjects", [])),
                rooms=names(getattr(period, "rooms", [])),
                teachers=names(getattr(period, "teachers", [])),
                lesson=str(lesson or getattr(period, "id", "") or ""),
                cancelled=cancelled(period),
                note=str(getattr(period, "substText", "") or getattr(period, "info", "") or ""))

def mondays(start, end):
    day = start - timedelta(days=start.weekday())
    while day <= end:
        yield day
        day += timedelta(days=7)

def public_fetch(cfg, start, end):
    from webuntis_public import WebUntisPublicClient
    client = WebUntisPublicClient(cfg["server"], school=cfg["school"], rate_limit=0.35)
    tz = ZoneInfo(cfg["timezone"])
    return [row(p, "public", tz)
            for monday in mondays(start, end)
            for p in client.fetch_week(class_id=int(cfg["class_id"]), date=monday).periods]

def login_fetch(cfg, start, end):
    import webuntis
    username = os.getenv("UNTIS_USERNAME", "")
    password = os.getenv("UNTIS_PASSWORD", "")
    if not username or not password:
        raise RuntimeError("UNTIS_USERNAME und UNTIS_PASSWORD fehlen")
    tz = ZoneInfo(cfg["timezone"])
    result = []
    with webuntis.Session(server=cfg["server"], school=cfg["school"],
                         username=username, password=password,
                         useragent="FK04-12ME-Personal-Calendar/1.0").login() as session:
        matches = [c for c in session.klassen() if str(c.name).casefold() == cfg["class_name"].casefold()]
        if len(matches) != 1:
            raise RuntimeError("Klasse 12ME nicht eindeutig im WebUntis-Login gefunden")
        for monday in mondays(start, end):
            periods = session.timetable_extended(start=monday,
                      end=min(monday + timedelta(days=6), end), klasse=matches[0].id)
            result.extend(row(p, "login", tz) for p in periods)
    return result

def fetch(cfg, start, end):
    errors = []
    for method, fn in (("public", public_fetch), ("login", login_fetch)):
        if method == "login" and not (os.getenv("UNTIS_USERNAME") and os.getenv("UNTIS_PASSWORD")):
            errors.append("login: Secrets nicht hinterlegt")
            continue
        try:
            data = fn(cfg, start, end)
            if not data:
                raise ValueError("0 Einträge vom Server")
            print(f"Quelle: {method}; empfangene Termine: {len(data)}")
            return method, data
        except Exception as e:
            print(f"{method} gescheitert: {type(e).__name__}: {e}", file=sys.stderr)
            errors.append(f"{method}: {type(e).__name__}: {e}")
    raise RuntimeError("Kein Abruf möglich: " + " | ".join(errors))

def escape(s):
    return str(s or "").replace("\\", "\\\\").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")

def fold(line):
    parts, chunk, used = [], "", 0
    for char in line:
        width = len(char.encode("utf-8"))
        if chunk and used + width > 75:
            parts.append(chunk)
            chunk, used = " " + char, width + 1
        else:
            chunk += char
            used += width
    parts.append(chunk)
    return "\r\n".join(parts)

def ical(events):
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "CALSCALE:GREGORIAN",
             "PRODID:-//FK04 12ME//Filtered Timetable//DE", "METHOD:PUBLISH",
             "X-WR-CALNAME:FK04 12ME – Meine Module",
             "X-WR-TIMEZONE:Europe/Berlin",
             "REFRESH-INTERVAL;VALUE=DURATION:PT3H", "X-PUBLISHED-TTL:PT3H"]
    repeats = defaultdict(int)
    for item, course in sorted(events, key=lambda x:(x[0]["start"], x[1], x[0]["lesson"])):
        key = (item["start"].date(), course, item["lesson"])
        repeats[key] += 1
        identity = "|".join((str(key[0]), course, item["lesson"], str(repeats[key])))
        uid = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:30] + "@fk04-12me-calendar"
        description = "Dozenten: " + (", ".join(item["teachers"]) or "nicht angegeben")
        if item["note"]:
            description += "\nWebUntis: " + item["note"]
        description += "\nQuelle: FK04 WebUntis; inoffizieller Kalender"
        lines.extend(["BEGIN:VEVENT", "UID:" + uid, "DTSTAMP:" + now,
             "DTSTART:" + item["start"].astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
             "DTEND:" + item["end"].astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
             "SUMMARY:" + escape(course),
             "LOCATION:" + escape(", ".join(item["rooms"])),
             "DESCRIPTION:" + escape(description), "END:VEVENT"])
    lines.append("END:VCALENDAR")
    return "\r\n".join(map(fold, lines)) + "\r\n"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true", help="Only query week of 2026-10-12")
    args = parser.parse_args()
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    start = date.fromisoformat("2026-10-12" if args.probe else cfg["semester_start"])
    end = start + timedelta(days=6) if args.probe else date.fromisoformat(cfg["semester_end"])
    source, data = fetch(cfg, start, end)
    available, selected, found = Counter(), [], Counter()
    for event in data:
        available.update(event["subjects"])
        course = course_for(event["subjects"], cfg["courses"])
        if course:
            found[course] += 1
            if not event["cancelled"] and start <= event["start"].date() <= end:
                selected.append((event, course))
    diagnosis = (["Quelle: " + source, f"Zeitraum: {start} bis {end}",
                  f"Einträge gesamt: {len(data)}", f"Übernommen: {len(selected)}",
                  "", "MODUL-TREFFER:"] +
                  [f"{course}: {found[course]}" for course in cfg["courses"]] +
                  ["", "ALLE WEBUNTIS-FACHNAMEN:"] +
                  [f"{name}: {count}" for name, count in available.most_common()])
    directory = ROOT / "diagnostics"
    directory.mkdir(exist_ok=True)
    (directory / "subjects.txt").write_text("\n".join(diagnosis) + "\n", encoding="utf-8")
    print("\n".join(diagnosis[:12]))
    if not selected:
        raise RuntimeError("Kein passendes Fach gefunden. Details im Artifact fachnamen-diagnose.")
    if args.probe:
        print("Probe erfolgreich; keine Datei überschrieben.")
        return
    dest = ROOT / "docs" / "stundenplan.ics"
    dest.parent.mkdir(exist_ok=True)
    temp = dest.with_suffix(".ics.tmp")
    temp.write_bytes(ical(selected).encode("utf-8"))
    temp.replace(dest)
    print(f"iCal erzeugt: {len(selected)} Termine")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("FEHLER:", exc, file=sys.stderr)
        sys.exit(1)
