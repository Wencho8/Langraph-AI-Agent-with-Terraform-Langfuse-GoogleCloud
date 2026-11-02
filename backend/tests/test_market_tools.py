"""Offline market/graph tests; no live credentials, provider calls or extra containers."""
import asyncio
import json
from time import monotonic
from urllib.parse import parse_qs

import httpx
import pytest

from chatbot.adapters.outbound.market_data.iol import IolMarketData
from chatbot.application.market_tools import market_tools
from chatbot.domain.agent import ToolCall
from chatbot.domain.market import MarketDataError


class FixtureMarket:
    async def search(self, query, kind):
        return [{'instrument_id': 'bCBA:AL30:t1', 'symbol': 'AL30'}]

    async def quote(self, instrument_id):
        return {'price': 100, 'currency': 'ARS', 'source': 'fixture'}

    async def history(self, instrument_id, start, end):
        return {'instrument_id': instrument_id, 'symbol': instrument_id, 'market': 'bCBA',
                'currency': 'USD' if 'GD30' in instrument_id else 'ARS', 'source': 'fixture',
                'start': start, 'end': end, 'as_of': end, 'adjustment': 'unadjusted',
                'settlement': 'provider_default',
                'points': [{'date': start, 'close': 10}, {'date': end, 'close': 12}]}


async def invoke(tools, name, **args):
    return json.loads(await tools.execute(ToolCall('call', name, json.dumps(args))))


async def test_chart_references_are_isolated_and_chart_uses_backend_points():
    tools, other = market_tools(FixtureMarket()), market_tools(FixtureMarket())
    result = await invoke(tools, 'get_price_history', instrument_id='bCBA:AL30:t1', start='2026-01-01', end='2026-02-01')
    assert 'points' not in result and result['count'] == 2
    arguments = {'series_ids': [result['series_id']], 'title': 'Evolución', 'comparison': 'base_100'}
    assert (await invoke(other, 'show_chart', **arguments))['error'] == 'unknown_series_reference'
    chart = await invoke(tools, 'show_chart', **arguments)
    assert chart['status'] == 'created'
    block = tools.take_events()[0].block
    assert [point['close'] for point in block['series'][0]['points']] == [100, 120]
    assert not tools.take_events()
    await invoke(tools, 'show_chart', **arguments)
    assert (await invoke(tools, 'show_chart', **arguments))['error'] == 'chart_limit'


async def test_mixed_currency_prices_rejected_but_relative_chart_allowed():
    tools = market_tools(FixtureMarket())
    ids = []
    for ticker in ('AL30', 'GD30'):
        result = await invoke(tools, 'get_price_history', instrument_id=f'bCBA:{ticker}:t1', start='2026-01-01', end='2026-02-01')
        ids.append(result['series_id'])
    args = {'series_ids': ids, 'title': 'Comparación'}
    assert (await invoke(tools, 'show_chart', comparison='absolute', **args))['error'] == 'incompatible_chart_currencies'
    assert (await invoke(tools, 'show_chart', comparison='base_100', **args))['status'] == 'created'


async def test_expected_provider_failure_is_visible_to_model_without_secret_details():
    class Unavailable(FixtureMarket):
        async def quote(self, instrument_id):
            raise MarketDataError('market_rate_limited')
    result = await invoke(market_tools(Unavailable()), 'get_quote', instrument_id='bCBA:AL30:t1')
    assert result['error'] == 'market_rate_limited'
    assert 'price' not in result


@pytest.mark.parametrize('prices', [(53.90, 5.35, 5.08), (81400, 8105, 7865), (10, 100, 102)])
async def test_large_discontinuities_never_reach_a_chart_or_comparison_summary(prices):
    class Discontinuous(FixtureMarket):
        async def history(self, instrument_id, start, end):
            data = await super().history(instrument_id, start, end)
            data['points'] = [dict(date=day, close=price) for day, price in zip(
                ('2026-07-30', '2026-08-03', '2026-10-29'), prices)]
            return data

    tools = market_tools(Discontinuous())
    result = await invoke(tools, 'get_price_history', instrument_id='bCBA:YPFDD:t1',
                          start='2026-07-30', end='2026-10-30')
    assert result['error'] == 'history_comparability_unverified'
    assert 'Do not calculate a period change' in result['instruction']
    assert not {'series_id', 'first', 'last', 'min', 'max', 'points'}.intersection(result)
    assert not tools.take_events()
    assert (await invoke(tools, 'show_chart', series_ids=['invented'], title='YPF',
                         comparison='base_100'))['error'] == 'unknown_series_reference'


async def test_quality_gate_preserves_ordinary_prices_without_rescaling():
    from chatbot.application.market_tools import check_history_comparability
    points = [{'date': '2026-08-05', 'close': 5.39}, {'date': '2026-10-29', 'close': 5.08}]
    original = [dict(point) for point in points]
    check_history_comparability(points)
    assert points == original


async def test_iol_native_async_auth_refresh_cache_and_read_only_endpoints():
    grants, reads = [], []
    async def handle(request):
        await asyncio.sleep(0)  # The client transport is asynchronous.
        if request.url.path == '/token':
            grants.append(parse_qs(request.content.decode())['grant_type'][0])
            return httpx.Response(200, json={'access_token': 'access', 'refresh_token': 'refresh', 'expires_in': 1200})
        assert request.method == 'GET'
        assert '/Titulos/AL30/Cotizacion' == request.url.path.removeprefix('/api/v2/bCBA')
        reads.append(request)
        return httpx.Response(200, json={'ultimoPrecio': 100, 'moneda': 'peso_Argentino', 'fechaHora': '2026-01-01T15:00:00-03:00'})
    provider = IolMarketData('fixture-user', 'fixture-password', client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    try:
        results = await asyncio.gather(provider.quote('bCBA:AL30:t1'), provider.quote('bCBA:AL30:t1'))
        assert all(row['price'] == 100 for row in results)
        assert grants == ['password']  # Concurrent requests share one login.
        await provider.quote('bCBA:AL30:t1')
        assert len(reads) == 2
        provider._expires = 0
        provider._cache.clear()
        await provider.quote('bCBA:AL30:t1')
        assert grants == ['password', 'refresh_token']
        with pytest.raises(MarketDataError):
            await provider.quote('https://another.invalid/anything')
    finally:
        await provider.close()


async def test_history_sorts_daily_closes_preserves_missing_dates_and_rejects_future():
    async def handle(request):
        if request.url.path == '/token':
            return httpx.Response(200, json={'access_token': 'access', 'expires_in': 1200})
        if '/seriehistorica/' in request.url.path:
            return httpx.Response(200, json=[
                {'fechaHora': '2026-01-05T17:00:00-03:00', 'ultimoPrecio': 12},
                {'fechaHora': '2026-01-02T11:00:00-03:00', 'ultimoPrecio': 9},
                {'fechaHora': '2026-01-02T17:00:00-03:00', 'ultimoPrecio': 10}])
        return httpx.Response(200, json={'moneda': 'peso_Argentino'})
    provider = IolMarketData('user', 'pass', client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    try:
        history = await provider.history('bCBA:AL30:t1', '2026-01-01', '2026-01-06')
        assert history['points'] == [{'date': '2026-01-02', 'close': 10}, {'date': '2026-01-05', 'close': 12}]
        with pytest.raises(MarketDataError):
            await provider.history('bCBA:AL30:t1', '2099-01-01', '2099-02-01')
        with pytest.raises(MarketDataError):
            await provider.history('bCBA:AL30:t0', '2026-01-01', '2026-01-06')
    finally:
        await provider.close()


async def test_iol_http_errors_never_echo_broker_response():
    async def handle(request):
        return httpx.Response(403, json={'message': 'sensitive provider response'})
    provider = IolMarketData('private-user', 'private-password', client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    try:
        with pytest.raises(MarketDataError) as failure:
            await provider.quote('bCBA:AL30:t1')
        assert str(failure.value) == 'market_authentication'
    finally:
        await provider.close()


async def test_graph_can_call_tools_repeatedly_and_emit_chart_between_text_blocks():
    from chatbot.adapters.outbound.agent.graph import LangGraphAgent
    from chatbot.domain.agent import AgentCompleted, AgentRequest, ChatHistory, ModelCompleted, ModelItem, TextDelta
    from chatbot.domain.models import UserProfile
    from chatbot.domain.presentation import ChartReady
    from chatbot.prompts.loader import load_prompt
    from uuid import uuid4

    class Model:
        provider, name = 'fixture', 'fixture'
        def __init__(self): self.calls = 0
        async def stream(self, request):
            self.calls += 1
            if self.calls == 1:
                call = ToolCall('history', 'get_price_history', json.dumps({'instrument_id': 'bCBA:AL30:t1', 'start': '2026-01-01', 'end': '2026-02-01'}))
                yield ModelCompleted('', (), (call,))
            elif self.calls == 2:
                result = json.loads(request.items[-1].data['output'])
                yield TextDelta('Mirá la evolución.\n\n')
                call = ToolCall('chart', 'show_chart', json.dumps({'series_ids': [result['series_id']], 'title': 'AL30', 'comparison': 'absolute'}))
                yield ModelCompleted('Mirá la evolución.\n\n', (), (call,))
            else:
                yield TextDelta('Estos son precios sin ajustar.')
                yield ModelCompleted('Estos son precios sin ajustar.', (), ())
    async def check(): pass
    graph = LangGraphAgent(Model(), prompt=load_prompt(), tools_factory=lambda: market_tools(FixtureMarket()))
    events = [event async for event in graph.stream(AgentRequest(UserProfile(uuid4()), ChatHistory((), ()), monotonic() + 10, check))]
    assert any(isinstance(event, ChartReady) for event in events)
    done = events[-1]
    assert isinstance(done, AgentCompleted)
    assert [block['type'] for block in done.blocks] == ['text', 'chart', 'text']
    assert done.metadata['model_calls'] == 3 and done.metadata['tool_calls'] == 2
    assert done.text == 'Mirá la evolución.\n\nEstos son precios sin ajustar.'


async def test_openai_high_reasoning_is_forwarded_to_responses_api():
    from tests.fakes import OpenAIHarness, response_events
    from chatbot.domain.agent import ModelRequest
    harness = OpenAIHarness(lambda body: response_events('Answer'))
    harness.model.reasoning_effort = 'high'
    try:
        _ = [event async for event in harness.model.stream(ModelRequest('finance', None, (), ()))]
        assert harness.requests[0]['reasoning'] == {'effort': 'high'}
    finally:
        await harness.model.close()


def test_iol_settings_require_credentials_and_do_not_expose_them_in_repr():
    from chatbot.config import Settings
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Settings(database_url='postgresql+asyncpg://unused', market_data_provider='iol', iol_credentials='bad-json')
    settings = Settings(database_url='postgresql+asyncpg://unused', market_data_provider='iol',
                        iol_credentials=json.dumps({'username': 'private-user', 'password': 'private-password'}))
    assert 'private-user' not in repr(settings) and 'private-password' not in repr(settings)


async def test_real_iol_panel_codes_and_uppercase_settlement_are_normalized():
    async def handle(request):
        if request.url.path == '/token':
            return httpx.Response(200, json={'access_token': 'access', 'expires_in': 1200})
        if '/Cotizaciones/' in request.url.path:
            return httpx.Response(200, json={'titulos': [
                {'simbolo': 'AL30', 'descripcion': 'Bono', 'mercado': '1', 'moneda': '1', 'plazo': 'T1'},
                {'simbolo': 'AL30D', 'descripcion': 'Bono USD', 'mercado': '1', 'moneda': '2', 'plazo': 'T1'},
                {'simbolo': 'UNKNOWN', 'mercado': '9', 'moneda': '9', 'plazo': 'T1'}]})
        assert request.url.params.get('plazo') == 't1'
        assert 'model.plazo' not in request.url.params
        return httpx.Response(200, json={'ultimoPrecio': 100, 'moneda': 'peso_Argentino', 'plazo': 'T1'})
    provider = IolMarketData('user', 'pass', client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    try:
        found = await provider.search('AL30', 'titulosPublicos')
        assert [row['instrument_id'] for row in found] == ['bCBA:AL30:t1', 'bCBA:AL30D:t1']
        assert [row['currency'] for row in found] == ['ARS', 'USD']
        assert (await provider.quote(found[0]['instrument_id']))['settlement'] == 't1'
    finally:
        await provider.close()


async def test_large_intraday_history_is_streamed_and_reduced_without_losing_daily_close():
    from chatbot.adapters.outbound.market_data.history_stream import daily_closes
    rows = [{'fechaHora': f'2026-10-29T15:{minute:02}:00', 'ultimoPrecio': minute,
             'unused': 'x' * 5000} for minute in range(60)]
    payload = json.dumps(rows).encode()
    async def chunks():
        for offset in range(0, len(payload), 1021):
            await asyncio.sleep(0)
            yield payload[offset:offset + 1021]
    assert await daily_closes(chunks()) == [{'fechaHora': '2026-10-29T15:59:00', 'ultimoPrecio': 59}]


@pytest.mark.parametrize('payload', [b'[{', b'[{},]', b'[]trailing', b'{}'])
async def test_history_stream_rejects_truncated_or_invalid_data(payload):
    from chatbot.adapters.outbound.market_data.history_stream import daily_closes
    async def chunks(): yield payload
    with pytest.raises(MarketDataError):
        await daily_closes(chunks())
