"""Serve the React bundle without allowing SPA fallback to hide API errors."""
from pathlib import PurePosixPath
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles


class ReactStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        normalized = PurePosixPath(path.replace("\\", "/").lstrip("/"))
        parts = normalized.parts
        if (parts and parts[0] == "api") or any(part.startswith(".") for part in parts):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            response = None
        # Extensionless browser routes may return index.html. Missing assets must
        # stay 404 instead of returning HTML where JavaScript/JSON is expected.
        if (response is None or response.status_code == 404) and not normalized.suffix:
            return await super().get_response("index.html", scope)
        return response if response is not None else JSONResponse({"detail": "Not Found"}, status_code=404)
