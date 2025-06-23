"""Event helpers for Peloton integration."""

from homeassistant.core import HomeAssistant

from .const import DOMAIN


def fire_exercise_complete_event(
    hass: HomeAssistant,
    entry_id: str,
    workout_stats_summary: dict,
    user_profile: dict,
    workout_stats_detail: dict,
) -> None:
    """Fire an exercise_complete event when a workout is complete."""
    workout_stats_summary_id = workout_stats_summary["id"]

    # Extract title
    title = (
        workout_stats_summary.get("ride", {}).get("title")
        if workout_stats_summary.get("ride")
        else None
    )

    # Extract calories from summaries
    calories = None
    for summary in workout_stats_detail.get("summaries", []):
        if summary.get("slug") in ("total_calories", "calories"):
            calories = summary.get("value")
            break

    # Extract duration (seconds)
    start_time = workout_stats_summary.get("start_time")
    end_time = workout_stats_summary.get("end_time")
    duration = (
        end_time - start_time
        if end_time is not None and start_time is not None
        else None
    )

    # Extract distance
    distance = None
    distance_unit = None
    for summary in workout_stats_detail.get("summaries", []):
        if summary.get("slug") == "distance":
            distance = summary.get("value")
            distance_unit = summary.get("display_unit")
            break

    hass.bus.async_fire(
        "exercise_complete",
        {
            "entry_id": entry_id,
            "workout_id": workout_stats_summary_id,
            "user_id": workout_stats_summary.get("user_id"),
            "username": user_profile.get("username"),
            "start_time": start_time,
            "end_time": end_time,
            "duration_seconds": duration,
            "calories": calories,
            "type": workout_stats_summary.get("fitness_discipline"),
            "title": title,
            "distance": distance,
            "distance_unit": distance_unit,
            "domain": DOMAIN,
        },
    )
