#!/usr/bin/env python3
# VOIX CLAIRE — éclaircir la voix quand c'est nécessaire (l'auteur, 04/10/2026 : « il y a un problème de son, n'hésite pas à
# éclaircir ma voix quand c'est nécessaire, sur les reels et les vidéos longues »).
# Claude n'entend pas : ce script MESURE le son, décide s'il faut corriger, corrige, puis re-mesure.
#   python3 tools/voix_claire.py <entrée.wav|.mp4> <sortie.wav> [--lufs -16] [--rapport fiche.txt] [--mesure-seule]
# Ce qu'il mesure, sur les moments où quelqu'un parle :
#   - l'équilibre de la voix par bandes, comparé à une voix prise de près (cible ci-dessous) ;
#   - le souffle : écart entre la voix et le fond ; l'écart entre les passages forts et faibles (LRA).
# Ce qu'il fait si c'est nécessaire (chaque correction est bornée, pour ne pas dénaturer la voix) :
#   réduction du bruit de fond (porte spectrale, profil mesuré dans les silences) · coupe-bas · moins de graves et de bas-médium (voix sourde, pièce qui résonne)
#   · plus de présence (2 à 5 kHz) et d'air (au-dessus de 7 kHz) · dé-esseur léger · compression douce (voix lointaines
#   remontées) · niveau final (−16 LUFS en long, −14 en court) · limiteur.
import sys,os,json,subprocess,argparse,tempfile,wave,re
import numpy as np
from scipy.signal import welch
BANDES=[(50,120),(120,250),(250,500),(500,1000),(1000,2000),(2000,4000),(4000,8000),(8000,16000)]
# CIBLE v2 (04/10/2026) : calée sur la voix de l'auteur dans SON reel de référence (reel de référence, « tu reconnais
# ma voix »), mesurée avec la même méthode : 50–120 Hz −17,9 · 120–250 −2,8 · 250–500 +2,2 · 500–1000 0 · 1–2 kHz −10 ·
# 2–4 kHz −20,3 · 4–8 kHz −28 · 8–16 kHz −42,9 ; voix forte et dense (90 % des trames sous −12,5 dBFS, médiane −18,5),
# aucun blanc de 0,3 s. Sa voix est chaude, proche, sans grondement. On reprend son bas (grondement coupé, corps gardé) ;
# pour le haut on reste entre sa référence (très sombre, micro proche + compression Instagram) et une voix neutre : on
# n'ajoute plus d'aigu à un micro lointain, on enlève ce qui la rend sourde (250–500 Hz) et ce qui gronde (< 110 Hz).
CIBLE=[-14.0,-2.0,2.5,0.0,-3.0,-9.0,-15.0,-24.0]      # dB par rapport à la bande 500–1000 Hz
TOL=1.5
def lire(p):
    # 06/10/2026 : le ffmpeg 9 du Mac écrit des WAV « étendus » (format 65534) que wave de Python 3.9 refuse : on lit par ffmpeg
    try:
        w=wave.open(p) if p.lower().endswith('.wav') else None
        if w is not None and w.getsampwidth()==2:
            return w.getframerate(),np.frombuffer(w.readframes(w.getnframes()),dtype=np.int16).reshape(-1,w.getnchannels())/32768
    except wave.Error: pass
    raw=subprocess.run(['ffmpeg','-loglevel','error','-i',p,'-vn','-ar','48000','-ac','2','-f','s16le','-'],capture_output=True,check=True).stdout
    return 48000,np.frombuffer(raw,dtype=np.int16).reshape(-1,2)/32768
def mesure(sr,x):
    m=x.mean(1); hop=int(sr*0.02); n=len(m)//hop
    e=10*np.log10(np.mean(m[:n*hop].reshape(n,hop)**2,axis=1)+1e-12)
    plancher=float(np.percentile(e,5)); voix=float(np.percentile(e,90)); thr=plancher+0.6*(voix-plancher)
    iv=np.where(e>thr)[0]; ib=np.where(e<plancher+3)[0]
    def psd(ix,sig):
        seg=sig[:n*hop].reshape(n,hop)[ix[:80000]].ravel(); f,P=welch(seg,sr,nperseg=4096); return f,P
    f,P=psd(iv,m); fb,Pb=psd(ib,m)
    S=[10*np.log10(P[(f>=a)&(f<c)].sum()+1e-20) for a,c in BANDES]; N=[10*np.log10(Pb[(fb>=a)&(fb<c)].sum()+1e-20) for a,c in BANDES]
    rel=[s-S[3] for s in S]
    out={'plancher_dB':round(plancher,1),'voix_dB':round(voix,1),'ecart_voix_fond_dB':round(voix-plancher,1),
         'profil':[round(v,1) for v in rel],'ecart_cible':[round(v-c,1) for v,c in zip(rel,CIBLE)],'fond_sous_voix':[round(nv-sv,1) for nv,sv in zip(N,S)]}
    out['clarte']=round(float(np.mean(rel[5:7])-np.mean(rel[1:3])),1)      # présence (2–8 kHz) moins bas (120–500 Hz) ; cible ≈ −12
    if x.shape[1]==2:
        def gap(sig):
            ee=10*np.log10(np.mean(sig[:n*hop].reshape(n,hop)**2,axis=1)+1e-12); return float(np.percentile(ee,90)-np.percentile(ee,5))
        out['ecart_G']=round(gap(x[:,0]),1); out['ecart_D']=round(gap(x[:,1]),1); out['ecart_somme']=round(gap(m),1)
    return out
def debruiter(sr,x,prop=0.95,nstd=1.5,nfft=2048,hop=512):
    """Réduction du bruit de fond par porte spectrale. Le profil du bruit est MESURÉ dans les silences du fichier lui-même
    (trames les plus calmes), par tranches de 20 s, pour suivre un fond qui change (vent, passage). Tout ce qui ne dépasse
    pas le bruit de nstd écarts-types est baissé de prop (0,95 = -26 dB) ; le masque est lissé en temps (50 ms) et en
    fréquence (500 Hz) pour éviter les gazouillis. Aucune dépendance autre que numpy / scipy."""
    from scipy.signal import stft,istft
    from scipy.ndimage import uniform_filter
    m=x.mean(1); n=len(m); out=np.zeros_like(x)
    f,t,Zm=stft(m,sr,nperseg=nfft,noverlap=nfft-hop); P=np.abs(Zm)**2; bd=(f>=150)&(f<=9000)
    e=10*np.log10(P[bd].sum(0)+1e-12); nt=len(t); blk=int(20*sr/hop); ctx=int(30*sr/hop)
    centres=list(range(0,nt,blk)) or [0]; TH=[]
    for c0 in centres:
        a_,b_=max(0,c0-ctx),min(nt,c0+blk+ctx); ee=e[a_:b_]; fl=np.percentile(ee,5); idx=np.where(ee<fl+4)[0]+a_
        if len(idx)<int(1.5*sr/hop): fl=np.percentile(e,5); idx=np.where(e<fl+4)[0]
        TH.append(idx)
    fb=max(1,int(round(500/(sr/nfft)))); tb=max(1,int(round(0.05*sr/hop)))
    for c in range(x.shape[1]):
        f,t,Z=stft(x[:,c],sr,nperseg=nfft,noverlap=nfft-hop); S=20*np.log10(np.abs(Z)+1e-9); thr=np.zeros_like(S)
        cols=[]
        for idx in TH: Sn=S[:,idx]; cols.append(Sn.mean(1)+nstd*Sn.std(1))
        cols=np.array(cols).T                                  # fréquence x tranche
        pos=np.array([min(nt-1,c0+blk//2) for c0 in centres],float); tt=np.arange(nt,dtype=float)
        for k in range(S.shape[0]): thr[k]=np.interp(tt,pos,cols[k])
        mask=(S<thr).astype(np.float32); mask=uniform_filter(mask,size=(fb,tb),mode='nearest')*prop
        _,y=istft(Z*(1-mask),sr,nperseg=nfft,noverlap=nfft-hop); y=y[:n]; out[:len(y),c]=y
    return out
def fond_voix(sr,x,ref=None):
    """niveau de la voix et du fond (dB) sur les mêmes trames, celles de ref (le son d'origine) si donné"""
    m=x.mean(1); hop=int(sr*0.02); n=len(m)//hop; e=10*np.log10(np.mean(m[:n*hop].reshape(n,hop)**2,axis=1)+1e-12)
    r=e if ref is None else ref[:n]; fl=np.percentile(r,5); vx=np.percentile(r,90); thr=fl+0.6*(vx-fl)
    return float(np.mean(e[r>thr])), float(np.mean(e[r<fl+4])), e
def lra(p):
    r=subprocess.run(['ffmpeg','-hide_banner','-nostats','-i',p,'-af','ebur128','-f','null','-'],capture_output=True,text=True).stderr
    I=re.findall(r"I:\s+(-?[\d.]+) LUFS",r); L=re.findall(r"LRA:\s+(-?[\d.]+) LU",r); return (float(I[-1]) if I else None, float(L[-1]) if L else None)
def chaine(M,lufs):
    d=M['ecart_cible']; borne=lambda v,a,b:max(a,min(b,v)); notes=[]
    if d[0]>6: f=['highpass=f=105:poles=2','highpass=f=105:poles=2']; notes.append(f"grondement sous 110 Hz coupé (il dépassait la référence de {d[0]:.0f} dB)")
    else: f=['highpass=f=85:poles=2']
    g_bas=borne(-d[1],-6,0) if d[1]>TOL else 0; g_bm=borne(-d[2],-7,0) if d[2]>TOL else 0
    g_pres=borne(-np.mean(d[5:6]),0,5) if d[5]<-TOL else 0; g_air=borne(-d[6],0,4) if d[6]<-TOL else 0
    # après avoir retiré du bas, la présence remonte d'autant en relatif : on ne pousse l'aigu que s'il manque encore
    if g_bas: f.append(f"equalizer=f=170:t=q:w=0.9:g={g_bas:.1f}"); notes.append(f"graves 120–250 Hz {g_bas:+.1f} dB")
    if g_bm: f.append(f"equalizer=f=350:t=q:w=1.0:g={g_bm:.1f}"); notes.append(f"bas-médium 250–500 Hz {g_bm:+.1f} dB (voix sourde)")
    if g_pres: f.append(f"equalizer=f=3200:t=q:w=0.9:g={g_pres:.1f}"); notes.append(f"présence 2–4 kHz {g_pres:+.1f} dB")
    if g_air: f.append(f"treble=g={g_air:.1f}:f=7000:t=s:w=0.7"); notes.append(f"air au-dessus de 7 kHz {g_air:+.1f} dB")
    if g_pres or g_air: f.append('deesser=i=0.25:m=0.5:f=0.5')
    if M['ecart_voix_fond_dB']<34:
        f.append(f"agate=threshold={10**((M['plancher_dB']+9)/20):.5f}:ratio=1.6:range=0.45:attack=8:release=260:knee=4"); notes.append('fond abaissé de 7 dB au plus entre les phrases (expanseur doux)')
    f.append('acompressor=threshold=-26dB:ratio=2.5:attack=12:release=220:makeup=3:knee=6'); notes.append('compression douce 2,5:1 (voix lointaines remontées)')
    return ','.join(f),notes,bool(g_bas or g_bm or g_pres or g_air)
if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('entree'); ap.add_argument('sortie',nargs='?'); ap.add_argument('--lufs',type=float,default=-16); ap.add_argument('--rapport'); ap.add_argument('--mesure-seule',action='store_true'); ap.add_argument('--mono',action='store_true'); ap.add_argument('--sans-debruitage',action='store_true')
    A=ap.parse_args(); sr,x=lire(A.entree); M=mesure(sr,x); I0,L0=lra(A.entree)
    R=[f"VOIX CLAIRE — {os.path.basename(A.entree)}",f"Avant : niveau {I0} LUFS, écart fort/faible {L0} LU, fond à {M['ecart_voix_fond_dB']} dB sous la voix, clarté {M['clarte']} (cible ≈ -12)",
       "  bandes "+' '.join(f"{a}-{b}" for a,b in BANDES),"  profil  "+' '.join(f"{v:+.1f}" for v in M['profil']),"  cible   "+' '.join(f"{v:+.1f}" for v in CIBLE),"  écart   "+' '.join(f"{v:+.1f}" for v in M['ecart_cible'])]
    if A.mesure_seule or not A.sortie: print('\n'.join(R)); sys.exit(0)
    # --- réduction du bruit de fond, avant tout le reste (l'auteur, 04/10/2026 : « t'as pas fait de réduction de bruit »)
    notes0=[]; src=A.entree
    if not A.sans_debruitage:
        V0,N0,e0=fond_voix(sr,x)
        if V0-N0<34:
            for prop,nstd in ((0.95,1.25),(0.95,1.5)):
                y=debruiter(sr,x,prop,nstd); V1,N1,_=fond_voix(sr,y,e0)
                if V1-N1>=28 or (V0-V1)>3.5: break
            x=y; M=mesure(sr,x); src=tempfile.mktemp(suffix='.wav')
            w=wave.open(src,'w'); w.setnchannels(x.shape[1]); w.setsampwidth(2); w.setframerate(sr); w.writeframes((np.clip(x,-1,1)*32767).astype(np.int16).tobytes()); w.close()
            notes0.append(f"bruit de fond réduit de {N0-N1:.1f} dB (mesuré dans les silences ; la voix perd {V0-V1:.1f} dB), porte spectrale {prop} / {nstd}, profil du bruit pris dans les silences du fichier : la voix passe de {V0-N0:.1f} à {V1-N1:.1f} dB au-dessus du fond")
    F,notes,eq=chaine(M,A.lufs); notes=notes0+notes
    pre='pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1,' if (A.mono or (x.shape[1]==2 and M.get('ecart_somme',0)>=max(M['ecart_G'],M['ecart_D'])+0.8)) else ''
    if pre: notes.insert(0,'les deux canaux additionnés (le fond diffus baisse, la voix reste)')
    tmp=tempfile.mktemp(suffix='.wav')
    subprocess.run(['ffmpeg','-y','-loglevel','error','-i',src,'-vn','-af',pre+F,'-ar','48000','-c:a','pcm_s24le',tmp],check=True)
    # affinage : on re-mesure après la première passe et on corrige ce qui s'écarte encore de la voix de référence (borné)
    _,xt=lire(tmp); Mt=mesure(48000,xt); dt=Mt['ecart_cible']; aff=[]
    if dt[0]>4: aff.append('highpass=f=125:poles=2'); notes.append('coupe-bas remonté à 125 Hz (grondement encore au-dessus de la référence)')
    if dt[2]>TOL: g=max(-3.0,-dt[2]); aff.append(f"equalizer=f=350:t=q:w=1.0:g={g:.1f}"); notes.append(f"bas-médium {g:+.1f} dB de plus")
    hi=float(np.mean(dt[4:7]))
    if hi>TOL: g=max(-4.0,-hi); aff.append(f"highshelf=f=1600:g={g:.1f}:t=s:w=0.7"); notes.append(f"haut du spectre {g:+.1f} dB (voix plus chaude, comme la référence)")
    if aff:
        tmp2=tempfile.mktemp(suffix='.wav'); subprocess.run(['ffmpeg','-y','-loglevel','error','-i',tmp,'-af',','.join(aff),'-ar','48000','-c:a','pcm_s24le',tmp2],check=True); os.remove(tmp); tmp=tmp2; F=F+','+','.join(aff)
    Im,_=lra(tmp); gain=A.lufs-Im                      # niveau final par un gain fixe (pas de normalisation dynamique : elle remonterait le fond dans les silences)
    fin=f"volume={gain:.2f}dB,alimiter=limit=0.89:level=0:attack=3:release=60,aresample=48000"; F=F+','+fin
    subprocess.run(['ffmpeg','-y','-loglevel','error','-i',tmp,'-af',fin,'-ar','48000','-c:a','pcm_s16le',A.sortie],check=True); os.remove(tmp)
    notes.append(f"niveau final {A.lufs:.0f} LUFS par un gain fixe de {gain:+.1f} dB + limiteur")
    sr2,y=lire(A.sortie); M2=mesure(sr2,y); I1,L1=lra(A.sortie)
    R+=["Corrections : "+(' ; '.join(notes) if notes else 'aucune'),f"Chaîne ffmpeg : {pre+F}",
        f"Après : niveau {I1} LUFS, écart fort/faible {L1} LU, fond à {M2['ecart_voix_fond_dB']} dB sous la voix, clarté {M2['clarte']}",
        "  profil  "+' '.join(f"{v:+.1f}" for v in M2['profil']),"  écart   "+' '.join(f"{v:+.1f}" for v in M2['ecart_cible']),
        "Ce que la mesure ne dit pas : le timbre à l'oreille, un éventuel effet métallique de la réduction du souffle. À écouter sur 20 s."]
    txt='\n'.join(R); print(txt)
    if A.rapport: open(A.rapport,'w').write(txt+'\n')
