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
    def test_cancelled(self):
        self.assertTrue(main.cancelled(SimpleNamespace(code="cancelled")))
        self.assertFalse(main.cancelled(SimpleNamespace(code="",cancelled=False)))
    def test_line_width(self):
        for line in main.fold("DESCRIPTION:"+"Ä"*90).split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")),75)

if __name__=="__main__":
    unittest.main()
