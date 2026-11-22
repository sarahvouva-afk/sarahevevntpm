#!/usr/bin/env python3
# RÉÉCOUTE — contrôle obligatoire d'un montage AVANT livraison (règle de l'auteur du 03/10/2026).
# Claude n'a pas d'oreilles : la « réécoute », c'est ce script. Il prend le FINAL (pas le rush) et vérifie :
#   1. les blancs : toute zone calme trop longue dans le son du final (mesure sur l'enveloppe, pas sur la transcription) ;
#   2. ce qui est dit : le final est retranscrit mot à mot (Scribe) → pauses entre mots, « euh », consignes de régie
#      (« tu peux enchaîner »…), reprises (« c'est une, c'est une »), excuses ;
#   3. les coupes : si on donne la liste des mots attendus (--attendu), chaque mot attendu doit se retrouver dans le
#      final (un mot manquant = coupe qui mange un mot) et rien d'autre ne doit apparaître.
# Verdict VERT / ORANGE / ROUGE. Un ROUGE ne se livre pas : on corrige le dérush et on relance.
#   python3 tools/reecoute.py <final.mp4|.wav|.mp3> [--attendu mots.json] [--mots scribe.json] [--out rapport.txt]
#                             [--format long]  (format long : rythme naturel, seuls les blancs ≥ 0,8 s sont signalés)
#                             [--debut 0] [--fin 0]   (secondes à ignorer au début / à la fin : intro motion, outro)
import sys,os,json,re,subprocess,argparse,tempfile,difflib,unicodedata,wave
import numpy as np
from scipy.signal import butter,sosfiltfilt
from scipy.ndimage import percentile_filter
ap=argparse.ArgumentParser(); ap.add_argument('final'); ap.add_argument('--attendu'); ap.add_argument('--mots'); ap.add_argument('--out')
ap.add_argument('--debut',type=float,default=0); ap.add_argument('--fin',type=float,default=0)
ap.add_argument('--blanc-rouge',type=float,default=0.8); ap.add_argument('--blanc-orange',type=float,default=0.6)
ap.add_argument('--sans-scribe',action='store_true'); ap.add_argument('--format',default='court',choices=['court','long'])
A=ap.parse_args()
if A.format=='long': A.blanc_orange=max(A.blanc_orange,0.8)   # format long : rythme naturel (l'auteur, 03/10/2026), seuls les blancs de 0,8 s ou plus comptent
KIT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp=tempfile.mkdtemp(); wav=os.path.join(tmp,'a.wav')
subprocess.run(['ffmpeg','-y','-loglevel','error','-i',A.final,'-vn','-ac','1','-ar','32000','-c:a','pcm_s16le',wav],check=True)
wv=wave.open(wav); sr=wv.getframerate(); x=np.frombuffer(wv.readframes(wv.getnframes()),dtype=np.int16)/32768; DUR=len(x)/sr
T0=A.debut; T1=DUR-A.fin
def tc(t): return f"{int(t//60)}:{t%60:04.1f}"
# ---- 1. blancs (enveloppe large bande, seuil local entre le plancher et la voix)
y=sosfiltfilt(butter(4,[150,9000],btype='band',fs=sr,output='sos'),x); hop=int(sr*0.01); win=int(sr*0.03)
c=np.cumsum(np.concatenate([[0],y*y])); ii=np.arange(0,len(y)-win,hop); env=10*np.log10((c[ii+win]-c[ii])/win+1e-12)
dec=env[::10]; fl=percentile_filter(dec,8,size=200,mode='nearest'); sp=percentile_filter(dec,85,size=200,mode='nearest')
thr=np.repeat(fl+0.5*(sp-fl),10)[:len(env)]; thr=np.pad(thr,(0,len(env)-len(thr)),mode='edge'); calm=env<thr
d=np.diff(np.concatenate([[0],calm.astype(int),[0]])); st=np.where(d==1)[0]; en=np.where(d==-1)[0]
blancs=[(max(T0,s*0.01),min(T1,e*0.01)-max(T0,s*0.01)) for s,e in zip(st,en)]; blancs=[b for b in blancs if b[1]>=A.blanc_orange]   # seulement la partie dans la fenêtre analysée
R=[]; rouge=[]; orange=[]
tot=float(np.sum([min(T1,e*0.01)-max(T0,s*0.01) for s,e in zip(st,en) if min(T1,e*0.01)-max(T0,s*0.01)>=0.35]))
R.append(f"RÉÉCOUTE de {os.path.basename(A.final)} — {tc(DUR)} (analysé de {tc(T0)} à {tc(T1)})")
R.append(f"\n1. BLANCS (son calme) : {len([b for b in blancs if b[1]>=A.blanc_rouge])} de {A.blanc_rouge} s ou plus, {len([b for b in blancs if b[1]<A.blanc_rouge])} entre {A.blanc_orange} et {A.blanc_rouge} s ; calme cumulé au-delà de 0,35 s : {tot:.0f} s sur {T1-T0:.0f} s")
for t,dur in blancs:
    R.append(f"   {tc(t)}  blanc de {dur:.2f} s"); (rouge if dur>=A.blanc_rouge else orange).append(f"blanc {dur:.2f} s à {tc(t)}")
# ---- 2. ce qui est dit
words=None
if A.mots: words=json.load(open(A.mots))['words']
elif not A.sans_scribe:
    mp3=os.path.join(tmp,'a.mp3'); subprocess.run(['ffmpeg','-y','-loglevel','error','-i',wav,'-c:a','libmp3lame','-b:a','64k',mp3],check=True)
    out=os.path.join(tmp,'scribe.json'); r=subprocess.run(['node',os.path.join(KIT,'engine','cut','scribe.mjs'),mp3,out],capture_output=True,text=True)
    if r.returncode: R.append(f"\n2. RETRANSCRIPTION IMPOSSIBLE : {r.stderr.strip()[-200:]}"); rouge.append('retranscription impossible : la réécoute est incomplète')
    else:
        words=json.load(open(out))['words']
        if A.out: json.dump({'words':words},open(re.sub(r'\.txt$','',A.out)+'.mots.json','w'),ensure_ascii=False)
norm=lambda s:re.sub(r"[^a-z0-9']+",'',unicodedata.normalize('NFD',s.lower()).encode('ascii','ignore').decode())
if words is not None:
    ws=[w for w in words if T0<=w['start']<T1 and norm(w['text'])]
    R.append(f"\n2. CE QUI EST DIT : {len(ws)} mots retranscrits")
    gaps=[(a['end'],b['start']-a['end'],a['text'],b['text']) for a,b in zip(ws,ws[1:]) if b['start']-a['end']>=A.blanc_orange]
    R.append(f"   Pauses entre deux mots ≥ {A.blanc_orange} s : {len(gaps)}")
    for t,g,a,b in gaps:
        R.append(f"   {tc(t)}  {g:.2f} s entre « {a} » et « {b} »")
        k0,k1=int(t/0.01),max(int(t/0.01)+1,int((t+g)/0.01)); fc=float(np.mean(calm[k0:k1]))
        if any(bt<t+g and bt+bd>t and bd>=A.blanc_rouge for bt,bd in blancs): pass      # déjà compté comme blanc (son calme) ci-dessus
        elif fc<0.6 or g>=A.blanc_rouge: orange.append(f"{g:.2f} s sans mot retranscrit à {tc(t)} (hésitation, mot avalé ou bruit : à écouter)")
    txt=[norm(w['text']) for w in ws]
    REGIE=["tu peux enchainer","tu peux continuer","tu peux passer","enchaine","continue","on enchaine","c'est pas grave","pardon","excusezmoi","excuse moi","je recommence","on la refait","attends","coupe"]
    hits=[]
    for ph in REGIE:
        p=[norm(t) for t in ph.split()]
        for i in range(len(txt)-len(p)+1):
            if txt[i:i+len(p)]==p and (len(p)>1 or ws[i]['text'].strip()[-1:] in '.!' and (i==0 or ws[i-1]['text'].strip()[-1:] in '.?!')): hits.append((ws[i]['start'],' '.join(w['text'] for w in ws[i:i+len(p)])))
    R.append(f"   Consignes de régie / excuses : {len(hits)}")
    for t,h in sorted(set(hits)): R.append(f"   {tc(t)}  « {h} »"); rouge.append(f"régie « {h} » à {tc(t)}")
    euh=[(w['start'],w['text']) for w in ws if re.fullmatch(r"(e+u+h+|h+u+m+|b+a+h+|b+e+n+|h+e+i+n+)",norm(w['text']))]
    R.append(f"   Hésitations (euh, bah, ben, hein) : {len(euh)}")
    for t,h in euh: R.append(f"   {tc(t)}  « {h} »")
    if len(euh)>max(3,len(ws)//250): orange.append(f"{len(euh)} hésitations restantes")
    rep=[]; i=0
    while i<len(txt):
        found=False
        for n in (4,3,2,1):
            if i+2*n<=len(txt) and txt[i:i+n]==txt[i+n:i+2*n] and (n>1 or len(txt[i])>3) and not (n==1 and txt[i] in ('vous','nous','tres','bien','fort')):
                rep.append((ws[i]['start'],' '.join(w['text'] for w in ws[i:i+2*n]))); i+=n; found=True; break
        if not found: i+=1
    R.append(f"   Reprises (même groupe de mots dit deux fois de suite) : {len(rep)}")
    for t,h in rep: R.append(f"   {tc(t)}  « {h} »")
    if rep: orange.append(f"{len(rep)} reprise(s) restante(s) : à écarter si ce n'est pas voulu")
    if A.attendu:
        exp=json.load(open(A.attendu)); et=[norm(e['t']) for e in exp]; keep=[k for k,t in enumerate(et) if t]; et=[et[k] for k in keep]
        sm=difflib.SequenceMatcher(None,et,txt,autojunk=False); manq=[];extra=[]
        for op,i1,i2,j1,j2 in sm.get_opcodes():
            if op=='equal': continue
            a=' '.join(exp[keep[k]]['t'] for k in range(i1,i2)); b=' '.join(ws[k]['text'] for k in range(j1,j2)); t=ws[min(j1,len(ws)-1)]['start']
            close=difflib.SequenceMatcher(None,norm(a),norm(b)).ratio()
            if op=='delete' or (op=='replace' and close<0.6 and i2-i1>j2-j1): manq.append((t,a,b))
            elif op=='insert' or (op=='replace' and close<0.6): extra.append((t,a,b))
        R.append(f"\n3. COUPES : {sm.ratio()*100:.1f} % des mots attendus retrouvés à l'identique ; {len(manq)} passage(s) manquant(s) ou mangé(s), {len(extra)} passage(s) inattendu(s)")
        for t,a,b in manq: R.append(f"   {tc(t)}  attendu « {a} » → entendu « {b} »"); 
        for t,a,b in extra: R.append(f"   {tc(t)}  inattendu « {b} » (attendu « {a} »)")
        nm=sum(len(a.split()) for _,a,_ in manq)
        if sm.ratio()<0.90: rouge.append(f"seulement {sm.ratio()*100:.0f} % des mots attendus retrouvés : coupes à vérifier")
        elif manq: orange.append(f"{len(manq)} passage(s) attendus non retrouvés tels quels (mot mangé par une coupe, ou simple écart de retranscription)")
        if extra: orange.append(f"{len(extra)} passage(s) inattendu(s)")
verdict='ROUGE' if rouge else 'ORANGE' if orange else 'VERT'
R.insert(1,f"VERDICT : {verdict}"+(' — NE PAS LIVRER, corriger puis relancer' if rouge else ''))
if rouge: R.insert(2,'  Bloquant : '+' ; '.join(rouge[:12])+(' …' if len(rouge)>12 else ''))
if orange: R.insert(3 if rouge else 2,'  À vérifier : '+' ; '.join(orange[:12])+(' …' if len(orange)>12 else ''))
rep_='\n'.join(R); print(rep_)
if A.out: open(A.out,'w',encoding='utf-8').write(rep_+'\n')
sys.exit(2 if rouge else 0)
