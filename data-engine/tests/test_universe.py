"""The Telda universe gate and its seed file.

The gate itself is pure, so none of this needs a database.
"""

from datetime import datetime, timezone

import pytest

from egx_engine.cli import default_universe_file
from egx_engine.universe import (
    INSTRUMENT_NOT_REGISTERED,
    NOT_IN_TELDA_UNIVERSE,
    TELDA_AVAILABILITY_UNVERIFIED,
    TELDA_UNIVERSE_OK,
    UniverseError,
    check_universe,
    load_universe_csv,
)

VERIFIED_AT = datetime(2026, 3, 1, tzinfo=timezone.utc)

HEADER = (
    "instrument_id,ticker,name,asset_type,sector,telda_available,telda_verified_on\n"
)


def write(tmp_path, body, name="universe.csv"):
    path = tmp_path / name
    path.write_text(HEADER + body, encoding="utf-8")
    return path


# --- the gate ------------------------------------------------------------


def test_unregistered_instrument_is_refused():
    verdict = check_universe(None)
    assert verdict.ok is False
    assert verdict.reason == INSTRUMENT_NOT_REGISTERED


def test_registered_but_unavailable_is_refused():
    verdict = check_universe({"telda_available": False, "telda_verified_at": VERIFIED_AT})
    assert verdict.ok is False
    assert verdict.reason == NOT_IN_TELDA_UNIVERSE


def test_available_without_verification_is_refused():
    """Defence in depth behind the database CHECK constraint."""
    verdict = check_universe({"telda_available": True, "telda_verified_at": None})
    assert verdict.ok is False
    assert verdict.reason == TELDA_AVAILABILITY_UNVERIFIED


def test_missing_keys_are_refused_rather_than_assumed():
    verdict = check_universe({})
    assert verdict.ok is False
    assert verdict.reason == NOT_IN_TELDA_UNIVERSE


def test_verified_and_available_passes():
    verdict = check_universe({"telda_available": True, "telda_verified_at": VERIFIED_AT})
    assert verdict.ok is True
    assert verdict.reason == TELDA_UNIVERSE_OK


# --- the seed file -------------------------------------------------------


def test_shipped_universe_claims_no_availability():
    """The repository must never assert Telda membership nobody verified."""
    entries = load_universe_csv(default_universe_file())

    assert entries, "the shipped universe file should not be empty"
    assert all(not e.telda_available for e in entries)
    assert all(e.telda_verified_at is None for e in entries)
    assert all(check_universe(
        {"telda_available": e.telda_available, "telda_verified_at": e.telda_verified_at}
    ).ok is False for e in entries)


def test_a_verified_row_loads(tmp_path):
    path = write(tmp_path, "COMI,COMI,Commercial International Bank,EQUITY,Banks,true,2026-03-01\n")
    entry = load_universe_csv(path)[0]

    assert entry.instrument_id == "COMI"
    assert entry.telda_available is True
    assert entry.telda_verified_at == VERIFIED_AT
    assert entry.sector == "Banks"


def test_availability_without_a_date_is_rejected(tmp_path):
    path = write(tmp_path, "COMI,COMI,Bank,EQUITY,,true,\n")
    with pytest.raises(UniverseError, match="verified by a human"):
        load_universe_csv(path)


def test_unparseable_availability_is_rejected(tmp_path):
    path = write(tmp_path, "COMI,COMI,Bank,EQUITY,,maybe,\n")
    with pytest.raises(UniverseError, match="true or false"):
        load_universe_csv(path)


def test_bad_verification_date_is_rejected(tmp_path):
    path = write(tmp_path, "COMI,COMI,Bank,EQUITY,,true,01/03/2026\n")
    with pytest.raises(UniverseError, match="ISO date"):
        load_universe_csv(path)


def test_duplicate_instrument_id_is_rejected(tmp_path):
    path = write(
        tmp_path,
        "COMI,COMI,Bank,EQUITY,,false,\nCOMI,COMI2,Bank Again,EQUITY,,false,\n",
    )
    with pytest.raises(UniverseError, match="duplicate instrument_id"):
        load_universe_csv(path)


def test_incomplete_row_is_rejected(tmp_path):
    path = write(tmp_path, "COMI,,Bank,EQUITY,,false,\n")
    with pytest.raises(UniverseError, match="required"):
        load_universe_csv(path)


def test_missing_column_is_rejected(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("instrument_id,ticker,name\nCOMI,COMI,Bank\n", encoding="utf-8")
    with pytest.raises(UniverseError, match="missing column"):
        load_universe_csv(path)


def test_blank_lines_are_skipped(tmp_path):
    path = write(tmp_path, "COMI,COMI,Bank,EQUITY,,false,\n,,,,,,\n")
    assert len(load_universe_csv(path)) == 1


def test_empty_sector_becomes_null(tmp_path):
    path = write(tmp_path, "COMI,COMI,Bank,EQUITY,,false,\n")
    assert load_universe_csv(path)[0].sector is None


def test_unreadable_file_is_rejected(tmp_path):
    with pytest.raises(UniverseError, match="could not read"):
        load_universe_csv(tmp_path / "absent.csv")
