import unittest
from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from types import SimpleNamespace
import main

class CalendarTests(unittest.TestCase):
    def test_module_filter(self):
        courses={"Ringvorlesung Elektromobilität":["Ringvorl"],
                 "Felder und Wellen":["Felder und Wellen"]}
        self.assertEqual(main.course_for(["Ringvorlesung Elektromobilität"],courses),"Ringvorlesung Elektromobilität")
        self.assertEqual(main.course_for(["Felder und Wellen"],courses),"Felder und Wellen")
        self.assertIsNone(main.course_for(["Digitale Systeme"],courses))
    def test_timezone(self):
        tz=ZoneInfo("Europe/Berlin")
        d=main.localized(date(2026,10,12),900,tz)
        self.assertEqual(d.astimezone(timezone.utc).hour,7)
        self.assertEqual(main.localized(date(2026,11,12),900,tz).astimezone(timezone.utc).hour,8)
    def test_ics(self):
        d=datetime(2026,10,12,9,tzinfo=ZoneInfo("Europe/Berlin"))
        event={"start":d,"end":d+timedelta(minutes=90),"rooms":["R2.001"],"teachers":["Prof. Beispiel"],"lesson":"27","note":""}
        calendar=main.ical([(event,"Felder und Wellen")])
        for term in ("BEGIN:VCALENDAR","BEGIN:VEVENT","UID:","DTSTART:20261012T070000Z","SUMMARY:Felder und Wellen","LOCATION:R2.001"):
            self.assertIn(term,calendar)
    def test_lecture_blocks_and_room_in_title(self):
        tz=ZoneInfo("Europe/Berlin")
        d=datetime(2026,10,6,9,tzinfo=tz)
        def event(start_min, end_min, room):
            return {"start":d+timedelta(minutes=start_min),
                    "end":d+timedelta(minutes=end_min),
                    "rooms":[room],"teachers":[],"lesson":"27","note":""}
        classes=[(event(0,45,"R3.012"),"Batterien und Brennstoffzellen"),
                 (event(60,105,"R3.012"),"Batterien und Brennstoffzellen"),
                 (event(120,165,"R3.012"),"Batterien und Brennstoffzellen")]
        blocks=main.merge_lessons(classes)
        self.assertEqual(len(blocks),1)
        self.assertEqual(blocks[0][0]["end"],d+timedelta(minutes=165))
        calendar=main.ical(blocks)
        self.assertEqual(calendar.count("BEGIN:VEVENT"),1)
        self.assertIn("SUMMARY:R3.012 · Batterien und Brennstoffzellen",calendar)
        self.assertIn("LOCATION:R3.012",calendar)
    def test_room_changes_and_long_breaks_remain_separate(self):
        tz=ZoneInfo("Europe/Berlin")
        d=datetime(2026,10,6,9,tzinfo=tz)
        def event(start_min, end_min, room):
            return {"start":d+timedelta(minutes=start_min),
                    "end":d+timedelta(minutes=end_min),
                    "rooms":[room],"teachers":[],"lesson":"27","note":""}
        lessons=[(event(0,45,"R3.012"),"Felder und Wellen"),
                 (event(45,90,"R2.093"),"Felder und Wellen"),
                 (event(150,195,"R3.012"),"Felder und Wellen")]
        self.assertEqual(len(main.merge_lessons(lessons)),3)
    def test_prefer_short_room_codes(self):
        self.assertEqual(main.room_names([SimpleNamespace(name="R2.093",long_name="Raum 2.093")]),["R2.093"])
    def test_cancelled(self):
        self.assertTrue(main.cancelled(SimpleNamespace(code="cancelled")))
        self.assertFalse(main.cancelled(SimpleNamespace(code="",cancelled=False)))
    def test_line_width(self):
        for line in main.fold("DESCRIPTION:"+"Ä"*90).split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")),75)

if __name__=="__main__":
    unittest.main()
