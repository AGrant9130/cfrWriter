from datetime import date, datetime

import pytest

from cfrwriter import formatting, logdata, settings as S
from conftest import EXAMPLE_LOG


# ---- log parsing ------------------------------------------------------------

def test_example_log_skips_aborts_and_sorts_newest_first():
    parsed = logdata.parse_log(EXAMPLE_LOG)
    assert len(parsed.entries) == 13
    assert parsed.skipped == 4
    assert parsed.entries[0].when == datetime(2026, 11, 4, 16, 28, 54)
    assert [e.when for e in parsed.entries] == sorted((e.when for e in parsed.entries), reverse=True)


def test_july_8_row_matches_the_example_report():
    e = next(e for e in logdata.parse_log(EXAMPLE_LOG).entries if e.when.date() == date(2026, 7, 8))
    assert (e.kind, e.capacitance_text, e.current_ma) == ("Profile", "2473", 200)
    assert (e.step_v, e.final_v, e.step_min, e.final_min) == (170, 680, 15, 30)


def test_bad_rows_and_bad_files():
    text = "Year, Month, Day, Hour, Minute, Second, Type, Result (uF), Volt Final (V), Volt Step (V), " \
           "Time Final (s), Time Step (s), Current (mA)\n2026, 1, 2, 3, 4, 5, Basic, 99, 680, 170, 30, 15, 200\n" \
           "garbage\n2026, 1, 2, 3, 4, 6, Basic, , 680, 170, 30, 15, 200\n"
    parsed = logdata.parse_log_text(text)
    assert len(parsed.entries) == 1 and parsed.skipped == 2
    with pytest.raises(logdata.LogFormatError):
        logdata.parse_log_text("a,b,c\n1,2,3\n")
    with pytest.raises(logdata.LogFormatError):
        logdata.parse_log_text("")


def test_find_latest_csv(tmp_path):
    old, new = tmp_path / "old.csv", tmp_path / "sub" / "NEW.CSV"
    new.parent.mkdir()
    old.write_text("x")
    new.write_text("x")
    import os
    os.utime(old, (1, 1))
    assert logdata.find_latest_csv([tmp_path]) == new
    assert logdata.find_latest_csv([tmp_path / "missing"]) is None


# ---- formatting -------------------------------------------------------------

def test_dates_and_minutes():
    d = date(2026, 7, 8)
    assert formatting.format_date(d, "MM/DD/YYYY") == "07/08/2026"
    assert formatting.format_date(d, "M/D/YYYY") == "7/8/2026"
    assert formatting.format_date(d, "DD/MM/YYYY") == "08/07/2026"
    assert formatting.format_date(d, "YYYY-MM-DD") == "2026-07-08"
    assert formatting.minutes_text(1) == "1 Minute" and formatting.minutes_text(15) == "15 Minutes"


@pytest.mark.parametrize("bad,expected", [("a/b:c*d", "a_b_c_d"), ("CON", "Unknown"), ("  ", "Unknown"),
                                          ("name. ", "name"), ("", "Unknown")])
def test_sanitize(bad, expected):
    assert formatting.sanitize_component(bad) == expected


def test_output_path_never_overwrites(tmp_path):
    vals = {"customer": "Acme/Motors", "date": "2026-07-08", "serial": "SN1"}
    p1 = formatting.build_output_path(str(tmp_path), "{customer}/{date}", "{customer}_{date}_{serial}", vals)
    assert p1 == tmp_path / "Acme_Motors" / "2026-07-08" / "Acme_Motors_2026-07-08_SN1.pdf"
    p1.parent.mkdir(parents=True)
    p1.write_text("x")
    p2 = formatting.build_output_path(str(tmp_path), "{customer}/{date}", "{customer}_{date}_{serial}", vals)
    assert p2.name.endswith("SN1 (2).pdf")


def test_output_path_blocks_traversal(tmp_path):
    vals = {"customer": "..", "date": "d", "serial": "s"}
    p = formatting.build_output_path(str(tmp_path), "{customer}/../x", "{customer}", vals)
    assert tmp_path in p.parents


# ---- settings ---------------------------------------------------------------

def test_settings_roundtrip_and_tolerant_load():
    s = S.Settings()
    s.company_name = S.InfoField("Acme", False)
    s.contacts = [S.Contact("A", "1", "a@x", "Eng", True), S.Contact("B", include=False)]
    S.save_settings(s)
    loaded = S.load_settings()
    assert loaded.company_name == S.InfoField("Acme", False)
    assert [c.name for c in loaded.contacts] == ["A", "B"] and loaded.contacts[1].include is False

    S.settings_path().write_text('{"paper": "Tabloid", "date_format": 5, "bogus": 1, "company_name": 7}')
    weird = S.load_settings()
    assert weird.paper == "Letter" and weird.date_format == "MM/DD/YYYY"
    S.settings_path().write_text("not json")
    assert S.load_settings().paper == "Letter"


def test_defaults_match_requirements():
    s = S.Settings()
    assert s.disclaimer.value.startswith("Reform capacitors") and s.footer_note.value == ""
    assert s.first_run_done is False


def test_bundle_roundtrip(tmp_path):
    s = S.Settings()
    s.user_name = S.InfoField("Pat", True)
    S.export_bundle(s, b"PNGDATA", tmp_path / "b.json")
    s2, logo = S.import_bundle(tmp_path / "b.json")
    assert s2.user_name.value == "Pat" and logo == b"PNGDATA"
    (tmp_path / "x.json").write_text("{}")
    with pytest.raises(ValueError):
        S.import_bundle(tmp_path / "x.json")
