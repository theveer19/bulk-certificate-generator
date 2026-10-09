"""Generate a large request payload for load-testing the bulk endpoint.

Usage::

    python scripts/make_bulk_request.py 500 > samples/bulk_500.json
    curl -X POST http://localhost:8000/api/v1/jobs \
         -H "Content-Type: application/json" \
         -d @samples/bulk_500.json
"""

import json
import sys

FIRST = [
    "Aarav", "Diya", "Rohan", "Ananya", "Kabir", "Meera", "Arjun", "Ishita",
    "Vivaan", "Saanvi", "Aditya", "Riya", "Kartik", "Nisha", "Dhruv", "Tara",
]
LAST = [
    "Sharma", "Patel", "Verma", "Iyer", "Singh", "Nair", "Reddy", "Bose",
    "Joshi", "Kulkarni", "Gupta", "Menon", "Chauhan", "Desai", "Rao", "Mehta",
]


def build(count: int) -> dict:
    recipients = []
    for i in range(count):
        first = FIRST[i % len(FIRST)]
        last = LAST[(i // len(FIRST)) % len(LAST)]
        recipients.append(
            {
                "name": f"{first} {last}",
                "email": f"{first.lower()}.{last.lower()}{i}@example.com",
            }
        )
    return {
        "title": "Advanced Python Workshop 2026",
        "issue_date": "2026-10-09",
        "recipients": recipients,
    }


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    json.dump(build(count), sys.stdout, indent=2)
    sys.stdout.write("\n")
