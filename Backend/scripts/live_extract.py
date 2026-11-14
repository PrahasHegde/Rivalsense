"""One opt-in live extraction through the same endpoint used by the frontend.

Run from the project root: python -m scripts.live_extract
This consumes Context.dev credits. It never prints raw SDK responses or credentials.
"""
import json
from fastapi.testclient import TestClient
from app.main import app

URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"


def main():
    with TestClient(app) as client:
        response = client.post("/api/prices/extract", json={"url": URL})
    print("Tested URL:", URL)
    print("HTTP status:", response.status_code)
    print(json.dumps(response.json(), indent=2))
    return 0 if response.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
