#!/usr/bin/env python3
import json, os, sys, time, urllib.request
BASE=os.environ.get('CARLY_URL','').rstrip('/')
if not BASE: sys.exit('Set CARLY_URL')
F=[]
def chat(msgs,shown=None):
 b=json.dumps({'messages':[{'role':'user','content':m} if isinstance(m,str) else m for m in msgs],'country':'gt','top_n':30,'shown_cars':shown or []}).encode(); r=urllib.request.Request(BASE+'/carly/chat',data=b,headers={'Content-Type':'application/json'}); t=time.time()
 with urllib.request.urlopen(r,timeout=30) as x: d=json.loads(x.read().decode())
 return d,time.time()-t
def names(d): return [f"{r.get('make','?')} {r.get('model','?')}" for r in d.get('recommendations') or []]
def ck(n,ok,x=''):
 print(('PASS' if ok else 'FAIL'),n,x)
 if not ok:F.append(n)
# Toyota x5
R=[]
for i in range(5):
 d,t=chat(['Busco un Toyota SUV para mi familia, cuota hasta 450 al mes']); R.append((names(d),round(t,2),d.get('token_path') or d.get('route_precedence'))); print('toyota',i+1,R[-1])
ck('toyota_x5_same_top',len({tuple(x[0]) for x in R})==1)
ck('toyota_x5_latency_band',max(x[1] for x in R)-min(x[1] for x in R)<1.0,f"spread={max(x[1] for x in R)-min(x[1] for x in R):.2f}s")
ck('toyota_x5_same_path',len({x[2] for x in R})==1)
# Range
D,_=chat(['Busco un SUV confiable entre USD 15,000 y 25,000 para trabajo diario']); P=[r.get('price_usd') for r in D.get('recommendations') or [] if r.get('price_usd') is not None]
ck('range_has_results',bool(P)); ck('range_floor',all(p>=15000 for p in P),f"min={min(P) if P else None}"); ck('range_ceiling',all(p<=25000 for p in P),f"max={max(P) if P else None}")
# Bugatti x3
B=[]
for _ in range(3):
 d,_=chat(['Busco un Bugatti Chiron 2025 en Guatemala']); B.append((d.get('reply',''),len(d.get('recommendations') or []),d.get('route_precedence')))
ck('bugatti_zero_recs',all(x[1]==0 for x in B),str([x[1] for x in B])); ck('bugatti_deterministic',len({x[0] for x in B})==1); ck('bugatti_honest_wording',all('no tengo' in x[0].lower() for x in B))
# Prior regressions
D,_=chat(['Busco algo para uso familiar, cuota de 400']); ck('no_familia_de_cinco','familia de cinco' not in D.get('reply','').lower())
D,_=chat(['Toyota Corolla',{'role':'assistant','content':'ok'},'Mejor cualquier Toyota, es para trabajo, cuota 450']); N=names(D); ck('scope_released',not N or any('corolla' not in n.lower() for n in N),str(N))
D,_=chat([{'role':'user','content':'¿Cuánto manejo al día? [CONTEXTO ACTIVO DE CARTRADE: radio=100km]'}]); ck('radius_not_buyer_fact','100 km diarios' not in D.get('reply','').lower())
# Shortlist followups
D0,_=chat(['Busco un Toyota SUV para mi familia, cuota hasta 450 al mes']); S=(D0.get('recommendations') or [])+(D0.get('explore') or []); C=['Busco un Toyota SUV para mi familia, cuota hasta 450 al mes',{'role':'assistant','content':D0.get('reply','ok')}]
if not S:F.append('guion_context_unavailable')
else:
 L=f"{S[0].get('make','')} {S[0].get('model','')}".strip()
 D,_=chat(C+[f'¿Qué opinas del {L}?'],S); ck('unit_question_not_rebuilt',bool(D.get('route_precedence') or D.get('token_path')) or len(D.get('recommendations') or [])==0); ck('unit_question_has_substance',len(D.get('reply',''))>80)
 D,_=chat(C+[f'¿Pros y contras del modelo {L}?'],S); q=D.get('reply','').lower(); bad=any(w in q for w in ('vin','vendedor','inspección','este anuncio')); ck('model_question_no_unit_leak',not bad); ck('model_question_has_substance',len(D.get('reply',''))>80)
 D,_=chat(C+[f'¿Es buena compra el {L}?'],S); q=D.get('reply','').lower(); ck('buy_decision_verdicts',any(w in q for w in ('sí','si te','no te','recomiendo','buena','conviene','veredicto','evitar','adelante'))); ck('buy_decision_not_pure_checklist',q.count('verific')+q.count('checklist')<4)
 D,_=chat(C+['Muéstrame más opciones'],S); new=names(D); seen={f"{r.get('make','?')} {r.get('model','?')}" for r in S}; fresh=[n for n in new if n not in seen]; ex=any(w in D.get('reply','').lower() for w in ('no tengo más','no hay más','agot')); ck('more_options_fresh_or_honest',bool(fresh) or ex,f"fresh={len(fresh)} exhausted={ex}")
print('FAILS',F)
sys.exit(1 if F else 0)
