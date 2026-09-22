from datetime import date

from pyedookit.parsers.dates import TIME_RE, find_days

TODAY = date(2026, 9, 22)


def test_date_without_year_uses_todays_year():
    assert find_days("28. 9.", TODAY) == [date(2026, 9, 28)]


def test_explicit_year_is_kept():
    assert find_days("29. 1. 2027", TODAY) == [date(2027, 1, 29)]


def test_range_with_year_only_on_the_end():
    assert find_days("od 23. 12. do 3. 1. 2027", TODAY) == [date(2026, 12, 23), date(2027, 1, 3)]


def test_thin_spaces_from_the_timetable():
    assert find_days("St 23. 9. 2026, 8:00 – 8:45", TODAY) == [date(2026, 9, 23)]


def test_relative_words():
    assert find_days("Včera , 8:00", TODAY) == [date(2026, 9, 21)]
    assert find_days("dnes", TODAY) == [TODAY]
    assert find_days("Zítra , 8:00", TODAY) == [date(2026, 9, 23)]


def test_invalid_date_is_skipped():
    assert find_days("31. 2.", TODAY) == []


def test_times_are_not_dates():
    assert find_days("od 13:30 do 15:30", TODAY) == []
    assert TIME_RE.findall("od 13:30 do 15:30") == [("13", "30"), ("15", "30")]
