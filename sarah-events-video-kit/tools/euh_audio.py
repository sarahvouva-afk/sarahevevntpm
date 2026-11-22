#!/usr/bin/env python3
# Repère les hésitations (« euh… », voyelle tenue) dans le son, là où la transcription ne les écrit pas : une voix présente mais
# un spectre qui ne bouge presque pas pendant plus de 0,28 s. La parole normale change de son toutes les 60 à 120 ms.
#   euh(x, sr) -> [(début, fin)] en secondes
import numpy as np
def euh(x,sr=16000,min_d=0.28):
    hop=int(sr*0.02); n=len(x)//hop
    if n<5: return []
    fr=x[:n*hop].reshape(n,hop)*np.hanning(hop); S=np.abs(np.fft.rfft(fr,512,axis=1))[:,4:120]      # 120 Hz – 3,7 kHz
    rms=20*np.log10(np.sqrt((fr**2).mean(1))+1e-9); voix=rms>np.percentile(rms,40)+3
    L=np.log(S+1e-6); L=L-L.mean(1,keepdims=True); flux=np.sqrt(((L[1:]-L[:-1])**2).mean(1)); flux=np.r_[flux[0],flux]
    seuil=np.percentile(flux[voix],22) if voix.any() else 0
    st=voix&(flux<seuil)
    out=[]; i=0
    while i<n:
        if st[i]:
            j=i
            while j<n and (st[j] or (j+1<n and st[j+1])): j+=1
            if (j-i)*hop/sr>=min_d: out.append((i*hop/sr,j*hop/sr))
            i=j
        else: i+=1
    return out
