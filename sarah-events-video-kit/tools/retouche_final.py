#!/usr/bin/env python3
# RETOUCHE D'UN FINAL (règle 15 : « si seul le final existe, on modifie le final lui-même ») — 08/10/2026.
# Retire des plages du final (blancs, « bah », « euh », reprises) sans rien remonter : image coupée à l'image près, son recollé en fondus
# enchaînés de 30 ms. Les sous-titres, titres, cartes et sons déjà incrustés restent tels quels (un tic n'est jamais sous-titré, un blanc
# n'a pas de sous-titre). Limite : le fond musical saute légèrement à chaque coupe (à écouter, le dire dans la fiche).
#   python3 tools/retouche_final.py <final.mp4> <coupes.json> <sortie.mp4>
#   coupes.json : {"coupes": [[début, fin, "raison"], …], "gains": [[début, fin, dB, "raison"], …]}  (secondes du final AVANT coupes ;
#   un gain remonte un passage dit tout bas, avec des rampes de 50 ms ; la motion de fin n'est jamais touchée)
import sys,json,subprocess,os
src,cj,dst=sys.argv[1:4]; J=json.load(open(cj)); C=sorted(J.get('coupes',[])); GN=J.get('gains',[])
pr=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','stream=codec_type,r_frame_rate:format=duration','-of','json',src]))
fps=[eval(s['r_frame_rate']) for s in pr['streams'] if s['codec_type']=='video'][0]; dur=float(pr['format']['duration'])
fr=lambda t:round(t*fps)/fps
keep=[]; cur=0.0
for a,b,_ in C:
    a,b=fr(a),fr(b)
    if a>cur: keep.append((cur,a))
    cur=max(cur,b)
keep.append((cur,dur))
n=len(keep)
gexp='1'+''.join(f"+({10**(g/20)-1:.4f})*clip((t-{a:.3f})/0.05,0,1)*clip(({b:.3f}-t)/0.05,0,1)" for a,b,g,*_ in GN)
if n>1: pre=f"[0:v]split={n}"+''.join(f"[sv{i}]" for i in range(n))+f";[0:a]volume='{gexp}':eval=frame,asplit={n}"+''.join(f"[sa{i}]" for i in range(n))+";"
else: pre=f"[0:v]null[sv0];[0:a]volume='{gexp}':eval=frame[sa0];"
v=''.join(f"[sv{i}]trim=start={a:.5f}:end={b:.5f},setpts=PTS-STARTPTS[v{i}];" for i,(a,b) in enumerate(keep))
au=''.join(f"[sa{i}]atrim=start={a:.5f}:end={b+(0.03 if i<len(keep)-1 else 0):.5f},asetpts=PTS-STARTPTS[a{i}];" for i,(a,b) in enumerate(keep))
vc=''.join(f"[v{i}]" for i in range(len(keep)))+f"concat=n={len(keep)}:v=1:a=0[vo];"
ac='[a0]'; chain=''
for i in range(1,len(keep)):
    o=f'x{i}' if i<len(keep)-1 else 'ao'; chain+=f"{ac}[a{i}]acrossfade=d=0.03:c1=tri:c2=tri[{o}];"; ac=f'[{o}]'
if len(keep)==1: chain="[a0]anull[ao];"
fc=pre+v+au+vc+chain.rstrip(';')
subprocess.run(['ffmpeg','-y','-v','error','-i',src,'-filter_complex',fc,'-map','[vo]','-map','[ao]','-c:v','libx264','-preset','faster','-crf','19',
                '-maxrate','4600k','-bufsize','9200k','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-ar','48000','-movflags','+faststart',dst],check=True)
nd=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',dst]))
print(f"{os.path.basename(dst)} : {len(C)} coupe(s), {dur:.2f} s -> {nd:.2f} s (retiré {dur-nd:.2f} s)")
