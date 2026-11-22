#!/usr/bin/env python3
# ÉCOUTE PAR WHISPER (règles 26 et 31 ; l'auteur, 04/10/2026 : « il faut que tu mettes Whisper pour l'écouter, il faut vraiment que ce soit
# clair » ; 05/10/2026 : « fais en sorte qu'à chaque fois il puisse la comprendre à 99 % »).
# Claude n'entend pas. Whisper (large-v3-turbo) écoute le son d'un montage et écrit ce qu'il comprend ; on compare aux mots du dérush.
#
#   python3 tools/ecoute_whisper.py <final.mp4|.wav> <mots attendus .json> [--voix-seule voix.wav] [--fin 43.2] [--sortie ecoute.json]
#   python3 tools/ecoute_whisper.py <passage.wav> <mots attendus .json> --passage      (AVANT de monter : un passage candidat, voix seule)
#
# « mots attendus » : {"words":[{"text":…}]} (cut.words.json) ou une liste de mots.
#
# CIBLE (règle 31) : 99 % des mots compris, sur le son FINAL.
#   VERT   : final >= 99 %.
#   ORANGE : final sous 99 % mais pas sous la voix seule. Le montage ne coûte rien : les mots qui manquent sont mal dits à la prise
#            (mots avalés, phrase dite trop vite). Aucun réglage de son ne les rend. On le dit dans la fiche, avec les mots et leur instant.
#   ROUGE  : final sous la voix seule. C'est le mixage : on baisse (x0,4) les sons posés à moins de 0,7 s avant le mot perdu ; s'il n'y en a
#            pas, on baisse le fond de 3 dB (jusqu'à 39 dB sous la voix). On remixe, on réécoute. On ne livre pas un ROUGE.
#   --passage : VERT si le passage est compris à 99 % voix seule. Sinon, à ce stade (choix des passages, règle 27), on prend une autre
#            prise ou on retire la phrase mal dite si l'idée reste entière ; si la phrase est indispensable, on la garde et on le signale.
#
# MESURE STABLE (05/10/2026) : température 0 et recherche par faisceau (5). Avant, Whisper retentait au hasard les passages difficiles et
# le même son donnait 94,8 % puis 97,4 %. Même son, même résultat maintenant ; l'écart d'un seul mot reste du bruit de mesure.
# VOCABULAIRE : le jargon du client est donné à Whisper comme à quelqu'un du métier (--vocab, ou clients/return par défaut). JAMAIS le
# texte du montage : ce serait lui souffler la réponse.
# HOMOPHONES : « foncer » / « foncé », « ses » / « ces » se prononcent pareil ; le choix d'orthographe de Whisper n'est pas une erreur.
# Les nombres (chiffres ou lettres) et « euros » sont retirés des deux côtés ; les élisions sont développées.
# Modèle : claude-video-kit/.linux/models/large-v3-turbo s'il existe, sinon téléchargé (pip install faster-whisper). Compter 1 à 2 s de
# calcul par seconde de son sur un cœur.
import sys,os,json,re,unicodedata,difflib,subprocess,argparse
import numpy as np
K=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); _m=None
SEUIL=99.0
VOCAB="Sarah Events. Événementiel : cheffe de projet, congrès, séminaire, soirée, défilé, vernissage, kakémono, traiteur, hôtesses, régie, VIC."
def modele():
    global _m
    if _m is None:
        from faster_whisper import WhisperModel
        loc=K+'/.linux/models/large-v3-turbo'
        _m=WhisperModel(loc if os.path.isdir(loc) else 'large-v3-turbo',device='cpu',compute_type='int8',cpu_threads=max(1,(os.cpu_count() or 2)-1))
    return _m
def charge(path,fin=None):
    r=subprocess.run(['ffmpeg','-v','error','-i',path,'-vn','-ac','1','-ar','16000','-f','s16le','-'],capture_output=True).stdout
    x=np.frombuffer(r,dtype=np.int16).astype(np.float32)/32768; return x[:int(fin*16000)] if fin else x
NB=set("zero un une deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze quinze seize vingt trente quarante cinquante soixante cent cents mille euros euro pour".split())
EL={'t':'tu','j':'je','qu':'que','c':'ce','n':'ne','d':'de','l':'le','s':'se','m':'me'}
def norm(s):
    """mots comparables : sans accents ni ponctuation ; nombres (chiffres ou lettres) et « euros » retirés des deux côtés ; élisions développées"""
    s=unicodedata.normalize('NFD',s.lower().replace('€',' euros ').replace('%',' pour cent ')); s=''.join(c for c in s if unicodedata.category(c)!='Mn')
    return [EL.get(w,w) for w in re.sub(r"[^a-z0-9]+"," ",s).split() if not w.isdigit() and w not in NB]
def phon(w):
    """homophones ramenés à la même forme"""
    if w in ('ces','ses'): return 'ses'
    if w in ('vapeau','vapeaux','vapos','vaco','vacos','vapour'): return 'vapo'      # 12/10/2026 : un produit, Whisper l'écrit de cinq façons
    if len(w)>3:
        w=re.sub(r'(er|ez|ee|ees|es)$','e',w)
        if len(w)>3: w=re.sub(r'[sx]$','',w)
    return w
def ecoute(x,vocab=VOCAB):
    seg,_=modele().transcribe(x,language='fr',word_timestamps=True,beam_size=5,temperature=0.0,vad_filter=False,condition_on_previous_text=False,initial_prompt=vocab)
    return [{'t':w.word.strip(),'s':round(w.start,2),'e':round(w.end,2),'p':round(w.probability,3)} for s in seg for w in s.words]
def compare(W,attendu):
    """taux de mots compris et écarts datés (secondes dans le son écouté)"""
    a=[phon(x) for x in norm(' '.join(attendu))]; b=[]; ix=[]
    for k,w in enumerate(W):
        for t in norm(w['t']): b.append(phon(t)); ix.append(k)
    sm=difflib.SequenceMatcher(None,a,b,autojunk=False); ok=sum(x.size for x in sm.get_matching_blocks()); diff=[]
    for tag,i1,i2,j1,j2 in sm.get_opcodes():
        if tag=='equal': continue
        if j1<j2: t0=W[ix[j1]]['s']; t1=W[ix[j2-1]]['e']
        else: t0=W[ix[j1-1]]['e'] if j1>0 else 0.0; t1=W[ix[j1]]['s'] if j1<len(ix) else (W[-1]['e'] if W else 0.0)
        diff.append({'tag':tag,'attendu':' '.join(a[i1:i2]),'entendu':' '.join(b[j1:j2]),'t0':round(float(t0),2),'t1':round(float(t1),2)})
    return {'mots_attendus':len(a),'taux':round(100*ok/max(1,len(a)),1),'ecarts':diff}
def rapport(path,attendu,fin=None,vocab=VOCAB):
    W=ecoute(charge(path,fin),vocab); c=compare(W,attendu)
    return {'taux':c['taux'],'mots_attendus':c['mots_attendus'],'confiance':round(float(np.mean([w['p'] for w in W])),3) if W else 0,'mots_faibles':[(w['t'],w['s']) for w in W if w['p']<0.5],'ecarts':c['ecarts'],'texte':' '.join(w['t'] for w in W)}
def verdict(final,voix=None):
    if final['taux']>=SEUIL: return 'VERT'
    if voix is None: return 'ORANGE'
    return 'ORANGE' if final['taux']>=voix['taux'] else 'ROUGE'
if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('son'); ap.add_argument('attendu'); ap.add_argument('--voix-seule'); ap.add_argument('--fin',type=float); ap.add_argument('--sortie'); ap.add_argument('--vocab'); ap.add_argument('--passage',action='store_true')
    a=ap.parse_args(); d=json.load(open(a.attendu)); att=[(x.get('text') or x.get('t')) if isinstance(x,dict) else x for x in (d['words'] if isinstance(d,dict) else d)]
    vocab=a.vocab if a.vocab is not None else VOCAB
    res={'final':rapport(a.son,att,a.fin,vocab)}
    if a.voix_seule: res['voix_seule']=rapport(a.voix_seule,att,a.fin,vocab)
    f=res['final']; v=res.get('voix_seule'); res['verdict']=('VERT' if f['taux']>=SEUIL else 'ORANGE') if a.passage else verdict(f,v); res['seuil']=SEUIL
    if a.sortie: json.dump(res,open(a.sortie,'w'),ensure_ascii=False,indent=1)
    print(res['verdict'],'—',('passage' if a.passage else 'final'),':',f['taux'],'% des',f['mots_attendus'],'mots compris, confiance',f['confiance'],('| voix seule : '+str(v['taux'])+' %') if v else '')
    if res['verdict']=='ORANGE' and not a.passage: print('   le montage ne coûte rien : les mots ci-dessous sont mal dits à la prise (à signaler dans la fiche)')
    if res['verdict']=='ROUGE': print('   le mixage coûte des mots : baisser les sons posés avant ces mots, puis le fond (règle 31), et réécouter')
    if a.passage and res['verdict']!='VERT': print('   passage sous 99 % : autre prise, ou retirer la phrase mal dite si l\'idée reste entière (règles 27 et 31)')
    for e in f['ecarts'][:20]:
        if e['tag']!='insert': print(f"   @{e['t0']} s : attendu « {e['attendu']} » → entendu « {e['entendu']} »")
    if f['mots_faibles']: print('   mots peu sûrs :',', '.join(f"{w} @{t}s" for w,t in f['mots_faibles'][:12]))
