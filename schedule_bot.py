
import os
import json
import re
import sys
import hashlib
from pathlib import Path
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

CONFIG = Path("config.json")
HISTORY = Path("schedule_history.json")
WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]

DAYS = [
    "Monday", "Tuesday", "Wednesday",
    "Thursday", "Friday", "Saturday", "Sunday"
]

EMOJIS = ["🟢", "🔵", "🟣", "🟠",
          "🔴", "🟡", "⚪"]

HEADERS = {
    "User-Agent": "WarlineScheduleBot/1.0"
}


def read_json(path, default):
    if not path.exists():
        return default
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def save_json(path, data):
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def fetch_page(url):
    response = requests.get(
        url, headers=HEADERS, timeout=25
    )
    response.raise_for_status()

    soup = BeautifulSoup(
        response.text, "html.parser"
    )

    # Avoid extracting navigation and scripts.
    for tag in soup([
        "script", "style", "nav", "footer"
    ]):
        tag.decompose()

    return soup


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def get_vs_schedule(soup):
    """
    Read the published daily VS objectives table.
    """
    schedule = {}

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])

            if len(cells) < 2:
                continue

            day_text = clean(
                cells[0].get_text(" ", strip=True)
            )

            day = next(
                (
                    d for d in DAYS
                    if re.search(
                        r"\b" + d + r"\b",
                        day_text,
                        re.IGNORECASE
                    )
                ),
                None
            )

            if not day:
                continue

            objective_cell = cells[1]

            items = [
                clean(li.get_text(" ", strip=True))
                for li in objective_cell.find_all("li")
            ]

            if not items:
                items = [
                    clean(x)
                    for x in objective_cell.stripped_strings
                ]

            items = [x for x in items if x]

            if items:
                schedule[day] = items

    if len(schedule) != 7:
        raise ValueError(
            "Could not extract all 7 VS days. "
            "Website format may have changed."
        )

    return schedule


def check_source(soup, required):
    text = clean(soup.get_text(" ", strip=True))
    lower = text.lower()

    for phrase in required:
        if phrase.lower() not in lower:
            raise ValueError(
                "Expected source information missing: "
                + phrase
            )

    return text


def get_sources(config):
    sources = config["sources"]
    pages = {}

    for name, url in sources.items():
        print("Checking:", name, url)
        pages[name] = fetch_page(url)

    vs = get_vs_schedule(pages["daily_vs"])

    arms_text = check_source(
        pages["daily_vs"],
        ["Arms Race", "4 hours", "00:00"]
    )

    frost_text = check_source(
        pages["frostfall"],
        ["Friday", "09:00", "18:00", "23:00"]
    )

    sand_text = check_source(
        pages["sandstrike"],
        ["Saturday", "04:00", "11:00", "21:00"]
    )

    exercise_text = check_source(
        pages["alliance_exercises"],
        ["48 hours"]
    )

    # These are source-verified recurring windows,
    # not server-specific confirmed bookings.
    return {
        "vs": vs,
        "arms": arms_text,
        "frost": frost_text,
        "sand": sand_text,
        "exercises": exercise_text,
        "urls": sources
    }


def next_week():
    today = datetime.now(timezone.utc).date()

    # Always select the upcoming Monday.
    days_until = (7 - today.weekday()) % 7
    if days_until == 0:
        days_until = 7

    return today + timedelta(days=days_until)


def build_embeds(data, monday, config):
    sunday = monday + timedelta(days=6)
    week = monday.isocalendar().week

    fields = []

    for index, day in enumerate(DAYS):
        date = monday + timedelta(days=index)

        objectives = data["vs"][day]

        # Keep the objectives readable in Discord.
        lines = [
            "• " + objective
            for objective in objectives
        ]

        value = "\n".join(lines)

        if len(value) > 1024:
            raise ValueError(
                f"VS objectives too long for {day}"
            )

        fields.append({
            "name": (
                f"{EMOJIS[index]} "
                f"{day.upper()} • {date:%d %b}"
            ),
            "value": value,
            "inline": False
        })

    first_embed = {
        "title": "📅 WARLINE WEEKLY SCHEDULE",
        "description": (
            f"⚔️ **Week {week}**\n"
            f"📆 {monday:%d %B} – "
            f"{sunday:%d %B %Y}\n\n"
            "**Daily VS objectives**\n"
            "Plan upgrades and resources "
            "to maximize your rewards."
        ),
        "color": 3447003,
        "fields": fields,
        "footer": {
            "text": (
                "Warline Alliance • "
                "Source: The ArchAngels"
            )
        }
    }

    second_embed = {
        "title": "⚔️ WEEKLY EVENT INFORMATION",
        "description": (
            "**🏁 Arms Race – Daily**\n"
            "Mission changes every 4 hours "
            "from 00:00 UTC through 20:00 UTC. "
            "Mission order varies; check in-game.\n\n"

            "**❄️ Frostfall – Friday**\n"
            "Sign-up: Monday–Thursday.\n"
            "Possible battle slots (UTC):\n"
            "09:00–09:30\n"
            "18:00–18:30\n"
            "23:00–23:30\n"
            "Your alliance must confirm its slot.\n\n"

            "**🏜️ Sandstrike – Saturday**\n"
            "Published matchmaking windows (UTC):\n"
            "04:00–05:00\n"
            "11:00–12:00\n"
            "21:00–22:00\n\n"

            "**🛡️ Alliance Exercises**\n"
            "Approximately once every 48 hours "
            "when eligible. Leadership chooses "
            "the start time.\n\n"

            "⚠️ These are recurring guide "
            "schedules, not live confirmation "
            "of events on your server."
        ),
        "color": 15844367,
        "fields": [
            {
                "name": "📚 Event Guides",
                "value": (
                    "[Daily VS & Arms Race]("
                    + data["urls"]["daily_vs"] + ")\n"
                    "[Frostfall]("
                    + data["urls"]["frostfall"] + ")\n"
                    "[Sandstrike]("
                    + data["urls"]["sandstrike"] + ")\n"
                    "[Alliance Exercises]("
                    + data["urls"]["alliance_exercises"]
                    + ")"
                )
            }
        ],
        "footer": {
            "text": (
                "All event times UTC • "
                "Verify current availability in-game"
            )
        }
    }

    notes = config.get("manual_notes", [])
    if notes:
        second_embed["fields"].append({
            "name": "📢 Alliance Notes",
            "value": "\n".join(
                "• " + str(note) for note in notes
            )[:1024]
        })

    return [first_embed, second_embed]


def send_discord(embeds, config):
    notify = config.get(
        "notification", "none"
    )

    if notify == "everyone":
        content = "@everyone"
        allowed = {"parse": ["everyone"]}
    else:
        content = ""
        allowed = {"parse": []}

    payload = {
        "username": "Warline Schedule Bot",
        "content": content,
        "allowed_mentions": allowed,
        "embeds": embeds
    }

    response = requests.post(
        WEBHOOK + (
            "&wait=true" if "?" in WEBHOOK
            else "?wait=true"
        ),
        json=payload,
        timeout=30
    )

    response.raise_for_status()
    print("Schedule posted to Discord.")


def main():
    config = read_json(CONFIG, {})
    history = read_json(
        HISTORY, {"posted_weeks": []}
    )

    monday = next_week()
    week_key = monday.isoformat()

    if week_key in history["posted_weeks"]:
        print("Already posted:", week_key)
        return

    data = get_sources(config)
    embeds = build_embeds(
        data, monday, config
    )

    send_discord(embeds, config)

    history["posted_weeks"].append(week_key)
    history["posted_weeks"] = sorted(
        set(history["posted_weeks"])
    )

    save_json(HISTORY, history)
    print("Completed:", week_key)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("ERROR:", error)
        sys.exit(1)
