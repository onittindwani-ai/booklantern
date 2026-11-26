"""Fake QuickBooks Online API for tests and the demo. Written from Intuit's public material (UNVERIFIED against the real service).

OAuth: POST /oauth2/v1/tokens/bearer with Basic client auth (the real host is oauth.platform.intuit.com).
Data: /v3/company/{realmId}/... with a Bearer token and an optional minorversion query value. Access tokens last 3600 seconds.
"""

from __future__ import annotations

import base64
import secrets
from decimal import Decimal
from urllib.parse import parse_qsl

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse


class QboMock:
    def __init__(self, client_id: str = "mock-client", client_secret: str = "mock-secret", realm_id: str = "9130000000001"):
        self.client_id, self.client_secret, self.realm_id = client_id, client_secret, realm_id
        self.access = "mock-access-1"
        self.refresh = "mock-refresh-1"
        self.bills: dict[str, dict] = {}
        self.invoices: dict[str, dict] = {}
        self.expire_next = False
        self.minor_versions: list[str | None] = []
        self.app = self._build()

    def _build(self) -> FastAPI:
        app = FastAPI(title="QuickBooks mock")

        @app.post("/oauth2/v1/tokens/bearer")
        async def token(request: Request, authorization: str | None = Header(default=None)):
            want = "Basic " + base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            if authorization != want:
                return JSONResponse({"error": "invalid_client"}, 401)
            form = dict(parse_qsl((await request.body()).decode()))
            if form.get("grant_type") == "refresh_token":
                if form.get("refresh_token") != self.refresh:
                    return JSONResponse({"error": "invalid_grant"}, 400)
                self.refresh = "mock-refresh-" + secrets.token_hex(3)
            elif form.get("grant_type") != "authorization_code":
                return JSONResponse({"error": "unsupported_grant_type"}, 400)
            self.access = "mock-access-" + secrets.token_hex(3)
            return {"token_type": "bearer", "access_token": self.access, "refresh_token": self.refresh, "expires_in": 3600, "x_refresh_token_expires_in": 8726400}

        def auth(authorization: str | None):
            if self.expire_next:
                self.expire_next = False
                return JSONResponse({"fault": {"error": [{"message": "Token expired", "code": "3200"}], "type": "AUTHENTICATION"}}, 401)
            if authorization != f"Bearer {self.access}":
                return JSONResponse({"fault": {"error": [{"message": "AuthenticationFailed", "code": "3200"}], "type": "AUTHENTICATION"}}, 401)
            return None

        @app.get("/v3/company/{realm}/query")
        def query(realm: str, query: str, minorversion: str | None = None, authorization: str | None = Header(default=None)):
            bad = auth(authorization)
            if bad:
                return bad
            if realm != self.realm_id:
                return JSONResponse({"fault": {"error": [{"message": "Company not found"}]}}, 400)
            self.minor_versions.append(minorversion)
            q = query.lower()
            if "from bill" in q:
                return {"QueryResponse": {"Bill": list(self.bills.values())}}
            if "from invoice" in q:
                return {"QueryResponse": {"Invoice": list(self.invoices.values())}}
            return {"QueryResponse": {}}

        @app.post("/v3/company/{realm}/{entity}")
        async def create(realm: str, entity: str, request: Request, minorversion: str | None = None, authorization: str | None = Header(default=None)):
            bad = auth(authorization)
            if bad:
                return bad
            if entity not in ("bill", "invoice"):
                return JSONResponse({"fault": {"error": [{"message": "Unsupported entity"}]}}, 400)
            body = await request.json()
            if entity == "bill" and not (body.get("VendorRef") and body.get("Line")):
                return JSONResponse({"fault": {"error": [{"message": "VendorRef and Line are required", "code": "2020"}], "type": "ValidationFault"}}, 400)
            self.minor_versions.append(minorversion)
            store = self.bills if entity == "bill" else self.invoices
            new_id = str(len(store) + 100)
            total = sum(Decimal(str(x.get("Amount", 0))) for x in body.get("Line", [])) + Decimal(str((body.get("TxnTaxDetail") or {}).get("TotalTax", 0)))
            store[new_id] = {**body, "Id": new_id, "SyncToken": "0", "TotalAmt": float(total)}
            return {"Bill" if entity == "bill" else "Invoice": store[new_id], "time": "2026-12-01T09:00:00.000-08:00"}

        return app
