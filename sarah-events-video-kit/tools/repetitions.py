#!/usr/bin/env python3
# RÉPÉTITIONS (règle 32, l'auteur, 06/10/2026 : « tu as oublié la logique des répétitions, l'objectif c'est de rendre le reel fluide »).
# Liste, dans le texte d'un reel FINI (retranscription du final, pas du rush), ce qui se répète et alourdit :
#   - tics de langage : « tu vois », « en fait », « du coup », « encore une fois », « pareil », « voilà », « euh », « bah », « genre », « j'ai envie de dire » ;
#   - reprises : le même groupe de mots dit deux fois de suite (« il présente, il présente », « un tas de rendez-vous, un tas de rendez-vous ») ;
#   - un groupe de 3 mots ou plus qui revient à moins de 60 mots d'écart (idée redite, accroche redite au milieu).
# Ce n'est qu'une liste : chaque ligne se juge (une insistance voulue sur scène se garde ; un tic se retire s'il se coupe proprement).
#   python3 tools/repetitions.py <texte.txt | ecoute.json | cut.words.json> […]
import sys,json,re,unicodedata
TICS=["tu vois","en fait","du coup","encore une fois","pareil","voila","euh","bah","ben","genre","j ai envie de dire","entre guillemets","justement","tu sais","quoi"]
VIDES=set("le la les un une des de du d l a au aux et ou que qu qui ce c est en on il elle je tu vous nous ne n pas y se s son sa ses mon ma mes ton ta tes pour par sur dans avec plus tout tous".split())
def nz(t): return re.sub(r"[^a-z0-9]+"," ",''.join(c for c in unicodedata.normalize('NFD',t.lower()) if unicodedata.category(c)!='Mn')).split()
def texte(p):
    s=open(p,encoding='utf-8').read()
    try: d=json.loads(s)
    except Exception: return s
    if isinstance(d,dict) and 'final' in d: return d['final'].get('texte','')
    if isinstance(d,dict) and 'words' in d: return ' '.join((x.get('text') or x.get('t') or '') for x in d['words'])
    return d.get('texte',d.get('text','')) if isinstance(d,dict) else ' '.join(map(str,d))
def analyse(t):
    w=nz(t); s=' '+' '.join(w)+' '; out={'mots':len(w),'tics':{},'reprises':[],'redites':[]}
    for tic in TICS:
        n=len(re.findall(r'(?<= )'+re.escape(tic)+r'(?= )',s))
        if n and not (tic in ('pareil','justement','quoi','genre') and n<2): out['tics'][tic]=n
    for n in (4,3,2,1):                                   # reprises : même groupe de mots collé à lui-même
        for i in range(len(w)-2*n+1):
            if w[i:i+n]==w[i+n:i+2*n] and (n>1 or w[i] not in ('go','tres','non','oui')): 
                g=' '.join(w[i:i+n])
                if not any(g in r for r in out['reprises']): out['reprises'].append(g+' / '+g)
    vus={}
    for n in (5,4,3):                                     # redites : même groupe de 3 mots ou plus, à moins de 60 mots
        for i in range(len(w)-n+1):
            g=tuple(w[i:i+n])
            if sum(1 for x in g if x not in VIDES)<2: continue
            if g in vus and 0<i-vus[g]<=60 and i-vus[g]>=n:
                gs=' '.join(g)
                if not any(gs in r or r in gs for r in out['redites']) and not any(gs in r for r in out['reprises']): out['redites'].append(gs)
            vus[g]=i
    return out
if __name__=='__main__':
    for p in sys.argv[1:]:
        a=analyse(texte(p)); n=sum(a['tics'].values())+len(a['reprises'])+len(a['redites'])
        print(f"{p} — {a['mots']} mots ; {n} point(s) à juger"); 
        if a['tics']: print('   tics :',', '.join(f"« {k} » x{v}" for k,v in a['tics'].items()))
        if a['reprises']: print('   reprises :',' ; '.join(a['reprises']))
        if a['redites']: print('   redites :',' ; '.join(a['redites']))
