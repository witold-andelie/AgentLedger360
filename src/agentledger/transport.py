"""One HTTP client for both demo modes.

- single laptop: URLs like inproc://platform/... are served by in-process ASGI apps (no ports, no firewall)
- two laptops:   real URLs like http://192.168.1.20:8001/... go over the LAN
"""

from __future__ import annotations

import warnings
from typing import Any

import httpx
from fastapi import FastAPI

# Newer Starlette nudges TestClient users towards `httpx2`; plain httpx still works on 3.11 and 3.13.
warnings.filterwarnings("ignore", message=r"Using .httpx. with .starlette\.testclient. is deprecated")
from fastapi.testclient import TestClient  # noqa: E402

INPROC = "inproc://"


class Router:
    def __init__(self, timeout: float = 30.0) -> None:
        self._apps: dict[str, TestClient] = {}
        self._http = httpx.Client(timeout=timeout)

    def mount(self, name: str, app: FastAPI) -> str:
        self._apps[name] = TestClient(app)
        return f"{INPROC}{name}"

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if url.startswith(INPROC):
            name, _, path = url[len(INPROC):].partition("/")
            return self._apps[name].request(method, "/" + path, **kwargs)
        return self._http.request(method, url, **kwargs)

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)
