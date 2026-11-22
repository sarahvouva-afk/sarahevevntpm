#!/usr/bin/env python3
# MUSIQUES DE FOND — six ambiances synthétisées (aucun droit), pour varier selon le reel (l'auteur, 30/10/2026 : « les musiques ne sont pas
# assez variées, prends des musiques qui vont avec l'ambiance de la vidéo »). Chaque ambiance a son tempo, ses accords, ses instruments :
#   chill      boutique, déco : piano électrique chaud, basse ronde, grosse caisse feutrée, shaker (92 bpm)
#   tropical   mode, été, Antilles : marimba en arpèges, steel drum, percussions (100 bpm)
#   groove     outfit dynamique : basse funky, clap, guitare étouffée (108 bpm)
#   piano      valeurs, émotion : piano en arpèges, nappe douce (76 bpm)
#   disco      dynamiser : quatre temps, charleston ouvert, basse en octaves (118 bpm)
#   acoustique artisan, savoir-faire : guitare picking, bongos (96 bpm)
#   python3 tools/musiques.py <style> <durée> <sortie.wav> [graine]
import sys,numpy as np
from scipy.signal import butter,sosfilt,lfilter
SR=48000
N=lambda m:440.0*2**((m-69)/12)
def _t(d): return np.arange(int(SR*d))/SR
def lp(x,f,o=2): return sosfilt(butter(o,f,'low',fs=SR,output='sos'),x)
def hp(x,f,o=2): return sosfilt(butter(o,f,'high',fs=SR,output='sos'),x)
def bp(x,a,b,o=2): return sosfilt(butter(o,[a,b],'band',fs=SR,output='sos'),x)
R=np.random.default_rng(0)
# ---------------------------------------------------------------- instruments
def rhodes(f,d):
    t=_t(d); I=1.6*np.exp(-t*6)+0.25; c=np.sin(2*np.pi*f*t+I*np.sin(2*np.pi*f*t)); tine=0.18*np.sin(2*np.pi*f*14*t)*np.exp(-t*30)
    return (c+tine)*np.exp(-t*1.4)*np.minimum(1,t/0.004)
def piano(f,d):
    t=_t(d); y=np.zeros_like(t)
    for k in range(1,9): fk=f*k*np.sqrt(1+0.0004*k*k); y+=np.sin(2*np.pi*fk*t)*np.exp(-t*(0.9+0.55*k))/k**1.3
    y+=0.04*hp(R.standard_normal(len(t)),2000)*np.exp(-t*80); return y*np.minimum(1,t/0.002)
def marimba(f,d):
    t=_t(d); y=np.sin(2*np.pi*f*t)*np.exp(-t*5)+0.35*np.sin(2*np.pi*f*3.93*t)*np.exp(-t*16)+0.12*np.sin(2*np.pi*f*9.2*t)*np.exp(-t*40)
    return y*np.minimum(1,t/0.0015)
def steel(f,d):
    t=_t(d); I=1.1*np.exp(-t*3); y=np.sin(2*np.pi*f*t+I*np.sin(2*np.pi*2*f*t))+0.3*np.sin(2*np.pi*f*2.0*t)*np.exp(-t*4)+0.15*np.sin(2*np.pi*f*3.01*t)*np.exp(-t*7)
    return y*np.exp(-t*2.2)*np.minimum(1,t/0.003)
def pluck(f,d,bright=0.5):
    n=int(SR*d); P=max(2,int(SR/f)); x=np.zeros(n); x[:P]=lp(R.uniform(-1,1,P),2000+6000*bright)[:P]
    a=np.zeros(P+2); a[0]=1; a[P]=-0.4975; a[P+1]=-0.4975; return lfilter([1],a,x)*0.8
def bass(f,d,dist=1.6):
    t=_t(d); y=np.sin(2*np.pi*f*t)+0.3*np.sin(2*np.pi*2*f*t); env=np.minimum(1,t/0.004)*np.clip((d-t)/0.03,0,1)*np.exp(-t*1.2)
    return lp(np.tanh(y*dist)/np.tanh(dist),900)*env
def kick(g=1.0):
    t=_t(0.32); return np.sin(2*np.pi*(45*t+(120-45)*(1-np.exp(-t*35))/35))*np.exp(-t*11)*np.minimum(1,t/0.002)*g
def clap(g=1.0):
    t=_t(0.25); n=bp(R.standard_normal(len(t)),900,5000); env=np.zeros_like(t)
    for dl in (0,0.011,0.022): env+=np.exp(-np.maximum(0,t-dl)*60)*(t>=dl)
    return n*env*0.5*g
def rim(g=1.0):
    t=_t(0.08); return (np.sin(2*np.pi*1700*t)*0.6+bp(R.standard_normal(len(t)),1500,6000)*0.4)*np.exp(-t*90)*g
def hat(o=False,g=1.0):
    t=_t(0.35 if o else 0.06); return hp(R.standard_normal(len(t)),7000)*np.exp(-t*(12 if o else 90))*0.5*g
def shaker(g=1.0):
    t=_t(0.09); return bp(R.standard_normal(len(t)),4000,11000)*np.sin(np.pi*np.minimum(1,t/0.09))**2*0.35*g
def bongo(f=320,g=1.0):
    t=_t(0.2); return np.sin(2*np.pi*(f*t+f*0.6*(1-np.exp(-t*30))/30))*np.exp(-t*22)*g
# ---------------------------------------------------------------- styles
S={ 'chill':dict(bpm=92,prog=[(41,[57,60,64,67]),(40,[55,59,62,67]),(38,[57,60,62,65]),(36,[55,59,64,67])]),       # Fmaj7 Em7 Dm7 Cmaj7
    'tropical':dict(bpm=100,prog=[(41,[60,65,69]),(36,[60,64,67]),(38,[62,65,69]),(34,[62,65,70])]),                  # F C Dm Bb
    'groove':dict(bpm=108,prog=[(38,[60,65,69,72]),(43,[59,62,65,69]),(38,[60,65,69,72]),(43,[59,62,65,71])]),        # Dm7 G7
    'piano':dict(bpm=76,prog=[(45,[57,60,64]),(41,[57,60,65]),(36,[55,60,64]),(43,[55,59,62])]),                      # Am F C G
    'disco':dict(bpm=118,prog=[(45,[60,64,67,71]),(38,[60,62,66,69]),(45,[60,64,67,71]),(40,[59,62,67,71])]),         # Am9 D9 Am9 Em7
    'acoustique':dict(bpm=96,prog=[(43,[55,59,62,67]),(38,[54,57,62,66]),(40,[55,59,64,67]),(36,[55,60,64,67])]),     # G D Em C
}
def generer(style,dur,seed=1):
    global R
    R=np.random.default_rng(seed); st=S[style]; bpm=st['bpm']*(1+0.02*(seed%3-1)); be=60/bpm; n=int(SR*(dur+1)); L=np.zeros((n,2))
    def add(x,t0,g=1.0,pan=0.0):
        i=int(t0*SR); m=min(len(x),n-i)
        if m>0 and i>=0: L[i:i+m,0]+=x[:m]*g*(1-pan)/1.0; L[i:i+m,1]+=x[:m]*g*(1+pan)/1.0
    prog=st['prog'][seed%2:]+st['prog'][:seed%2]; nb=int(dur/be)+2
    for b in range(nb):
        t=b*be; bar=b//4; bt=b%4; root,ch=prog[(bar//2)%len(prog)] if style!='groove' else prog[bar%len(prog)]
        intro=t<2*4*be*0.5                           # 2 temps calmes au début
        if style=='chill':
            if bt in (0,2): add(kick(0.55),t)
            if bt in (1,3) and not intro: add(clap(0.22),t,pan=0.1)
            for k in range(4): add(shaker(0.25+0.15*(k%2)),t+k*be/4,pan=0.3)
            if bt==0 or (bt==2 and bar%2): 
                for m in ch: add(rhodes(N(m),be*3),t+(0.012*R.random()),0.16,pan=-0.15)
            if bt==1: 
                for m in ch[1:]: add(rhodes(N(m),be*1.2),t+be/2,0.09,pan=0.2)
            if bt in (0,2): add(bass(N(root),be*1.5),t,0.5)
            if bt==3: add(bass(N(root+7),be*0.5),t+be/2,0.35)
        elif style=='tropical':
            add(kick(0.45 if bt in (0,2) else 0.3),t)
            add(rim(0.22),t+be/2,pan=0.2)
            if bt==3 and bar%2: add(rim(0.15),t+be*0.75,pan=-0.2)
            for k in range(2): add(marimba(N(ch[(b*2+k)%len(ch)]+12),be),t+k*be/2,0.28,pan=-0.25)
            if bt in (0,2): add(bass(N(root),be*0.9,1.2),t,0.45)
            if bt==2: add(bass(N(root+12),be*0.4,1.2),t+be*0.75,0.25)
            if b%8 in (0,3,5) and not intro: add(steel(N(ch[R.integers(len(ch))]+12),be*2),t,0.17,pan=0.3)
            if b%4==3: add(bongo(380,0.25),t+be/2,pan=0.4); add(bongo(300,0.2),t+be*0.75,pan=0.4)
        elif style=='groove':
            if bt in (0,2): add(kick(0.65),t)
            if bt==2: add(kick(0.4),t+be*0.75)
            if bt in (1,3): add(clap(0.35),t,pan=0.05)
            for k in range(4): add(hat(False,0.22 if k%2 else 0.12),t+k*be/4,pan=0.35)
            pat=[(0,0,0.6),(0.75,12,0.45),(1.5,7,0.4),(2,0,0.55),(2.5,10,0.4),(3.25,12,0.45)]
            if bt==0:
                for off,iv,g in pat: add(bass(N(root+iv),be*0.35,2.2),t+off*be,g*0.9)
            add(pluck(N(ch[b%len(ch)]),be*0.25,0.3)*np.exp(-_t(be*0.25)[:int(SR*be*0.25)]*8),t+be/2,0.22,pan=-0.3)
        elif style=='piano':
            arp=ch+[ch[1]+12]
            for k in range(4): add(piano(N(arp[(bt*4+k)%len(arp)]),be*2.5),t+k*be/2 if k<2 else t+be*(0.5*k),0.22 if k==0 else 0.15,pan=-0.1+0.07*k)
            if bt==0: add(piano(N(root+12),be*4),t,0.2); 
            if bt==0 and not intro: add(kick(0.3),t)
            if not intro: add(shaker(0.12),t+be/2,pan=0.3)
        elif style=='disco':
            add(kick(0.7),t); add(hat(True,0.18),t+be/2,pan=0.3)
            if bt in (1,3) and not intro: add(clap(0.3),t)
            for k in range(2): add(bass(N(root+(12 if k else 0)),be*0.4,1.8),t+k*be/2,0.42)
            if bt in (1,3):
                for m in ch: add(rhodes(N(m),be*0.4),t+be/2,0.1,pan=0.2)
            for k in range(4): add(shaker(0.12),t+k*be/4,pan=-0.3)
        elif style=='acoustique':
            pat=[0,2,1,3,2,1,3,2]
            for k in range(2): 
                m=ch[pat[(b*2+k)%8]%len(ch)]; add(pluck(N(m),be*1.5,0.45),t+k*be/2,0.3,pan=-0.2+0.4*k)
            if bt==0: add(pluck(N(root+12),be*2,0.3),t,0.25)
            if bt in (0,2): add(bass(N(root),be*1.2,1.1),t,0.35)
            if not intro:
                add(bongo(330,0.22 if bt%2 else 0.3),t+be/2,pan=0.35)
                if bt==3: add(bongo(250,0.25),t+be*0.75,pan=0.35)
                for k in range(2): add(shaker(0.16),t+k*be/2,pan=-0.35)
    L=L[:int(SR*dur)]; L=hp(L.T,35).T
    L=L/(np.percentile(np.abs(L),99.9)+1e-9)*0.5; L=np.tanh(L*1.2)/np.tanh(1.2)*0.6
    t=np.arange(len(L))/SR; fi=np.clip(t/0.4,0,1)*np.clip((dur-t)/1.2,0,1); return L*fi[:,None]
if __name__=='__main__':
    import wave
    st,d,o=sys.argv[1],float(sys.argv[2]),sys.argv[3]; sd=int(sys.argv[4]) if len(sys.argv)>4 else 1
    x=generer(st,d,sd); y=(np.clip(x,-1,1)*32767).astype(np.int16)
    w=wave.open(o,'wb'); w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(y.tobytes()); w.close(); print(o,st,d)
