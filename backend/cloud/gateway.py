"""Supabase REST boundary. User clients and privileged job clients never mix."""
from __future__ import annotations
import os
from urllib.parse import quote
import httpx
from fastapi import HTTPException

class Gateway:
    def __init__(self, token: str | None = None, *, privileged: bool = False, transport=None):
        self.url = os.environ.get('SUPABASE_URL', '').rstrip('/')
        self.key = os.environ.get('SUPABASE_SECRET_KEY' if privileged else 'SUPABASE_PUBLISHABLE_KEY', '')
        if not self.url or not self.key:
            raise HTTPException(503, 'Cloud storage is not configured.')
        self.headers = {'apikey': self.key, 'Content-Type': 'application/json'}
        if token:
            self.headers['Authorization'] = f'Bearer {token}'
        elif privileged:
            # PostgREST reads the key from `apikey`, but the Auth admin endpoints
            # expect a bearer credential. Supabase permits the secret key in both
            # headers as long as the two values are identical, and a legacy
            # service-role JWT requires exactly this pairing, so send both.
            self.headers['Authorization'] = f'Bearer {self.key}'
        self.transport = transport

    async def request(self, method, path, *, body=None, params=None, headers=None):
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            r = await client.request(method, self.url+path, headers={**self.headers, **(headers or {})}, json=body, params=params)
        if r.is_error:
            # Never expose upstream messages, query strings, document data or tokens.
            if r.status_code in (401,403): raise HTTPException(401, 'Sign in again to continue.')
            if r.status_code == 404: raise HTTPException(404, 'This item was not found.')
            try: code = r.json().get('code')
            except ValueError: code = None
            if code == 'PT409': raise HTTPException(409, 'This plan changed in another tab. Reload before saving.')
            if code == 'PT429': raise HTTPException(429, 'Limit reached. Please try again later.')
            if code == 'PT404': raise HTTPException(404, 'This item was not found.')
            if code == 'PT422': raise HTTPException(422, 'The request is no longer valid. Refresh and try again.')
            raise HTTPException(502, 'The data service is unavailable. Your previous saved plan is unchanged.')
        return r.json() if r.content else None

    async def rpc(self, name, **args):
        return await self.request('POST', '/rest/v1/rpc/'+name, body=args)

    async def rows(self, table, **filters):
        return await self.request('GET','/rest/v1/'+table,params=filters)

    async def one(self, table, id, **filters):
        rows = await self.rows(table, id='eq.'+str(id), **filters)
        if not rows: raise HTTPException(404, 'This item was not found.')
        return rows[0]

    async def download(self, path: str) -> bytes:
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            async with client.stream('GET', self.url+'/storage/v1/object/authenticated/audit-uploads/'+quote(path, safe='/'), headers=self.headers) as r:
                if r.status_code != 200: raise ValueError('Upload is missing. Upload the report again.')
                data = bytearray()
                async for chunk in r.aiter_bytes():
                    data.extend(chunk)
                    if len(data)>25*1024*1024: raise ValueError('Document exceeds the 25 MB limit.')
                return bytes(data)

    async def remove_objects(self, paths):
        if paths: await self.request('DELETE', '/storage/v1/object/audit-uploads', body={'prefixes': paths})
