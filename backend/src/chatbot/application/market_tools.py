"""Per-invocation tool state. No credentials or conversation state in the provider."""
import asyncio
from copy import deepcopy
import json
import logging
from time import monotonic
from uuid import uuid4

from chatbot.application.tools import Tool, ToolRegistry
from chatbot.domain.agent import ToolDefinition
from chatbot.domain.market import MarketData, MarketDataError
from chatbot.domain.presentation import ChartResult

logger = logging.getLogger('chatbot')
KINDS = ['acciones', 'cedears', 'titulosPublicos', 'obligacionesNegociables', 'letras']
HISTORY_COMPARABILITY_WARNING = (
    'The historical series has a large price discontinuity and comparability is unverified. '
    'A split, another corporate action, a genuine market move or a provider error may cause this; '
    'the price ratio alone does not establish the cause. Do not calculate a period change, '
    'describe an investment loss or draw a chart from this series. Base 100 does not correct splits. '
    'Do not reuse earlier unverified figures or infer an adjustment factor. '
    'Explain that a verified adjusted series is needed, or offer a period that avoids the discontinuity.'
)


def check_history_comparability(points):
    """Conservative quality gate, never an automatic split detector or price correction."""
    if any(point['close'] <= 0 for point in points):
        raise MarketDataError('invalid_market_data')
    ordered = sorted(points, key=lambda point: point['date'])
    for previous, current in zip(ordered, ordered[1:]):
        ratio = current['close'] / previous['close']
        # A twofold change between consecutive observations needs verification.
        # This may reject a genuine move; it must never silently rescale prices.
        if ratio <= 0.5 or ratio >= 2:
            raise MarketDataError('history_comparability_unverified')


def schema(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def text(limit):
    return {'type': 'string', 'minLength': 1, 'maxLength': limit}


def market_tools(provider: MarketData) -> ToolRegistry:
    series = {}
    chart_count = 0

    def safe(name, handler):
        async def execute(**arguments):
            started, status = monotonic(), 'ok'
            try:
                return await handler(**arguments)
            except asyncio.CancelledError:
                status = "cancelled"
                raise
            except MarketDataError as error:
                status = error.code
                return {'error': error.code, 'source': 'IOL',
                        'instruction': (HISTORY_COMPARABILITY_WARNING if error.code == 'history_comparability_unverified'
                                        else 'Explain missing data honestly; do not invent prices or silently use another instrument.')}
            finally:
                logger.info(json.dumps({'event': 'market_tool_finished', 'tool': name, 'status': status,
                                        'duration_ms': round((monotonic() - started) * 1000, 2)}))
        return execute

    async def search_instruments(query, kind):
        return {'instruments': await provider.search(query, kind), 'source': 'IOL',
                'coverage': 'Argentina only. CEDEARs are local instruments, not US listings.'}

    async def get_quote(instrument_id):
        return await provider.quote(instrument_id)

    async def get_price_history(instrument_id, start, end):
        data = await provider.history(instrument_id, start, end)
        points = data['points']
        check_history_comparability(points)
        if len(series) >= 8:
            raise MarketDataError('series_limit')
        identifier = 'series_' + uuid4().hex
        series[identifier] = deepcopy(data)
        return {**{key: value for key, value in data.items() if key != 'points'},
                'series_id': identifier, 'count': len(points), 'first': points[0], 'last': points[-1],
                'min': min(p['close'] for p in points), 'max': max(p['close'] for p in points),
                'chart_hint': 'Use show_chart with this series_id; do not supply or invent price points.'}

    async def show_chart(series_ids, title, comparison):
        nonlocal chart_count
        if chart_count >= 2:
            raise MarketDataError('chart_limit')
        if len(set(series_ids)) != len(series_ids) or any(key not in series for key in series_ids):
            raise MarketDataError('unknown_series_reference')
        values = [deepcopy(series[key]) for key in series_ids]
        if comparison == 'absolute' and (any(not s.get('currency') for s in values)
                                         or len({s['currency'] for s in values}) != 1):
            raise MarketDataError('incompatible_chart_currencies')
        if comparison == 'base_100':
            dates = set.intersection(*[{p['date'] for p in s['points']} for s in values])
            if not dates:
                raise MarketDataError('no_common_trading_dates')
            first = min(dates)
            for value in values:
                base = next(p['close'] for p in value['points'] if p['date'] == first)
                if base <= 0:
                    raise MarketDataError('invalid_base_price')
                value['points'] = [{'date': p['date'], 'close': round(p['close'] / base * 100, 6)}
                                   for p in value['points'] if p['date'] in dates]
        identifier = 'chart_' + uuid4().hex
        chart_count += 1
        block = {'type': 'chart', 'id': identifier, 'title': title, 'comparison': comparison,
                 'series': values, 'note': 'Price evolution only; excludes coupons/dividends and FX conversion.'}
        return ChartResult({'status': 'created', 'chart_id': identifier,
                            'note': block['note']}, block)

    definitions = [
        ('search_instruments', 'Search Argentine IOL instruments by ticker or name. Choose kind explicitly; clarify ambiguous instruments. US listings are not supported here.',
         schema({'query': text(80), 'kind': {'type': 'string', 'enum': KINDS}}), search_instruments),
        ('get_quote', 'Get the last reported IOL price, currency, timestamp and settlement for an instrument_id returned by search. May be stale; do not label it live.',
         schema({'instrument_id': text(64)}), get_quote),
        ('get_price_history', 'Get daily unadjusted historical closes (up to two years), a summary and a series_id for charting. Large price discontinuities return history_comparability_unverified instead of figures or a chart reference; never infer an investment loss or rescale such prices. ISO dates YYYY-MM-DD; end date is exclusive (until today gives completed prior sessions). History settlement is provider-default; T0 history is unavailable.',
         schema({'instrument_id': text(64), 'start': text(10), 'end': text(10)}), get_price_history),
        ('show_chart', 'Display a line chart inline here using series_ids retrieved in THIS turn. Useful for evolution/comparisons even without explicit chart request. Base 100 compares relative prices on common dates, not total returns or FX-adjusted returns. Never invent series IDs.',
         schema({'series_ids': {'type': 'array', 'items': text(64), 'minItems': 1, 'maxItems': 3},
                 'title': text(120), 'comparison': {'type': 'string', 'enum': ['absolute', 'base_100']}}), show_chart),
    ]
    return ToolRegistry(Tool(ToolDefinition(name, description, parameters), safe(name, handler))
                        for name, description, parameters, handler in definitions)
