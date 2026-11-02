"""Read-only IOL v2 market adapter. No account or trading endpoints are exposed."""
import asyncio
from collections import OrderedDict
from copy import deepcopy
from datetime import date, datetime, timezone
import json
import math
import re
from time import monotonic

import httpx

from chatbot.domain.market import MarketDataError
from .history_stream import daily_closes

KINDS = ('acciones', 'cedears', 'titulosPublicos', 'obligacionesNegociables', 'letras')


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise MarketDataError('invalid_market_data')
    return value


def instrument_parts(identifier):
    match = re.fullmatch(r'(bCBA):([A-Z0-9][A-Z0-9.-]{0,24}):(t[01])', identifier)
    if not match:
        raise MarketDataError('unsupported_instrument')
    return match.groups()


def currency(value):
    return {'1': 'ARS', '2': 'USD', 'peso_argentino': 'ARS', 'dolar_estadounidense': 'USD',
            'ars': 'ARS', 'usd': 'USD'}.get(str(value).casefold())


def settlement_value(value):
    normalized = str(value).casefold()
    return normalized if normalized in ('t0', 't1') else None


def market_value(value):
    return 'bCBA' if str(value).casefold() in ('1', 'bcba') else None


class IolMarketData:
    def __init__(self, username, password, *, client=None, timeout=8):
        self.username, self.password = username, password
        self.client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False)
        self._auth_lock = asyncio.Lock()
        self._access, self._refresh, self._expires = None, None, 0
        self._cache = OrderedDict()

    async def close(self):
        await self.client.aclose()
        self._access = self._refresh = None
        self._cache.clear()

    async def _request(self, method, path, **kwargs):
        try:
            async with self.client.stream(method, 'https://api.invertironline.com' + path, **kwargs) as response:
                if response.status_code == 200 and '/seriehistorica/' in path:
                    return response.status_code, await daily_closes(response.aiter_bytes())
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 2_000_000:
                        raise MarketDataError('market_response_too_large')
                try:
                    data = json.loads(body)
                except (ValueError, UnicodeError):
                    data = None
                return response.status_code, data
        except httpx.TimeoutException:
            raise MarketDataError('market_timeout') from None
        except httpx.HTTPError:
            raise MarketDataError('market_unavailable') from None

    async def _token(self):
        async with self._auth_lock:
            if self._access and monotonic() < self._expires:
                return self._access
            credentials = ({'refresh_token': self._refresh, 'grant_type': 'refresh_token'} if self._refresh
                           else {'username': self.username, 'password': self.password, 'grant_type': 'password'})
            status, data = await self._request('POST', '/token', data=credentials)
            if status == 400 and self._refresh:
                self._refresh = None
                status, data = await self._request('POST', '/token', data={
                    'username': self.username, 'password': self.password, 'grant_type': 'password'})
            if status != 200 or not isinstance(data, dict) or not isinstance(data.get('access_token'), str):
                raise MarketDataError('market_authentication')
            expiry = data.get('expires_in', 0)
            if not isinstance(expiry, (int, float)) or expiry <= 0:
                raise MarketDataError('invalid_market_data')
            self._access, self._refresh = data['access_token'], data.get('refresh_token')
            self._expires = monotonic() + max(0, expiry - 30)
            return self._access

    async def _get(self, path, *, params=None, ttl=30):
        key = (path, tuple(sorted((params or {}).items())))
        cached = self._cache.get(key)
        if cached and monotonic() < cached[0]:
            self._cache.move_to_end(key)
            return deepcopy(cached[1])
        for attempt in range(2):
            token = await self._token()
            status, data = await self._request('GET', path, params=params, headers={'Authorization': 'Bearer ' + token})
            if status != 401 or attempt:
                break
            async with self._auth_lock:
                if self._access == token:
                    self._expires = 0
        if status != 200:
            code = {400: 'invalid_market_arguments', 401: 'market_authentication', 403: 'market_access_denied', 404: 'instrument_not_found',
                    429: 'market_rate_limited'}.get(status, 'market_unavailable')
            raise MarketDataError(code)
        if data is None:
            raise MarketDataError('invalid_market_data')
        self._cache[key] = (monotonic() + ttl, deepcopy(data))
        self._cache.move_to_end(key)
        while len(self._cache) > 64:
            self._cache.popitem(last=False)
        return data

    async def search(self, query, kind):
        if kind not in KINDS or not 1 <= len(query.strip()) <= 80:
            raise MarketDataError('invalid_market_arguments')
        data = await self._get(f'/api/v2/Cotizaciones/{kind}/argentina/Todos', ttl=300)
        rows = data.get('titulos') if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise MarketDataError('invalid_market_data')
        result, query = [], query.casefold().strip()
        for row in rows:
            if not isinstance(row, dict):
                continue
            ticker, description = row.get('simbolo', ''), row.get('descripcion', '')
            if not isinstance(ticker, str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9.-]{0,24}', ticker):
                continue
            if query not in (ticker + ' ' + str(description)).casefold():
                continue
            if market_value(row.get('mercado')) != 'bCBA':
                continue
            settlement = settlement_value(row.get('plazo'))
            if settlement not in ('t0', 't1'):
                continue
            result.append({'instrument_id': f'bCBA:{ticker}:{settlement}', 'symbol': ticker,
                           'name': str(description)[:160], 'market': 'bCBA', 'kind': kind,
                           'currency': currency(row.get('moneda')), 'settlement': settlement, 'source': 'IOL'})
            if len(result) == 20:
                break
        return result

    async def quote(self, instrument_id):
        market, symbol, settlement = instrument_parts(instrument_id)
        data = await self._get(f'/api/v2/{market}/Titulos/{symbol}/Cotizacion', params={'plazo': settlement})
        if not isinstance(data, dict):
            raise MarketDataError('invalid_market_data')
        reported_settlement = settlement_value(data.get('plazo'))
        if reported_settlement is not None and reported_settlement != settlement:
            raise MarketDataError('quote_settlement_unavailable')
        return {'instrument_id': instrument_id, 'symbol': symbol, 'market': market, 'settlement': reported_settlement,
                'requested_settlement': settlement,
                'price': number(data.get('ultimoPrecio')), 'currency': currency(data.get('moneda')),
                'minimum_denomination': data.get('laminaMinima'), 'lot_size': data.get('lote'),
                'as_of': data.get('fechaHora'), 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                'source': 'IOL', 'note': 'Last reported price; may be delayed or from a previous trading session.'}

    async def history(self, instrument_id, start, end):
        market, symbol, settlement = instrument_parts(instrument_id)
        if not all(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in (start, end)):
            raise MarketDataError("invalid_date_range")
        try:
            first, last = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError:
            raise MarketDataError('invalid_date_range') from None
        if first > last or (last - first).days > 730 or last > date.today():
            raise MarketDataError('invalid_date_range')
        # Historical endpoint has no settlement selector. Do not imply a T0 series.
        if settlement != 't1':
            raise MarketDataError('history_settlement_unavailable')
        data = await self._get(f'/api/v2/{market}/Titulos/{symbol}/Cotizacion/seriehistorica/{start}/{end}/sinAjustar', ttl=300)
        if not isinstance(data, list) or len(data) > 10_000:
            raise MarketDataError('invalid_market_data')
        daily = {}
        for row in data:
            if not isinstance(row, dict):
                raise MarketDataError('invalid_market_data')
            stamp = row.get('fechaHora')
            try:
                parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            except (ValueError, TypeError, AttributeError):
                raise MarketDataError('invalid_market_data') from None
            day = parsed.date().isoformat()
            if start <= day <= end:
                previous = daily.get(day)
                if previous is None or stamp > previous[0]:
                    daily[day] = (stamp, number(row.get('ultimoPrecio')))
        if not daily:
            raise MarketDataError('no_market_history')
        if len(daily) > 750:
            raise MarketDataError('market_response_too_large')
        info = await self._get(f'/api/v2/{market}/Titulos/{symbol}', ttl=300)
        if not isinstance(info, dict):
            raise MarketDataError('invalid_market_data')
        return {'instrument_id': instrument_id, 'symbol': symbol, 'market': market,
                'currency': currency(info.get('moneda')), 'source': 'IOL', 'start': start, 'end': end,
                'adjustment': 'unadjusted', 'settlement': 'provider_default', 'end_exclusive': True,
                'as_of': max(value[0] for value in daily.values()),
                'points': [{'date': day, 'close': value[1]} for day, value in sorted(daily.items())]}
