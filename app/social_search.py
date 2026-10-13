"""Search unverified Atlas social candidates without publishing vehicles."""
import os
import re
import unicodedata
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query

router=APIRouter()
STOP=set('quiero busco buscar necesito un una unos unas el la los las de del en para por con y o me mi carro carros auto autos vehiculo vehiculos usados usado guatemala guate salvador'.split())


def words(text):
    text=''.join(c for c in unicodedata.normalize('NFKD',str(text).lower()) if not unicodedata.combining(c))
    return set(re.findall(r'[a-z0-9]+',text))


def match_candidates(rows, query, country, limit=6):
    wanted=words(query)-STOP
    if not wanted:
        return []
    results=[];seen=set()
    for row in rows:
        if row.get('country','').upper()!=country or row.get('status') in {'rejected_non_vehicle','duplicate','sold','removed'}:
            continue
        url=row.get('url') or ''
        try:
            p=urlparse(url)
            if p.scheme!='https' or p.username or p.password or p.port:
                continue
        except ValueError:
            continue
        platform=row.get('platform')
        if platform=='tiktok':
            valid=p.hostname in {'www.tiktok.com','tiktok.com','m.tiktok.com'} and bool(re.fullmatch(r'/@[^/]+/video/\d+/?',p.path))
        elif platform=='instagram':
            valid=p.hostname in {'instagram.com','www.instagram.com'} and bool(re.fullmatch(r'/(p|reel)/[^/]+/?',p.path))
        elif platform=='facebook':
            valid=p.hostname in {'www.facebook.com','facebook.com','m.facebook.com','fb.com'} and any(x in p.path for x in ('/posts/','/marketplace/item/','/videos/','/reel/'))
        else:
            valid=False
        if not valid or url in seen:
            continue
        vehicle=row.get('vehicle') or {};card=row.get('vehicle_card') or {}
        fields=card.get('fields') or {}
        values={k:(fields.get(k) or {}).get('value') for k in ('make','model','year','price','currency')}
        for k in ('make','model','year'):
            if values[k] is None:
                values[k]=vehicle.get(k)
        text=' '.join(str(x or '') for x in [row.get('caption'),*values.values()])
        if not values['make'] or not wanted.issubset(words(text)):
            continue
        seen.add(url)
        results.append({'candidate_id':row.get('id'),'country':country,'platform':platform,'url':url,
                        **values,'label':'Publicación social · Pendiente de verificar',
                        'availability_verified':False,'inventory_eligible':False})
        if len(results)>=limit:
            break
    return results


async def search_social(query, country, limit=6):
    country=(country or '').upper()
    if country not in {'SV','GT'}:
        raise HTTPException(422,'Selecciona El Salvador o Guatemala.')
    base=os.getenv('ATLAS_SOCIAL_URL','').rstrip('/')
    try:
        p=urlparse(base)
        if p.scheme!='https' or not p.hostname or p.username or p.password or p.port or p.query or p.fragment:
            raise ValueError()
    except ValueError:
        return {'query':query,'country':country,'social_candidates':[],'social_status':'not_configured'}
    try:
        async with httpx.AsyncClient(timeout=5,follow_redirects=False) as client:
            r=await client.get(base+'/v1/social/candidates',params={'country':country})
            r.raise_for_status();rows=r.json()['candidates']
        results=match_candidates(rows,query,country,min(max(limit,1),12))
        return {'query':query,'country':country,'social_candidates':results,'social_status':'ok','count':len(results)}
    except (httpx.HTTPError,ValueError,KeyError,TypeError):
        return {'query':query,'country':country,'social_candidates':[],'social_status':'unavailable'}


@router.get('/carly/social-search')
async def social_search(q: str=Query(min_length=2,max_length=300),country: str='SV',limit: int=Query(default=6,ge=1,le=12)):
    return await search_social(q,country,limit)
