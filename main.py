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


def room_names(items):
    """Return the short classroom codes instead of long/short duplicates."""
    out = []
    for obj in items or ():
        if isinstance(obj, str):
            value = obj
        else:
            value = (getattr(obj, "name", None)
                     or getattr(obj, "short_name", None)
                     or getattr(obj, "long_name", None))
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
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
                rooms=room_names(getattr(period, "rooms", [])),
                teachers=[] if source == "login" else names(getattr(period, "teachers", [])),
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


def legacy_public_parse(payload, tz):
    """Accept the nested JSON structures used by the older public weekly API.

    Fail closed if subject names cannot be resolved; never publish anonymous
    identifiers or unrelated class entries as a seemingly valid calendar.
    """
    elements = {}
    periods = []
    def walk(obj):
        if isinstance(obj, list):
            for child in obj:
                walk(child)
            return
        if not isinstance(obj, dict):
            return
        if {"id", "type"} <= obj.keys() and ("name" in obj or "longName" in obj):
            keys = [str(obj["type"]), str(obj["id"])]
            elements[tuple(keys)] = str(obj.get("longName") or obj.get("name") or "")
        if all(k in obj for k in ("date", "startTime", "endTime")):
            periods.append(obj)
            return
        for value in obj.values():
            walk(value)
    walk(payload)
    result = []
    for p in periods:
        def by_type(number, attribute):
            out = []
            for v in p.get(attribute) or []:
                if isinstance(v, str):
                    out.append(v)
                elif isinstance(v, dict):
                    name = v.get("longName") or v.get("name") or v.get("shortName")
                    if not name:
                        name = elements.get((str(v.get("type", number)), str(v.get("id"))))
                    if name:
                        out.append(str(name))
            for el in p.get("elements") or []:
                if not isinstance(el, dict) or str(el.get("type")) != str(number):
                    continue
                value = el.get("longName") or el.get("name") or elements.get((str(number), str(el.get("id"))))
                if value:
                    out.append(str(value))
            return list(dict.fromkeys(out))
        subjects = by_type(3, "subjects")
        rooms = by_type(4, "rooms")
        teachers = by_type(2, "teachers")
        start = localized(p["date"], p["startTime"], tz)
        end = localized(p["date"], p["endTime"], tz)
        if end <= start:
            end += timedelta(days=1)
        result.append(dict(start=start, end=end, subjects=subjects,
            rooms=rooms, teachers=teachers, lesson=str(p.get("lessonId") or p.get("id") or ""),
            cancelled=p.get("code") in ("cancelled", "CANCELLED") or
                      p.get("cellState") in ("CANCELLED", "CANCELED") or
                      p.get("isCancelled", False) is True,
            note=str(p.get("substText") or p.get("periodText") or "")))
    return result

def legacy_public_fetch(cfg, start, end):
    """Try WebUntis's earlier, undocumented public weekly endpoint.

    Untis may disable this API; a 404 is not interpreted as valid empty data.
    """
    import requests
    from time import sleep
    tz = ZoneInfo(cfg["timezone"])
    hostname = cfg["server"].strip("/")
    suffix = "/api/public/timetable/weekly/data"
    base_paths = [f"https://{hostname}/WebUntis{suffix}",
                  f"https://{hostname}{suffix}"]
    session = requests.Session()
    session.headers.update({"User-Agent": "FK04-12ME-PersonalCalendar/1.0",
                            "Accept": "application/json"})
    probe_day = date(2026, 10, 12)
    params = dict(elementType=1, elementId=cfg["class_id"],
                  date=probe_day.isoformat(), formatId=1)
    errors = []
    selected_path = None
    probe_rows = None
    for url in base_paths:
        try:
            response = session.get(url, params=params, timeout=15)
            response.raise_for_status()
            probe_rows = legacy_public_parse(response.json(), tz)
            if not probe_rows:
                raise ValueError("Antwort hat keine lesbaren Unterrichtseinträge")
            if not any(e["subjects"] for e in probe_rows):
                raise ValueError("Unterricht vorhanden, aber keine auflösbaren Fachnamen")
            selected_path = url
            break
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__} {exc}")
    if selected_path is None:
        raise RuntimeError("Legacy-API nicht nutzbar: " + " | ".join(errors))
    results = []
    for monday in mondays(start, end):
        if monday == probe_day:
            rows = probe_rows
        else:
            response = session.get(selected_path,
                params={**params, "date": monday.isoformat()}, timeout=15)
            response.raise_for_status()
            rows = legacy_public_parse(response.json(), tz)
            if rows and not any(e["subjects"] for e in rows):
                raise ValueError(f"Keine lesbaren Fachnamen in Woche {monday}")
        results.extend(rows)
        sleep(0.25)
    return results

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
        # Avoid getKlassen: FK04 currently returns a schoolyear-null error on that RPC.
        # The class ID was taken from the publicly visible 12ME timetable URL.
        class_id = int(cfg["class_id"])
        # FK04's teaching timetable currently ends on 22 January 2027.
        # Requests crossing that server-side boundary fail as DateNotAllowed.
        teaching_end = date(2027, 1, 22)
        for monday in mondays(start, min(end, teaching_end)):
            week_start = max(monday, start)
            week_end = min(monday + timedelta(days=6), end, teaching_end)
            try:
                periods = session.timetable_extended(start=week_start,
                          end=week_end, klasse=class_id)
            except webuntis.errors.DateNotAllowed as exc:
                print(f"WARNUNG: Woche {week_start} bis {week_end} von WebUntis "
                      f"wegen Schuljahresgrenze abgelehnt: {exc}", flush=True)
                continue
            result.extend(row(p, "login", tz) for p in periods)
    return result

def fetch(cfg, start, end):
    errors = []
    for method, fn in (("public-modern", public_fetch), ("public-legacy", legacy_public_fetch), ("login", login_fetch)):
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


def merge_lessons(events, max_break_minutes=20):
    """Join successive 45-minute lessons into course blocks.

    Only merge entries on the same date, with the same subject AND room.
    Include ordinary 10/15/20-minute lecture breaks in the continuous block,
    but do not bridge longer gaps or room changes.
    """
    buckets = defaultdict(list)
    for event, course in events:
        room_key = tuple(sorted(norm(room) for room in event.get("rooms", []) if room))
        buckets[(event["start"].date(), course, room_key)].append(event)

    blocks = []
    max_break = timedelta(minutes=max_break_minutes)
    for (_, course, _), entries in buckets.items():
        current = None
        notes = []
        for entry in sorted(entries, key=lambda x: (x["start"], x["end"])):
            if current is None or entry["start"] > current["end"] + max_break:
                if current is not None:
                    current["note"] = " / ".join(notes)
                    blocks.append((current, course))
                current = dict(entry)
                notes = []
            else:
                current["end"] = max(current["end"], entry["end"])
                current["teachers"] = list(dict.fromkeys(
                    current.get("teachers", []) + entry.get("teachers", [])))
            if entry.get("note") and entry["note"] not in notes:
                notes.append(entry["note"])
        if current is not None:
            current["note"] = " / ".join(notes)
            blocks.append((current, course))
    return sorted(blocks, key=lambda x: (x[0]["start"], x[1], tuple(x[0].get("rooms", []))))

def ical(events):
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "CALSCALE:GREGORIAN",
             "PRODID:-//FK04 12ME//Filtered Timetable//DE", "METHOD:PUBLISH",
             "X-WR-CALNAME:FK04 12ME – Meine Module",
             "X-WR-TIMEZONE:Europe/Berlin",
             "REFRESH-INTERVAL;VALUE=DURATION:PT3H", "X-PUBLISHED-TTL:PT3H"]
    repeats = defaultdict(int)
    for item, course in sorted(events, key=lambda x:(x[0]["start"], x[1], tuple(x[0].get("rooms", [])))):
        room = ", ".join(item.get("rooms", []))
        key = (item["start"].date(), course, room)
        repeats[key] += 1
        identity = "|".join((str(key[0]), course, room, str(repeats[key])))
        uid = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:30] + "@fk04-12me-calendar"
        description = "Dozenten: " + (", ".join(item["teachers"]) or "nicht angegeben")
        if item["note"]:
            description += "\nWebUntis: " + item["note"]
        description += "\nQuelle: FK04 WebUntis; inoffizieller Kalender"
        lines.extend(["BEGIN:VEVENT", "UID:" + uid, "DTSTAMP:" + now,
             "DTSTART:" + item["start"].astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
             "DTEND:" + item["end"].astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
             "SUMMARY:" + escape((room + " · " if room else "") + course),
             "LOCATION:" + escape(room),
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
    blocks = merge_lessons(selected)
    temp.write_bytes(ical(blocks).encode("utf-8"))
    temp.replace(dest)
    print(f"iCal erzeugt: {len(blocks)} Unterrichtsblöcke aus {len(selected)} Einzelstunden")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("FEHLER:", exc, file=sys.stderr)
        sys.exit(1)
