"""UTC timestamps stored and returned with a Z suffix."""

from datetime import UTC, datetime, timedelta


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def shift_minutes(moment: datetime, minutes: int) -> datetime:
    return moment + timedelta(minutes=minutes)


def shift_seconds(moment: datetime, seconds: int) -> datetime:
    return moment + timedelta(seconds=seconds)


def shift_days(moment: datetime, days: int) -> datetime:
    return moment + timedelta(days=days)
