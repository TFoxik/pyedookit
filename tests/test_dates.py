from datetime import date

from pyedookit.parsers.dates import TIME_RE, find_days, resolve_day

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


def test_resolve_day_keeps_an_explicit_year():
    assert resolve_day("8. 1. 2026", date(2026, 11, 22), near=date(2026, 12, 18)) == date(
        2026, 1, 8
    )


def test_resolve_day_not_before_uses_its_year():
    assert resolve_day("do 20. 11.", date(2026, 11, 22), not_before=date(2026, 11, 2)) == date(
        2026, 11, 20
    )


def test_resolve_day_not_before_rolls_into_next_year():
    assert resolve_day("8. 1., 8:00", date(2026, 12, 20), not_before=date(2026, 12, 18)) == date(
        2027, 1, 8
    )


def test_resolve_day_near_keeps_a_day_just_before_it():
    assert resolve_day("22. 11.", date(2027, 5, 30), near=date(2026, 11, 24)) == date(2026, 11, 22)


def test_resolve_day_defaults_to_nearest_today():
    assert resolve_day("30. 12.", date(2027, 1, 3)) == date(2026, 12, 30)
