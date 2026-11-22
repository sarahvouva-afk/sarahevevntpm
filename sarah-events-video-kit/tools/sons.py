# SONS des formats courts référence (l'auteur, 04/10/2026 : « t'as pas mis trop de sons, inspire-toi de ce qui se fait »).
# Tout est SYNTHÉTISÉ ici (numpy / scipy) : aucun fichier externe, aucun droit. Deux familles :
#   - un FOND musical discret et continu (nappe + basse + pulsation), posé nettement sous la voix ;
#   - des EFFETS courts, chacun lié à ce qui se passe à l'image (règle 26 de PERSONNALISATION.md ; mesures de référence dans clients/return/exemples/HOOKS.md).
# Repères MESURÉS sur les reels de référence (clients/return/exemples/HOOKS.md, même mesure que mesure() ci-dessous) :
#   un créateur de référence : fond continu (98 % du temps), voix 18,5 dB au-dessus du fond, un coup grave toutes les ~1,9 s
#   Hans Kadss  : fond continu (100 %), 22,5 dB, un coup toutes les ~3,8 s, fond chargé en graves
#   jean_hdr    : fond présent 75 % du temps, 26,7 dB, 7 coups dans les 5 premières secondes (hook), puis un toutes les ~3 s
#   Matis Clouet (natif) : pas de fond (45 %), 36,8 dB, un effet toutes les ~7 s
# Réglage référence : fond continu, voix 21 dB au-dessus (bande 250–4000 Hz), un effet toutes les 1,5 à 2,5 s, hook plus dense.
import numpy as np, wave
from scipy.signal import butter, sosfilt, sosfiltfilt
SR=48000
def _t(d): return np.arange(int(SR*d))/SR
def _bp(x,lo,hi,o=2): return sosfilt(butter(o,[lo,hi],btype='band',fs=SR,output='sos'),x)
def _lp(x,f,o=2): return sosfilt(butter(o,f,btype='low',fs=SR,output='sos'),x)
def _hp(x,f,o=2): return sosfilt(butter(o,f,btype='high',fs=SR,output='sos'),x)
def _st(x,w=0.0,rng=None):
    """mono -> stéréo ; w = largeur (léger décalage entre les canaux)"""
    if w<=0: return np.stack([x,x],1)
    d=int(SR*0.0006*w*10); r=np.concatenate([np.zeros(d),x[:-d]]) if d else x; return np.stack([x,0.85*r+0.15*x],1)
_rng=np.random.default_rng(11)
def impact():
    t=_t(0.9); x=0.55*np.sin(2*np.pi*(78*t-24*t*t))*np.exp(-5.5*t)+0.2*np.sin(2*np.pi*170*t)*np.exp(-16*t)
    c=_bp(_rng.standard_normal(len(t)),900,5000)*np.exp(-140*t)*0.07; return _st(x+c)      # presque rien au-dessus de 300 Hz : la voix démarre à la première image, l'impact ne doit pas couvrir le premier mot (écoute Whisper du 04/10)
def boom():
    """coup grave long, pour la bascule hook -> corps"""
    t=_t(1.6); f=58*np.exp(-0.9*t)+34; ph=2*np.pi*np.cumsum(f)/SR; x=0.7*np.sin(ph)*np.exp(-2.6*t)*np.minimum(1,t/0.004)
    n=_lp(_rng.standard_normal(len(t)),260)*np.exp(-12*t)*0.3; return _st(x+n,0.5)      # queue courte et grave : au-dessus de 300 Hz elle masquait les premiers mots après le hook (écoute Whisper du 04/10)
def whoosh(d=0.5,g=1.0):
    n=int(SR*d); x=_rng.standard_normal(n); t=np.arange(n)/SR; p=t/d
    lo=_bp(x,300,1400); mi=_bp(x,1200,4200); hi=_bp(x,3800,11000)
    y=lo*np.clip(1-2*p,0,1)+mi*np.clip(1-np.abs(2*p-1),0,1)*0.7+hi*np.clip(2*p-1,0,1)*1.3      # creusé entre 1,2 et 4,2 kHz : la zone des consonnes reste à la voix
    env=np.sin(np.pi*np.clip(p,0,1)**0.7)**2; y=y*env*0.5*g
    L=y*(0.35+0.65*(1-p)); R=y*(0.35+0.65*p); return np.stack([L,R],1)
def swish(g=1.0):
    """passage d'air très court, sur un changement de valeur de plan"""
    n=int(SR*0.2); t=np.arange(n)/SR; x=_bp(_rng.standard_normal(n),2500,9000)*np.sin(np.pi*t/0.2)**2*0.3*g; return _st(x,0.6)
def pop():
    t=_t(0.13); return _st(0.3*np.sin(2*np.pi*(760+900*t)*t)*np.exp(-38*t))
def tick():
    t=_t(0.05); x=0.22*np.sin(2*np.pi*2300*t)*np.exp(-160*t)+_hp(_rng.standard_normal(len(t)),5000)*np.exp(-500*t)*0.12; return _st(x)
def ding():
    """arrivée d'un message : deux notes de cloche douces (ré6, sol6)"""
    out=np.zeros(int(SR*0.75))
    for k,(f,dl) in enumerate([(1174.7,0.0),(1568.0,0.085)]):
        t=_t(0.62); x=(np.sin(2*np.pi*f*t)+0.35*np.sin(2*np.pi*2.01*f*t)*np.exp(-9*t)+0.12*np.sin(2*np.pi*3.0*f*t)*np.exp(-16*t))*np.exp(-7.5*t)*np.minimum(1,t/0.003)
        i=int(dl*SR); out[i:i+len(x)]+=x*0.2
    return _st(out,0.4)
def bulle():
    """bulle de message envoyé : glissé court vers l'aigu"""
    t=_t(0.16); f=520+1500*t/0.16; x=0.26*np.sin(2*np.pi*np.cumsum(f)/SR)*np.sin(np.pi*t/0.16)**1.5; return _st(x)
def cash():
    """encaissement : cloche métallique brillante + tintement"""
    t=_t(0.9); x=np.zeros(len(t))
    for f,a,dc in [(2093,1.0,5.5),(3136,0.7,7),(4186,0.55,8),(5274,0.4,10),(6272,0.3,12),(8372,0.2,15)]: x+=a*np.sin(2*np.pi*f*t)*np.exp(-dc*t)
    x*=np.minimum(1,t/0.002)*0.085; c=_hp(_rng.standard_normal(len(t)),6000)*0.06*(np.exp(-60*t)+0.7*np.exp(-60*np.abs(t-0.07))*(t>0.04))
    return _st(x+c,0.5)
def riser(d=0.9,g=1.0):
    n=int(SR*d); t=np.arange(n)/SR; p=t/d; x=_rng.standard_normal(n)
    y=_bp(x,500,3000)*(1-p)+_bp(x,2500,12000)*p; f=180*(4.5**p); s=np.sin(2*np.pi*np.cumsum(f)/SR)*0.25
    env=(p**2.2)*np.clip((d-t)/0.03,0,1); return _st((y*0.45+s)*env*0.5*g,0.7)
def obturateur():
    """déclic d'appareil photo : pour une capture d'écran qui se pose"""
    out=np.zeros(int(SR*0.16))
    for dl,g in [(0.0,1.0),(0.062,0.8)]:
        t=_t(0.03); x=_bp(_rng.standard_normal(len(t)),1500,7000)*np.exp(-150*t)*0.4*g; i=int(dl*SR); out[i:i+len(x)]+=x
    return _st(out)
SFX={'impact':impact,'boom':boom,'whoosh':whoosh,'swish':swish,'pop':pop,'tick':tick,'ding':ding,'bulle':bulle,'cash':cash,'riser':riser,'obturateur':obturateur}

# ------------------------------------------------------------------ FOND MUSICAL
NOTE=lambda m:440.0*2**((m-69)/12)
PROGS={   # (fondamentale de basse en MIDI, notes de la nappe en MIDI) ; 2 mesures par accord
 'la-mineur':[(33,[57,60,64,67]),(29,[57,60,65,69]),(36,[55,60,64,67]),(31,[55,59,62,67])],   # Am7  Fmaj7  C  G
 're-mineur':[(38,[57,62,65,69]),(34,[58,62,65,69]),(29,[57,60,65,69]),(36,[55,60,64,67])],   # Dm   Bb    F  C
 'mi-mineur':[(40,[59,64,67,71]),(36,[60,64,67,71]),(31,[59,62,67,71]),(38,[57,62,66,69])],   # Em   Cmaj7 G  D
}
def fond(dur,bpm=84,prog='la-mineur',drop=3.0,seed=3):
    """Fond musical synthétisé, stéréo, longueur dur (s). Avant 'drop' (fin du hook) : nappe filtrée + basse seulement ;
    après : la pulsation entre (grosse caisse feutrée, contretemps très discrets). Niveau non réglé ici (voir mixer)."""
    rng=np.random.default_rng(seed); n=int(SR*dur); t=np.arange(n)/SR; beat=60.0/bpm; bar=4*beat; ch=PROGS[prog]
    pad=np.zeros((n,2)); bass=np.zeros(n); seg=2*bar; xf=0.6
    for k in range(int(np.ceil(dur/seg))+1):
        root,notes=ch[k%len(ch)]; a=k*seg; i0=max(0,int((a-xf)*SR)); i1=min(n,int((a+seg+xf)*SR))
        if i0>=n: break
        tt=t[i0:i1]-a; env=np.clip((tt+xf)/(2*xf),0,1)*np.clip((seg+xf-tt)/(2*xf),0,1); env=np.sin(env*np.pi/2)**2
        for side,det in ((0,-0.07),(1,0.07)):
            x=np.zeros(i1-i0)
            for m in notes:
                f=NOTE(m)*2**(det/12*(1+0.3*rng.random()))
                for h in range(1,7): x+=np.sin(2*np.pi*f*h*t[i0:i1]+rng.random()*6.28)/h**1.6
            pad[i0:i1,side]+=x*env/len(notes)
        fb=NOTE(root); b=np.sin(2*np.pi*fb*t[i0:i1])+0.25*np.sin(2*np.pi*2*fb*t[i0:i1]); bass[i0:i1]+=b*env
    lfo=0.5+0.5*np.sin(2*np.pi*t/(4*bar)-1.2); cut=_lp(pad,650,2); ope=_lp(pad,1700,2)
    op=np.clip((t-drop)/0.6,0,1)*(0.35+0.4*lfo); pad=cut*(1-op)[:,None]+ope*op[:,None]
    kick=np.zeros(n); hat=np.zeros(n); tk=_t(0.26); kx=np.sin(2*np.pi*(46*tk+ (110-46)*(1-np.exp(-tk*38))/38))*np.exp(-13*tk)*np.minimum(1,tk/0.002)
    th=_t(0.05); nb=int(dur/beat*2)+2
    for j in range(nb):
        tb=j*beat/2
        if tb<drop-0.02 or tb>=dur-0.3: continue
        i=int(tb*SR)
        if j%8 in (0,5): m=min(len(kx),n-i); kick[i:i+m]+=kx[:m]*(1.0 if j%8==0 else 0.7)
        if j%2==1:
            hx=_hp(rng.standard_normal(len(th)),7000)*np.exp(-110*th)*(0.5+0.5*rng.random()); m=min(len(hx),n-i); hat[i:i+m]+=hx[:m]
    # la basse « respire » sur la grosse caisse
    duck=np.ones(n); kenv=np.abs(kick); from scipy.ndimage import maximum_filter1d
    kenv=maximum_filter1d(kenv,int(SR*0.12)); duck=1-0.45*np.clip(kenv/ (kenv.max()+1e-9),0,1)
    # équilibre interne : tout est réglé par rapport à la nappe dans la bande 250–4000 Hz (c'est elle que regler_fond met sous la voix)
    ref=float(np.sqrt(np.mean(bande(pad.mean(1))**2))+1e-9); rb=float(np.sqrt(np.mean(bass**2))+1e-9); hm=float(np.abs(hat).max()+1e-9)
    out=pad+ (bass*duck*(1.5*ref/rb))[:,None]+ (kick*4.5*ref)[:,None]; out[:,0]+=hat*(1.3*ref/hm); out[:,1]+=hat*(1.0*ref/hm)
    out=_hp(out.T,30,2).T
    fi=np.clip(t/0.4,0,1)*np.clip((dur-t)/1.2,0,1); return out*fi[:,None]
def bande(x,lo=250,hi=4000):
    return sosfiltfilt(butter(4,[lo,hi],btype='band',fs=SR,output='sos'),x,axis=0)
def niveau_voix(v):
    """niveau de la voix dans la bande 250–4000 Hz : 90e centile des trames de 20 ms (dB)"""
    m=bande(v.mean(1) if v.ndim==2 else v); hop=int(SR*0.02); k=len(m)//hop; e=10*np.log10(np.mean(m[:k*hop].reshape(k,hop)**2,1)+1e-12); return float(np.percentile(e,90))
def regler_fond(bed,voix,ecart=21.0):
    """met le fond 'ecart' dB sous la voix (bande 250–4000 Hz, niveau moyen du fond contre 90e centile de la voix), et creuse le fond
    entre 1 et 4 kHz (-4 dB) pour laisser la place aux consonnes"""
    dip=sosfilt(butter(2,[1000,4000],btype='band',fs=SR,output='sos'),bed,axis=0); bed=bed-0.37*dip
    lv=niveau_voix(voix); m=bande(bed.mean(1)); lb=10*np.log10(np.mean(m**2)+1e-12); g=10**((lv-ecart-lb)/20); return bed*g, round(lv,1), round(20*np.log10(g),1)
def mesure(x,sr=SR):
    """mêmes mesures que sur les reels de référence : écart voix/fond (bande 250–4000), part du temps où le fond est présent,
    platitude du spectre dans les creux (bas = musical), coups graves (30–90 Hz) et leur rythme"""
    m=x.mean(1) if x.ndim==2 else x; N=2048; H=1024; nf=(len(m)-N)//H; win=np.hanning(N)
    fr=np.lib.stride_tricks.sliding_window_view(m,N)[::H][:nf]*win; P=np.abs(np.fft.rfft(fr,axis=1))**2/(N*N); f=np.fft.rfftfreq(N,1/sr)
    bd=lambda a,b:10*np.log10(P[:,(f>=a)&(f<b)].sum(1)+1e-14); mid=bd(250,4000); sub=bd(30,90)
    m5,m50,m90=np.percentile(mid,[5,50,90]); k=(f>=300)&(f<3000); flat=np.exp(np.mean(np.log(P[:,k]+1e-18),1))/np.mean(P[:,k]+1e-18,1)
    fps=sr/H; w=int(round(fps)); cont=[mid[j:j+w].min()>m90-30 for j in range(0,nf-w,w)]
    s50=np.median(sub); imp=[]
    for j in range(4,nf):
        if sub[j]>s50+12 and sub[j]-min(sub[j-2],sub[j-3],sub[j-4])>9 and (not imp or j/fps-imp[-1]>0.5): imp.append(round(j/fps,1))
    return {'dur':round(len(m)/sr,1),'ecart':round(float(m90-m5),1),'continu':int(round(100*np.mean(cont))) if cont else 0,'platFond':round(float(flat[mid<m5+4].mean()),2),'coups':len(imp),'un_coup_toutes_les_s':round(len(m)/sr/max(1,len(imp)),1)}
def lire(p):
    try:
        w=wave.open(p); x=np.frombuffer(w.readframes(w.getnframes()),dtype=np.int16).reshape(-1,w.getnchannels()).astype(np.float32)/32768; return x
    except wave.Error:      # 06/10/2026 : WAV « étendu » du ffmpeg 9 (format 65534), illisible par wave de Python 3.9 : lu par ffmpeg
        import subprocess
        raw=subprocess.run(['ffmpeg','-loglevel','error','-i',p,'-ar',str(SR),'-ac','2','-f','s16le','-'],capture_output=True,check=True).stdout
        return np.frombuffer(raw,dtype=np.int16).reshape(-1,2).astype(np.float32)/32768
def ecrire(p,x):
    w=wave.open(p,'w'); w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes((np.clip(x,-1,1)*32767).astype(np.int16).tobytes()); w.close()
def politique(evs):
    """règles de niveau tirées de l'écoute Whisper : un passage d'air arrive AVANT le premier mot du plan (0,14 s) et reste discret ; souffle et
    coup grave plafonnés. S'applique à tous les montages (appelée par mixer)."""
    out=[]
    for nom,t,g in evs:
        if nom=='swish': t=t-0.09; g=min(g,0.35)
        elif nom=='whoosh': g=min(g,0.40)
        elif nom=='boom': g=min(g,0.40)
        out.append((nom,max(0.0,t),g))
    return out
def mixer(voix,evs,dur,H=3.0,bpm=84,prog='la-mineur',ecart=21.0,seed=3,avec_fond=True):
    """voix : (n,2) ; evs : [(nom, t, gain)] ; rend le mixage (n,2), le détail du fond et la liste des sons posés"""
    tot=int(round(dur*SR)); A=np.zeros((tot,2),np.float32); m=min(len(voix),tot); A[:m]=voix[:m]; info={}
    if avec_fond:
        bed=fond(dur,bpm=bpm,prog=prog,drop=H,seed=seed); bed,lv,g=regler_fond(bed,voix,ecart); bed=bed[:tot]; A[:len(bed)]+=bed.astype(np.float32); info={'voix_250_4000_dB':lv,'gain_fond_dB':g,'ecart_voulu_dB':ecart,'bpm':bpm,'accords':prog}
    for nom,t,g in politique(evs):
        s=(SFX[nom]()*g).astype(np.float32); i0=max(0,int(t*SR)); s=s[:max(0,tot-i0)]; A[i0:i0+len(s)]+=s
    th=0.80; ov=np.abs(A)>th; A[ov]=np.sign(A[ov])*(th+(0.89-th)*np.tanh((np.abs(A[ov])-th)/(0.89-th)))
    return A,info
if __name__=='__main__':
    import sys
    for p in sys.argv[1:]: print(p,mesure(lire(p)))
