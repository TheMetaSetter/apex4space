"""Use a zero-price hosted model; keep exact data useful when it is unavailable."""
import os
import time

import httpx

_price_checked_until = 0.0
MODEL = 'nvidia/nemotron-3.5-lightning-free'


async def complete(messages, schema=None):
    global _price_checked_until
    if os.environ.get('FRISM_HOSTED_CHAT') != '1':
        raise ValueError('Hosted chat is off; use the exact database summary')
    token = os.environ.get('VERCEL_OIDC_TOKEN') or os.environ.get('AI_GATEWAY_API_KEY')
    if not token:
        raise ValueError('Hosted chat is not connected')
    async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
        if time.monotonic() >= _price_checked_until:
            catalog = await client.get('https://ai-gateway.vercel.sh/v1/models')
            catalog.raise_for_status()
            model = next((item for item in catalog.json()['data'] if item['id'] == MODEL), None)
            if model is None or any(float(model['pricing'][key]) != 0 for key in ('input', 'output')):
                raise ValueError('The model is no longer free')
            _price_checked_until = time.monotonic()+300
        payload = {'model': MODEL, 'messages': messages, 'max_tokens': 1000 if schema else 180}
        if schema:
            payload['response_format'] = {'type': 'json_schema', 'json_schema':
                {'name': 'data_intent', 'schema': schema, 'strict': True}}
        response = await client.post('https://ai-gateway.vercel.sh/v1/chat/completions',
            headers={'Authorization': f'Bearer {token}'}, json=payload)
        response.raise_for_status()
        answer = response.json()['choices'][0]['message']['content']
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError('The model returned no answer')
        return answer


def summary(data, question=''):
    totals = [str(item.get('total_cell_days', item.get('active_cell_count', 0))) for item in data]
    fact = ' and '.join(totals)+' cell-days.' if totals else 'Active cells show satellite fire detections.'
    title = 'A hotspot is a satellite detection of unusual heat.' if 'hotspot' in question.lower() else 'Selected database results.'
    if 'month' in question.lower() and len(data) == 1:
        months = data[0].get('monthly_counts', {})
        if months:
            peak = max(months, key=lambda month: (months[month], month))
            fact = f'{peak}: {months[peak]} cell-days, highest in this range.'
    return f'Summary: {title}\nKey fact: {fact}\nNote: Coverage is unknown. Active cells are not fire counts.'


def selected_summary(query, request, release_id):
    from app.insights import DataIntent, _chat_data
    if 'two ranges' in query.question.lower() and len(query.ranges) != 2:
        return {'answer': 'Summary: Choose two ranges in Compare.\nKey fact: Ranges may overlap.\nNote: Both ranges use the selected area.',
            'data': [], 'sources': [], 'available': False}
    kind = 'compare_ranges' if len(query.ranges) == 2 else 'range' if query.ranges else 'yearly' if query.years else 'general'
    intent = DataIntent(kind=kind, area_name=query.area_name, years=query.years)
    data, sources = _chat_data(intent, query, request, release_id)
    return {'answer': summary(data, query.question), 'data': data, 'sources': sources, 'available': False}
