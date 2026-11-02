"""Incrementally reduce an IOL JSON array to bounded daily closes."""
import asyncio
import codecs
from datetime import datetime
import json
import math

from chatbot.domain.market import MarketDataError


async def daily_closes(chunks):
    decoder = codecs.getincrementaldecoder('utf-8')()
    parser = json.JSONDecoder()
    buffer, state, total, records = '', 'start', 0, 0
    daily = {}
    try:
        async for chunk in chunks:
            total += len(chunk)
            if total > 64_000_000:
                raise MarketDataError('market_response_too_large')
            buffer += decoder.decode(chunk)
            while True:
                buffer = buffer.lstrip()
                if not buffer:
                    break
                if state == 'start':
                    if buffer[0] != '[':
                        raise ValueError()
                    buffer, state = buffer[1:], 'first'
                elif state in ('first', 'value'):
                    if state == 'first' and buffer[0] == ']':
                        buffer, state = buffer[1:], 'done'
                        continue
                    try:
                        row, end = parser.raw_decode(buffer)
                    except json.JSONDecodeError:
                        if len(buffer) > 128_000:
                            raise MarketDataError('market_response_too_large')
                        break
                    if not isinstance(row, dict):
                        raise ValueError()
                    stamp, price = row.get('fechaHora'), row.get('ultimoPrecio')
                    parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price):
                        raise ValueError()
                    day = parsed.date().isoformat()
                    if day not in daily or stamp > daily[day]['fechaHora']:
                        daily[day] = {'fechaHora': stamp, 'ultimoPrecio': price}
                    records += 1
                    if records % 256 == 0:
                        await asyncio.sleep(0)
                    if records > 100_000 or len(daily) > 750:
                        raise MarketDataError('market_response_too_large')
                    buffer, state = buffer[end:], 'separator'
                elif state == 'separator':
                    if buffer[0] == ',':
                        buffer, state = buffer[1:], 'value'
                    elif buffer[0] == ']':
                        buffer, state = buffer[1:], 'done'
                    else:
                        raise ValueError()
                else:
                    raise ValueError()  # Trailing content after the array.
        buffer += decoder.decode(b'', final=True)
        if state != 'done' or buffer.strip():
            raise ValueError()
    except (ValueError, TypeError, AttributeError, UnicodeError):
        raise MarketDataError('invalid_market_data') from None
    return [daily[day] for day in sorted(daily)]
