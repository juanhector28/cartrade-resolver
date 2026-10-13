from app.social_search import match_candidates

def row(**kw):
    return {'id':'one','country':'GT','platform':'tiktok','url':'https://www.tiktok.com/@dealer/video/1','status':'parsed','caption':'Honda Civic 2020','vehicle':{'make':'Honda','model':'Civic','year':2020},**kw}

def test_brand_country_match_and_unverified_label():
    r=match_candidates([row()],'Honda en Guatemala','GT')
    assert len(r)==1 and not r[0]['inventory_eligible'] and not r[0]['availability_verified']

def test_model_and_year_must_match():
    assert not match_candidates([row()],'Honda Accord','GT')
    assert not match_candidates([row()],'Honda 2021','GT')

def test_rejected_empty_duplicate_and_other_country_excluded():
    assert not match_candidates([row(status='rejected_non_vehicle')],'Honda','GT')
    assert not match_candidates([row()],'Honda','SV')
    assert not match_candidates([row(vehicle={},caption='')],'Honda','GT')
    assert not match_candidates([row(status='duplicate')],'Honda','GT')

def test_profile_and_generic_queries_excluded():
    assert not match_candidates([row(url='https://www.tiktok.com/@dealer')],'Honda','GT')
    assert not match_candidates([row()],'carros usados','GT')

def test_dedupe_and_private_fields_not_exposed():
    r=match_candidates([row(seller={'phone':'private'}),row()],'Honda','GT')
    assert len(r)==1 and 'seller' not in r[0] and 'caption' not in r[0]
