#!/usr/bin/env python3
# DÉRUSH MOT À MOT d'un rush parlé long (conférence, séance, module) — règle de l'auteur du 03/10/2026 :
# « trop de blancs, des coupes pas faites » ne doit plus arriver. Ce script :
#   - retire les mots listés (hésitations, reprises, apartés, consignes de régie « tu peux enchaîner ») ;
#   - resserre CHAQUE blanc entre deux mots gardés à une pause naturelle (fin de phrase / virgule / milieu) ;
#   - pose les coupes dans le calme réel du son (enveloppe large bande), bornées par les mots, jamais au hasard ;
#   - signale les sons non transcrits qu'il retire (« euh » étiré, bruit) pour la réécoute.
# Dossier de travail (argument, ou variable DERUSH_DIR, ou dossier du script) contenant :
#   all.json     [[début, fin, "mot"], …]  (Scribe ; voir words-concat.mjs ; {words:[{text,start,end}]} accepté)
#   audio.wav    le son du rush (sert à calculer envw.npy la première fois)
#   derush.json  {"plages":[[début,fin]…] ce qu'on garde en gros, "retirer":[[temps approx, "mots exacts"]…],
#                 "pause":{"fin":0.32,"virgule":0.24,"milieu":0.16}, "seuil":0.5, "retrait_min":0.2, "images_min":5,
#                 "son_continu_min":0.45, "creux_min_dB":-99, "morceau_min_images":10}
# Sortie : derush.out.json {segs:[[image début, image fin, coupe de fin de phrase ?]…], log:[…], mots:[indices gardés]}
# Comme module : import derush_mots as DR ; keep,opt=DR.load_keep() ; segs,log,idx=DR.build(keep,opt[,début,fin])
# Ensuite : assembler le son en fondus enchaînés de 30 ms à chaque coupe, puis passer le FINAL dans tools/reecoute.py.
import json,sys,os,wave,numpy as np
from scipy.ndimage import percentile_filter
FPS=int(os.environ.get('DERUSH_FPS','25')); HOP=0.01
D=os.environ.get('DERUSH_DIR') or (sys.argv[1] if __name__=='__main__' and len(sys.argv)>1 and os.path.isdir(sys.argv[1]) else os.path.dirname(os.path.abspath(__file__)))
W=json.load(open(D+'/all.json')); CFG=json.load(open(D+'/derush.json'))
if isinstance(W,dict): W=[[w['start'],w['end'],w['text']] for w in W['words']]
if not os.path.exists(D+'/envw.npy'):
    from scipy.signal import butter,sosfiltfilt
    wv=wave.open(D+'/audio.wav'); sr=wv.getframerate(); x=np.frombuffer(wv.readframes(wv.getnframes()),dtype=np.int16).reshape(-1,wv.getnchannels()).mean(1)/32768
    y=sosfiltfilt(butter(4,[150,min(9000,sr/2-100)],btype='band',fs=sr,output='sos'),x); hop=int(sr*0.01); win=int(sr*0.03)
    c=np.cumsum(np.concatenate([[0],y*y])); ii=np.arange(0,len(y)-win,hop); np.save(D+'/envw.npy',10*np.log10((c[ii+win]-c[ii])/win+1e-12))
env=np.load(D+'/envw.npy')
for k,v in {"pause":{"fin":0.32,"virgule":0.24,"milieu":0.16},"seuil":0.5,"retrait_min":0.2,"images_min":5,"son_continu_min":0.45,"creux_min_dB":-99,"morceau_min_images":10,"retirer":[]}.items(): CFG.setdefault(k,v)
dec=env[::10]; fl=percentile_filter(dec,8,size=200,mode='nearest'); sp=percentile_filter(dec,85,size=200,mode='nearest')
thr=np.repeat(fl+CFG['seuil']*(sp-fl),10)[:len(env)]; thr=np.pad(thr,(0,len(env)-len(thr)),mode='edge')
calm=env<thr
N=len(env); ix=lambda t:min(N-1,max(0,int(round((t-0.015)/HOP)))); tm=lambda k:k*HOP+0.015
def target(txt):
    t=txt.rstrip('»" ')
    return CFG['pause']['fin'] if t[-1:] in '.?!…' else CFG['pause']['virgule'] if t[-1:] in ',:;—' else CFG['pause']['milieu']
def is_end(txt): return txt.rstrip('»" ')[-1:] in '.?!…'
def calm_from(t0,t1,n=6):
    """premier instant ≥ t0 où le son reste calme n pas de suite (avant t1)"""
    a,b=ix(t0),ix(t1)
    for k in range(a,max(a,b-n)+1):
        if calm[k:k+n].all(): return tm(k)
    return None
def calm_until(t0,t1,n=6):
    """dernier instant ≤ t1 où le son était calme n pas de suite (après t0)"""
    a,b=ix(t0),ix(t1)
    for k in range(b,min(b,a+n)-1,-1):
        if k-n>=0 and calm[k-n:k].all(): return tm(k)
    return None
def argmin_env(t0,t1):
    a=ix(t0); b=max(a+1,ix(t1)); k=a+int(np.argmin(env[a:b])); return tm(k),float(env[k])
def junction(a,b):
    """entre le mot gardé a et le mot gardé suivant b (b = a+1 : blanc ; sinon : mots retirés entre les deux).
    Sortie cherchée juste après le mot a, entrée juste avant le mot b ; ce qui est entre les deux part,
    y compris un son non transcrit (« euh » étiré, bruit de salle) : ces cas sont signalés (son_retire)."""
    sa,ea,ta=W[a]; sb,eb,tb=W[b]; tg=target(ta); tail=0.55*tg; lead=0.45*tg
    nxt=W[a+1][0]; prv=W[b-1][1]
    info={'type':'blanc' if b==a+1 else 'retrait','avant':ta,'apres':tb,'phrase':is_end(ta)}
    if b>a+1: info['texte']=' '.join(x[2] for x in W[a+1:b])
    te=calm_from(max(ea-0.22,sa+0.4*(ea-sa)),min(ea+0.30,nxt+0.12))     # Scribe finit souvent les mots un peu tard
    if te is not None: out=max(te,ea-0.20)+tail
    else:
        o,lv=argmin_env(ea-0.02,max(ea+0.04,min(ea+0.15,nxt+0.10))); out=o; info['creux_sortie_dB']=round(float(np.median(env[ix(sa):ix(ea)+1])-lv),1)
    ts=calm_until(max(sb-0.30,prv-0.12),sb+0.15)
    if ts is not None: inn=min(ts,sb+0.08)-lead
    else:
        i,lv=argmin_env(max(sb-0.20,prv-0.10),sb+0.02); inn=i; info['creux_entree_dB']=round(float(np.median(env[ix(sb):ix(eb)+1])-lv),1)
    if b==a+1:
        if inn-out<CFG['retrait_min'] or (ts is None or te is None) and sb-ea<CFG['son_continu_min']: return None
    else:
        # 06/10/2026 (mots alignés MMS) : un mot retiré dit tout bas (« bah », fin de « justement ») passe pour du calme ;
        # la coupe couvre donc au moins les mots retirés, de leur début à leur fin.
        out=min(out,max(ea,W[a+1][0]-0.01)); inn=max(inn,min(sb,W[b-1][1]+0.01))
    if inn<out: out=inn=(inn+out)/2
    k0,k1=ix(out),ix(inn)
    if k1>k0:
        loud=float(np.mean(~calm[k0:k1]))*(inn-out)
        if loud>=0.25: info['son_retire']=round(loud,2)
    return out,inn,info
def segments(idx,optional=()):
    """idx : indices des mots gardés dans l'ordre → (morceaux [image début, image fin, coupe de fin de phrase ?], journal, mots réintégrés)"""
    idx=list(idx); rem=[]; log=[]; back=[]
    for a,b in zip(idx,idx[1:]):
        j=junction(a,b)
        if j is None: continue
        out,inn,info=j
        if info['type']=='retrait' and min(info.get('creux_sortie_dB',99),info.get('creux_entree_dB',99))<CFG['creux_min_dB'] and (a+1,b-1) in optional:
            info['abandon']='mots collés, coupe à risque : laissé'; log.append(info); back+=list(range(a+1,b)); continue
        fo=int(np.ceil(out*FPS)); fi=int(np.floor(inn*FPS))
        if fi-fo<(CFG['images_min'] if info['type']=='blanc' else 2):
            if info['type']=='retrait': info['abandon']='rien à retirer'; log.append(info)
            continue
        info.update(sortie=round(fo/FPS,2),entree=round(fi/FPS,2),retire=round((fi-fo)/FPS,2)); rem.append([fo,fi,info]); log.append(info)
    first=W[idx[0]][0]; last=W[idx[-1]][1]
    ts=calm_until(first-0.6,first+0.08); st=max(first-0.30,(ts-0.12) if ts else first-0.12)
    te=calm_from(last-0.10,last+0.8); en=min(last+0.5,(te+0.30) if te else last+0.25)
    if idx[0]>0: st=max(st,min(first-0.04,W[idx[0]-1][1]+0.02))                  # ne pas déborder sur le mot d'avant
    if idx[-1]<len(W)-1: en=max(last+0.04,min(en,W[idx[-1]+1][0]-0.03))           # ni sur le mot d'après
    F0=int(round(st*FPS)); F1=int(round(en*FPS)); rem.sort(key=lambda r:r[0])
    def mk():
        segs=[]; cur=F0; ph=False
        for fo,fi,info in rem:
            if fo-cur<3: cur=max(cur,fi); ph=ph or info['phrase']; continue
            segs.append([cur,fo,ph]); cur=fi; ph=info['phrase']
        if F1-cur>=3: segs.append([cur,F1,ph])
        return segs
    # un morceau trop court entre deux coupes fait un flash : on rend le plus petit des deux blancs voisins
    while True:
        segs=mk(); small=[s for s in segs[1:-1] if s[1]-s[0]<CFG.get('morceau_min_images',10)]
        if not small: break
        a,b,_=small[0]; cand=[r for r in rem if r[2]['type']=='blanc' and (r[1]==a or r[0]==b)]
        if not cand: break
        r=min(cand,key=lambda r:r[1]-r[0]); r[2]['rendu']='morceau trop court'; rem.remove(r); log.remove(r[2])
    return segs,log,back
def load_keep():
    keep=np.zeros(len(W),bool); drops=[]
    for a,b in CFG['plages']:
        for i,(s,e,t) in enumerate(W):
            if a-0.05<=s<b: keep[i]=True
    for it in CFG['retirer']:
        T,ph=it[0],it[1]; force=len(it)>2 and it[2]      # [temps, "mots", true] : à couper même si les mots sont collés
        toks=ph.split(); hit=None
        for i,(s,e,t) in enumerate(W):
            if s>=T-0.05 and [x[2] for x in W[i:i+len(toks)]]==toks: hit=i; break
        if hit is None: raise SystemExit(f'introuvable: {T} {ph}')
        keep[hit:hit+len(toks)]=False
        if not force: drops.append((hit,hit+len(toks)-1))
    for i,(s,e,t) in enumerate(W):
        if t.strip() in ('.','?','!',',','…'): keep[i]=False
    return keep,set(drops)
def build(keep,opt,lo=None,hi=None):
    sel=lambda: [i for i in range(len(W)) if keep[i] and (lo is None or W[i][0]>=lo-0.05) and (hi is None or W[i][0]<hi)]
    segs,log,back=segments(sel(),opt)
    if back:
        for i in back: keep[i]=True
        segs,log2,_=segments(sel(),())
        log=[l for l in log if 'abandon' in l]+log2
    return segs,log,sel()
if __name__=='__main__':
    keep,opt=load_keep(); segs,log,idx=build(keep,opt)
    T=sum(b-a for a,b,_ in segs)/FPS
    json.dump({'segs':segs,'log':log,'mots':idx,'keep':[bool(k) for k in keep]},open(D+'/derush.out.json','w'),ensure_ascii=False)
    bl=[l for l in log if l['type']=='blanc']; rt=[l for l in log if l['type']=='retrait']
    print(f"durée {T:.1f} s en {len(segs)} morceaux ; blancs resserrés : {len(bl)} ({sum(l['retire'] for l in bl):.1f} s, dont {sum(1 for l in bl if l.get('son_retire'))} avec un son non transcrit) ; retraits : {len([l for l in rt if 'retire' in l])} ({sum(l.get('retire',0) for l in rt):.1f} s)")
    for l in rt:
        if 'abandon' in l or 'creux_sortie_dB' in l or 'creux_entree_dB' in l: print('  ',{k:v for k,v in l.items() if k not in('type','phrase')})
    print('son non transcrit retiré (à vérifier) :',[(l['sortie'],l['avant'],l['apres'],l['son_retire']) for l in log if l.get('son_retire') and l['type']=='blanc'])
    print('morceaux < 0.6 s :',[(a/FPS,b/FPS) for a,b,_ in segs if b-a<15])
