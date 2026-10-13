"""Official TikTok oEmbed metadata; never fetch arbitrary social pages."""
from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx


async def recover_metadata(url: str, platform: str) -> dict:
    if platform != 'tiktok':
        return {'metadata_status':'provider_not_connected'}
    p=urlparse(url)
    if p.scheme != 'https' or p.hostname not in {'tiktok.com','www.tiktok.com','m.tiktok.com'} or p.username or p.password or p.port or not re.fullmatch(r'/@[A-Za-z0-9_.]+/video/[0-9]+/?',p.path):
        return {'metadata_status':'canonical_video_link_required'}
    try:
        async with httpx.AsyncClient(timeout=6,follow_redirects=False) as client:
            async with client.stream('GET','https://www.tiktok.com/oembed',params={'url':url}) as response:
                response.raise_for_status()
                if 'json' not in response.headers.get('content-type',''):
                    raise ValueError('unexpected content type')
                raw=bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw)>65536:
                        raise ValueError('metadata too large')
        import json
        data=json.loads(raw)
        if data.get('type') != 'video' or data.get('provider_name') != 'TikTok':
            raise ValueError('not TikTok video metadata')
        title=data.get('title')
        if not isinstance(title,str):
            title=''
        thumb=data.get('thumbnail_url')
        photos=[]
        if isinstance(thumb,str):
            image=urlparse(thumb)
            if image.scheme=='https' and image.hostname and not image.username and not image.password and not image.port:
                photos=[thumb]
        return {'title':title[:3000],'media_urls':photos,'metadata_status':'recovered',
                'metadata_provider':'tiktok_oembed','media_kind':'video_thumbnail'}
    except (httpx.HTTPError,ValueError,TypeError,AttributeError):
        return {'metadata_status':'unavailable'}
