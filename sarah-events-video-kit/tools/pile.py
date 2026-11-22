# PILE DÉROULANTE de petites captures (l'auteur, 04/10/2026 : « les screens, mets-les en plus petit, les mets pas en gros ; quand c'est
# des messages WhatsApp, de paiement, fais des trucs déroulants, des trucs dynamiques »). Sert aux reels conférence (cv/fin.py), aux
# reels et au long de la séance (d54) et aux reels modules. Une tuile = (bgr float32, alpha HxWx1, ombre) ; la plus récente est en
# bas ; chaque nouvelle tuile entre par le bas (léger grossissement) et pousse les autres vers le haut ; ce qui dépasse la limite
# haute s'efface ; toute la pile s'efface à la fin.
import cv2,numpy as np
GAP=14
ease=lambda x:1-(1-min(1,max(0,x)))**3
def make(im,wd,radius=26,pad=14):
    """image (bgr uint8, déjà recadrée et floutée) -> tuile de largeur wd : marge sombre, coins arrondis, liseré clair, ombre"""
    h,w=im.shape[:2]; s=wd/w; H=int(round(h*s))
    if s>1.05:
        im=cv2.resize(im,(wd,H),interpolation=cv2.INTER_LANCZOS4); bl=cv2.GaussianBlur(im,(0,0),1.6); im=cv2.addWeighted(im,1.6,bl,-0.6,0)
    else: im=cv2.resize(im,(wd,H),interpolation=cv2.INTER_AREA)
    canvas=np.zeros((H+2*pad,wd+2*pad,3),np.uint8); canvas[:]=im.reshape(-1,3).mean(0)*0.55
    canvas[pad:pad+H,pad:pad+wd]=im; Hc,Wc=canvas.shape[:2]
    a=np.zeros((Hc,Wc),np.uint8); cv2.rectangle(a,(radius,0),(Wc-radius,Hc),255,-1); cv2.rectangle(a,(0,radius),(Wc,Hc-radius),255,-1)
    for cx,cy in ((radius,radius),(Wc-radius-1,radius),(radius,Hc-radius-1),(Wc-radius-1,Hc-radius-1)): cv2.circle(a,(cx,cy),radius,255,-1,cv2.LINE_AA)
    a=cv2.GaussianBlur(a,(0,0),0.8).astype(np.float32)/255
    edge=cv2.GaussianBlur((a>0.5).astype(np.float32),(0,0),1.2); ring=np.clip(1-np.abs(edge-0.5)*6,0,1)*0.22
    bgr=canvas.astype(np.float32)*(1-ring[:,:,None])+255*ring[:,:,None]
    M=40; sh=np.zeros((Hc+2*M,Wc+2*M),np.float32); sh[M+10:M+10+Hc,M:M+Wc]=a; sh=cv2.GaussianBlur(sh,(0,0),16)*0.6
    return bgr,a[:,:,None],sh
def blit(dst,bgr,a,x0,y0,alpha):
    h,w=bgr.shape[:2]; xa=max(0,x0); ya=max(0,y0); xb=min(dst.shape[1],x0+w); yb=min(dst.shape[0],y0+h)
    if xa>=xb or ya>=yb or alpha<=0.003: return
    al=a[ya-y0:yb-y0,xa-x0:xb-x0]*alpha; reg=dst[ya:yb,xa:xb].astype(np.float32); dst[ya:yb,xa:xb]=(reg*(1-al)+bgr[ya-y0:yb-y0,xa-x0:xb-x0]*al+0.5).astype(np.uint8)
def draw(im,items,t,t1,haut,bas=1262,cx=540,dx=34,fondu=120.0):
    """items : [(instant d'entrée, tuile)] dans l'ordre ; t1 : fin de la pile ; haut / bas : limites verticales ; cx : centre horizontal"""
    out=min(1.0,max(0.0,(t1+0.28-t)/0.28)); vis=[(k,x) for k,x in enumerate(items) if x[0]<=t]
    for n,(k,(te,tl)) in enumerate(vis):
        bgr,a,sh=tl; h,w=bgr.shape[:2]; ent=ease((t-te)/0.30)
        off=sum((x2[1][0].shape[0]+GAP)*ease((t-x2[0])/0.34) for _,x2 in vis[n+1:])
        yb=bas-off+(1-ent)*54; y0=int(round(yb-h)); al=ent*out*min(1.0,max(0.0,(y0-(haut-fondu))/fondu))
        if al<=0.003: continue
        x0=int(round(cx-w/2+(-dx if k%2==0 else dx)))
        if ent<0.999:
            z=0.90+0.10*ent; w2=int(w*z)//2*2; h2=int(h*z); b2=cv2.resize(bgr,(w2,h2),interpolation=cv2.INTER_AREA); a2=cv2.resize(a,(w2,h2),interpolation=cv2.INTER_AREA)[:,:,None]
            blit(im,b2,a2,x0+(w-w2)//2,y0+(h-h2),al)
        else:
            M=40; blit(im,np.zeros((sh.shape[0],sh.shape[1],3),np.float32),sh[:,:,None],x0-M,y0-M,al); blit(im,bgr,a,x0,y0,al)
