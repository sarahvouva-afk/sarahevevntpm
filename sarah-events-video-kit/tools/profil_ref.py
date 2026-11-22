# Même mesure que celle faite dans le navigateur sur le reel de référence de l'auteur (référence) : puissance par bande
# (somme, trames de 4096, fenêtre de Hann) sur les trames où quelqu'un parle, rapportée à la bande 500–1000 Hz.
import sys,wave,numpy as np
REF={'profil':[-17.9,-2.8,2.2,0,-10,-20.3,-28,-42.9],'clarte':-23.0,'ecart_voix_fond':17.3,'p90':-12.5,'p50':-18.5}
def profil(path,a=None,b=None):
    w=wave.open(path); sr=w.getframerate(); ch=w.getnchannels()
    if a is not None: w.setpos(int(a*sr)); n=int((b-a)*sr)
    else: n=w.getnframes()
    x=np.frombuffer(w.readframes(n),dtype=np.int16).reshape(-1,ch).mean(1)/32768
    hop=int(sr*0.02); nf=len(x)//hop; e=10*np.log10(np.mean(x[:nf*hop].reshape(nf,hop)**2,axis=1)+1e-12)
    fl=np.percentile(e,5); vx=np.percentile(e,90); thr=fl+0.6*(vx-fl); N=4096; win=np.hanning(N)
    B=[(50,120),(120,250),(250,500),(500,1000),(1000,2000),(2000,4000),(4000,8000),(8000,16000)]; acc=np.zeros(8); accN=np.zeros(8); c=cN=0
    for s in range(0,len(x)-N,N//2):
        k=min(nf-1,(s+N//2)//hop); v=e[k]>thr; q=e[k]<fl+3
        if not (v or q): continue
        P=np.abs(np.fft.rfft(x[s:s+N]*win))**2; bp=np.array([P[int(round(f0*N/sr)):int(round(f1*N/sr))].sum() for f0,f1 in B])
        if v: acc+=bp; c+=1
        else: accN+=bp; cN+=1
    lv=10*np.log10(acc/c+1e-20)
    return {'profil':[round(float(v-lv[3]),1) for v in lv],'clarte':round(float(10*np.log10((acc[5]+acc[6])/(acc[1]+acc[2]))),1),'ecart_voix_fond':round(float(10*np.log10(acc.sum()/c)-10*np.log10(accN.sum()/max(1,cN)+1e-20)),1),'p90':round(float(vx),1),'p50':round(float(np.percentile(e,50)),1)}
if __name__=='__main__':
    print('référence (reel de référence) :',REF)
    for p in sys.argv[1:]: print(p,profil(p))
