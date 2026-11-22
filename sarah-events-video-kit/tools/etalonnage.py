# Étalonnage référence. v2 « premium » (l'auteur, 04/10/2026, référence : son reel référence, mesuré image par image :
# peau R 90 / V 54 / B 26, blancs du tee-shirt 148 / 141 / 130 soit 58 %, noirs à 7–10, eau turquoise désaturée 52 / 95 / 91).
# On s'en approche autant qu'un plan de jour le permet : exposition basse, blancs crème vers 72 %, noirs denses, peau brun
# chaud profond, bleus tirés vers le turquoise et calmés, léger vignettage.
import numpy as np, cv2
from scipy.interpolate import PchipInterpolator
def make(gr=1.02,gg=0.985,gb=0.88,pts=((0,0),(0.25,0.21),(0.5,0.455),(0.75,0.70),(1,0.90)),sat=1.12,teal=0.0,vig=0.0,size=None):
    x=np.arange(256)/255.0; px,py=zip(*pts); cv=PchipInterpolator(px,py); lut=np.zeros((256,1,3),np.uint8)
    for c,g in enumerate((gb,gg,gr)): lut[:,0,c]=np.clip(cv(np.clip(x*g,0,1))*255+0.5,0,255).astype(np.uint8)
    w=np.array([0.114,0.587,0.299]); M=sat*np.eye(3)+(1-sat)*np.tile(w,(3,1))
    if teal: T=np.eye(3); T[0]=[1-teal,teal,0]; M=T@M            # bleu tiré vers le vert : ciel et ombres turquoise, moins saturés
    V=None
    if vig and size:
        W,H=size; yy,xx=np.mgrid[0:H,0:W].astype(np.float32); r=np.sqrt(((xx-W/2)/(W/2))**2+((yy-H/2)/(H/2))**2)/np.sqrt(2)
        V=(1-vig*np.clip((r-0.45)/0.55,0,1)**2).astype(np.float32)[:,:,None]
    return lut,M.astype(np.float32),V
PREMIUM=dict(gr=1.03,gg=0.96,gb=0.81,sat=1.10,teal=0.14,vig=0.22,pts=((0,0.015),(0.12,0.06),(0.25,0.155),(0.5,0.385),(0.75,0.60),(1,0.76)))
FROID=dict(gr=0.90,gg=0.99,gb=0.93,sat=0.80,teal=0.30,vig=0.0,pts=((0,0.015),(0.12,0.06),(0.25,0.155),(0.5,0.385),(0.75,0.60),(1,0.76)))
def premium(size):
    """étalonnage premium : chaud partout, sauf ce qui était bleu à l'origine (ciel, casquette) qui part en turquoise calme"""
    return ('premium',make(size=size,**PREMIUM),make(**FROID))
def apply(im,G):
    if isinstance(G[0],str):
        _,Gw,Gc=G; lut,M,V=Gw; w=cv2.transform(cv2.LUT(im,lut),M); c=cv2.transform(cv2.LUT(im,Gc[0]),Gc[1])
        b,g,r=cv2.split(im); m=np.clip((b.astype(np.float32)-r.astype(np.float32)-6)/36.0,0,1); m=cv2.GaussianBlur(m,(0,0),3)[:,:,None]*0.85
        y=w.astype(np.float32)*(1-m)+c.astype(np.float32)*m
        if V is not None and V.shape[:2]==y.shape[:2]: y*=V
        return np.clip(y+0.5,0,255).astype(np.uint8)
    lut,M,V=G[0],G[1],(G[2] if len(G)>2 else None); y=cv2.transform(cv2.LUT(im,lut),M)
    if V is not None and V.shape[:2]==y.shape[:2]: y=(y.astype(np.float32)*V+0.5).astype(np.uint8)
    return y
