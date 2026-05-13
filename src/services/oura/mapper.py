"""
Maps Oura API response to DailyDataPoint dicts.

Rules:
- Always emits one entry per calendar day in [start, end].
- Missing fields are null, not omitted — the rule-engine handles nulls.
- sleep.average_hrv is used for HRV (more accurate than readiness.contributors.hrv_balance).
- latency / duration fields arrive in seconds from Oura; we convert to minutes.
# PRIVACY: only derived scalars are returned; raw Oura JSON is not persisted.
"""
from datetime import date, timedelta


def map_oura_to_daily_data_points(
    oura_response: dict,
    start: str,
    end: str,
) -> list[dict]:
    """
    Returns a list of DailyDataPoint dicts in chronological order.
    Always len == number of calendar days in [start, end].
    """
    sleep_by_day: dict[str, dict] = {
        s["day"]: s for s in oura_response.get("sleep", {}).get("data", [])
    }
    activity_by_day: dict[str, dict] = {
        a["day"]: a for a in oura_response.get("activity", {}).get("data", [])
    }
    temp_by_day: dict[str, dict] = {
        t["day"]: t for t in oura_response.get("temperature", {}).get("data", [])
    }

    points: list[dict] = []
    current = date.fromisoformat(start)
    end_date = date.fromisoformat(end)

    while current <= end_date:
        d = current.isoformat()
        sleep = sleep_by_day.get(d)
        activity = activity_by_day.get(d)
        temp = temp_by_day.get(d)

        latency_s = sleep.get("latency") if sleep else None
        deep_s = sleep.get("deep_sleep_duration") if sleep else None
        total_s = sleep.get("total_sleep_duration") if sleep else None

        points.append({
            "date": d,
            "hrv_ms": sleep.get("average_hrv") if sleep else None,
            "sleep_latency_min": latency_s / 60 if latency_s is not None else None,
            "deep_sleep_min":    deep_s / 60    if deep_s is not None    else None,
            "total_sleep_min":   total_s / 60   if total_s is not None   else None,
            "active_kcal":  activity.get("active_calories") if activity else None,
            "steps":        activity.get("steps")           if activity else None,
            "wrist_temp_deviation_c": temp.get("temperature_deviation") if temp else None,
        })
        current += timedelta(days=1)

    return points
