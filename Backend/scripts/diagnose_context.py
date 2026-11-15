"""Safe local diagnostics. --live makes two bounded public Context.dev calls."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from context.dev import ContextDev, APIStatusError, APIConnectionError, APITimeoutError

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    values = dotenv_values(ROOT / ".env")
    file_key = values.get("CONTEXT_DEV_API_KEY") or ""
    key = os.getenv("CONTEXT_DEV_API_KEY") or file_key
    print(json.dumps({"sdk_version": importlib.metadata.version("context.dev"),
        "provider_key_present": bool(key.strip()),
        "process_key_overrides_file": bool(os.getenv("CONTEXT_DEV_API_KEY") and file_key and os.getenv("CONTEXT_DEV_API_KEY") != file_key),
        "backend_supabase_url_present": bool(os.getenv("SUPABASE_URL") or values.get("SUPABASE_URL")),
        "backend_publishable_key_present": bool(os.getenv("SUPABASE_PUBLISHABLE_KEY") or values.get("SUPABASE_PUBLISHABLE_KEY"))}))
    if not args.live or not key.strip():
        return 0 if key.strip() else 1
    evidence = {"retrieved_at": datetime.now(timezone.utc).isoformat(), "kind": "verified_live_provider_probe"}
    calls = [
        ("research", lambda client: client.web.answers(
            task="Who founded Microsoft and in what year? Use reliable sources and state uncertainty.",
            mode="fast", json_format={"answer": "", "keywords": [""], "facts": [{"label": "", "value": "", "source_url": ""}], "uncertainties": [""]},
            timeout_opts={"milliseconds": 30000, "behavior": "return-partial"}, zdr="disabled")),
        ("product", lambda client: client.web.scrape(
            url="https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
            formats={"product": True}, product_params={"dedupe_images": False}, max_age_ms=0,
            timeout_opts={"milliseconds": 55000, "behavior": "return-partial"}, zdr="disabled"))
    ]
    for name, operation in calls:
        try:
            with ContextDev(api_key=key.strip(), timeout=65, max_retries=0) as client:
                result = operation(client)
            if name == "research":
                evidence[name] = {"question": "Who founded Microsoft and in what year?",
                    "json_content": result.json_content, "sources": result.sources, "partial": result.partial}
                print(json.dumps({"probe": name, "status": "success", "source_count": len(result.sources),
                                  "answer_present": bool(result.json_content.get("answer"))}))
            else:
                product = getattr(getattr(getattr(result, "product", None), "data", None), "product", None)
                evidence[name] = {"source_url": result.url,
                    "product": {field: getattr(product, field, None) for field in ("name","price","currency","brand","sku","availability")}}
                print(json.dumps({"probe": name, "status": "success", "product_present": product is not None}))
        except APIStatusError as exc:
            # Do not print raw messages, headers, body, URLs containing credentials, or key metadata.
            body = getattr(exc, "body", None)
            error = body.get("error") if isinstance(body, dict) else None
            code = (error.get("code") if isinstance(error, dict) else None) or (body.get("code") if isinstance(body, dict) else None)
            evidence[name] = {"status": "provider_error", "http_status": exc.status_code, "code": str(code)[:80] if code and key not in str(code) else None}
            print(json.dumps({"probe": name, **evidence[name]}))
        except (APIConnectionError, APITimeoutError) as exc:
            evidence[name] = {"status": "network_error", "error_class": type(exc).__name__}
            print(json.dumps({"probe": name, **evidence[name]}))
    (ROOT / "demo-evidence.local").write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

if __name__ == "__main__":
    main()
