"""Fake Xero and Akaunting endpoints, written from memory of their public docs (UNVERIFIED: the doc pages could not be read when this was built)."""

from __future__ import annotations

import base64

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse


class XeroMock:
    """GET and POST /api.xro/2.0/Invoices with a Bearer token and an xero-tenant-id header. Type ACCPAY is a bill, ACCREC a sales invoice."""

    def __init__(self, token: str = "mock-xero-token", tenant: str = "mock-tenant-1"):
        self.token, self.tenant = token, tenant
        self.invoices: list[dict] = []
        self.app = FastAPI(title="Xero mock")

        @self.app.get("/api.xro/2.0/Invoices")
        def list_invoices(authorization: str | None = Header(default=None), xero_tenant_id: str | None = Header(default=None)):
            if authorization != f"Bearer {self.token}":
                return JSONResponse({"Title": "Unauthorized"}, 401)
            if xero_tenant_id != self.tenant:
                return JSONResponse({"Title": "Forbidden", "Detail": "AuthenticationUnsuccessful"}, 403)
            return {"Invoices": self.invoices}

        @self.app.post("/api.xro/2.0/Invoices")
        async def create(request: Request, authorization: str | None = Header(default=None), xero_tenant_id: str | None = Header(default=None)):
            if authorization != f"Bearer {self.token}":
                return JSONResponse({"Title": "Unauthorized"}, 401)
            if xero_tenant_id != self.tenant:
                return JSONResponse({"Title": "Forbidden"}, 403)
            body = await request.json()
            inv = {**body, "InvoiceID": f"mock-{len(self.invoices) + 1}", "Status": body.get("Status", "DRAFT")}
            self.invoices.append(inv)
            return {"Invoices": [inv]}


class AkauntingMock:
    """GET and POST /api/documents with Basic auth. type=bill or invoice."""

    def __init__(self, user: str = "owner@example.test", password: str = "mock-password"):
        self.cred = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        self.documents: list[dict] = []
        self.app = FastAPI(title="Akaunting mock")

        @self.app.get("/api/documents")
        def list_documents(type: str = "invoice", authorization: str | None = Header(default=None)):
            if authorization != self.cred:
                return JSONResponse({"message": "Unauthenticated."}, 401)
            return {"data": [d for d in self.documents if d.get("type") == type]}

        @self.app.post("/api/documents")
        async def create(request: Request, authorization: str | None = Header(default=None)):
            if authorization != self.cred:
                return JSONResponse({"message": "Unauthenticated."}, 401)
            body = await request.json()
            if not body.get("type") or not body.get("contact_id"):
                return JSONResponse({"message": "The given data was invalid."}, 422)
            doc = {**body, "id": len(self.documents) + 1, "status": "draft"}
            self.documents.append(doc)
            return {"data": doc}
