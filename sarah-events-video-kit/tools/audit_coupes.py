#!/usr/bin/env python3
# AUDIT DES COUPES (l'auteur, 30/10/2026 : « des fois tu fais des cuts pas naturels, on voit la personne bouger très vite »).
# Repère les « jump cuts » : une coupe où le décor reste le même (même plan, même cadre) mais la personne saute de position.
# Une vraie coupe de plan (autre cadre, b-roll) change le décor : elle n'est pas signalée. Mesure seulement, n'écoute pas.
#   python3 tools/audit_coupes.py <video.mp4> [--json sortie.json]
import sys,json,subprocess,numpy as np
def frames(p,w=90,h=160):
    r=subprocess.run(['ffmpeg','-v','error','-i',p,'-an','-vf',f'scale={w}:{h},format=gray','-f','rawvideo','-'],capture_output=True).stdout
    fps=subprocess.run(['ffprobe','-v','error','-select_streams','v','-show_entries','stream=r_frame_rate','-of','csv=p=0',p],capture_output=True,text=True).stdout.strip().split('/')
    return np.frombuffer(r,np.uint8).reshape(-1,h,w).astype(np.float32),float(fps[0])/float(fps[1] if len(fps)>1 else 1)
def audit(p):
    F,fps=frames(p); n=len(F); H,Wd=F.shape[1:]
    # zone de la personne : 22 % à 58 % de la hauteur, 10 % à 90 % de la largeur (hors titres en haut, sous-titres et
    # écrans scindés en bas) ; c'est là qu'une coupe sautée se voit (la tête, les épaules, les mains changent de place)
    z0,z1=int(.22*H),int(.58*H); x0,x1=int(.1*Wd),int(.9*Wd)
    Z=F[:,z0:z1,x0:x1]; dz=np.abs(np.diff(Z,axis=0)).mean(axis=(1,2)); med=np.median(dz)+0.5; out=[]
    for i in range(1,n-2):
        if dz[i]<max(5.0,4*med) or dz[i]<dz[i-1]*2.2 or dz[i]<dz[i+1]*2.2: continue      # pic net sur une seule image = coupe
        a,b=F[i],F[i+1]
        ha,_=np.histogram(a,32,(0,255)); hb,_=np.histogram(b,32,(0,255)); hc=np.corrcoef(ha,hb)[0,1]
        m=np.zeros_like(a,bool); m[int(.22*H):int(.58*H),:]=True
        bord=np.abs(a-b)[~m].mean()
        za,zb=a[z0:z1,x0:x1],b[z0:z1,x0:x1]; frac=float((np.abs(za-zb)>25).mean())
        if hc>0.9 and bord<16 and frac>0.06:          # même décor (même plan), mais la personne a bougé d'un coup
            out.append({'t':round((i+1)/fps,2),'zone':round(frac,3),'gravite':'forte' if frac>0.15 else 'moyenne'})
    return out,n/fps
if __name__=='__main__':
    p=sys.argv[1]; o,L=audit(p)
    print(f"{p.split('/')[-1]} — {L:.1f} s — {len(o)} coupe(s) sautée(s)"+(' : '+', '.join(f"{x['t']:.2f} s ({x['gravite']})" for x in o) if o else ''))
    if '--json' in sys.argv: json.dump(o,open(sys.argv[sys.argv.index('--json')+1],'w'))
