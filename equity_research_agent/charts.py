"""High-resolution financial chart rendering."""
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def font(size,bold=False):
    names=['arialbd.ttf' if bold else 'arial.ttf','DejaVuSans.ttf']
    for name in names:
        try:return ImageFont.truetype(name,max(1,int(size)))
        except OSError:pass
    return ImageFont.load_default()

def color(c,default='#000000'):
    if c is None:return default
    if isinstance(c,(int,float)):return tuple([round(float(c)*255)]*3)
    if isinstance(c,str):return '#FFFFFF' if c=='RGB' else default
    if any(isinstance(v,str) for v in c):return default
    if len(c)==3:return tuple(round(float(v)*255) for v in c)
    if len(c)==4:
        a,b,d,k=c;return tuple(round(255*(1-v)*(1-k)) for v in [a,b,d])
    return default

def redraw(spec,path,scale=5):
    x0,y0,x1,y1=spec['bbox']; im=Image.new('RGB',(round((x1-x0)*scale),round((y1-y0)*scale)),'white'); d=ImageDraw.Draw(im)
    def pt(p):return ((p[0]-x0)*scale,(p[1]-y0)*scale)
    for r in spec['rects']:
        bottom=min(r['bottom'],245.8) if spec['source_page']==4 and x0==40 and r['x0']>170 and r['bottom']>264 else r['bottom']
        box=[(r['x0']-x0)*scale,(r['top']-y0)*scale,(r['x1']-x0)*scale,(bottom-y0)*scale]
        d.rectangle(box,fill=color(r.get('non_stroking_color'),'white') if r['fill'] else None,outline=color(r.get('stroking_color')) if r['stroke'] else None,width=max(1,round(r['linewidth']*scale)))
    for c in spec['curves']:
        if isinstance(c.get('stroking_color'),(int,float)) and c.get('stroking_color')>=.8 and c['height']<15:continue
        points=[]; current=None
        for op in c.get('path',[]):
            if op[0] in ('m','l'):
                current=op[1];points.append(pt(current))
            elif op[0]=='c' and current:
                a=current;b,e,f=op[1:4]
                for i in range(1,17):
                    t=i/16; points.append(pt([((1-t)**3*a[j]+3*(1-t)**2*t*b[j]+3*(1-t)*t*t*e[j]+t**3*f[j]) for j in [0,1]]))
                current=f
            elif op[0]=='h' and points:points.append(points[0])
        if not points:points=[pt(p) for p in c['pts']]
        if len(points)>2 and c['fill']:d.polygon(points,fill=color(c.get('non_stroking_color')))
        if len(points)>1 and c['stroke']:
            if spec.get('plot_bbox') and len(points)>100:
                overlay=Image.new('RGB',im.size,'white');od=ImageDraw.Draw(overlay);od.line(points,fill=color(c.get('stroking_color')),width=max(1,round(c['linewidth']*scale)))
                pb=spec['plot_bbox'];box=tuple(round(v) for v in [pt(pb[:2])[0],pt(pb[:2])[1],pt(pb[2:])[0],pt(pb[2:])[1]])
                im.paste(overlay.crop(box),box);d=ImageDraw.Draw(im)
            else:d.line(points,fill=color(c.get('stroking_color')),width=max(1,round(c['linewidth']*scale)))
    for ln in spec['lines']:
        d.line([( (ln['x0']-x0)*scale,(ln['top']-y0)*scale),((ln['x1']-x0)*scale,(ln['bottom']-y0)*scale)],fill=color(ln.get('stroking_color')),width=max(1,round(ln['linewidth']*scale)))
    for w in spec['words']:
        if spec.get('ylabel') and w['x0']<x0+13:continue
        if spec['source_page']==6 and w['top']>590:continue
        if spec['source_page']==5 and spec['bbox'][1]>500 and w['top']>645:continue
        # Re-typeset labels rather than retaining PDF pixels or embedded institution graphics.
        s=w['text'].replace('��','-').replace('�','-')
        f=font(w['size']*scale,'Bold' in w['fontname']); x=(w['x0']-x0)*scale; y=(w['top']-y0)*scale
        d.text((x,y),s,font=f,fill='#202020',anchor='lt')
    if spec['source_page']==6 or (spec['source_page']==5 and spec['bbox'][1]>500):
        start,end=(2020,2025) if spec['source_page']==6 else (2016,2027)
        for i,year in enumerate(range(start,end+1)):
            d.text(((50-x0+(x1-70)*i/(end-start))*scale,(y1-y0-13)*scale),str(year),font=font(6*scale),fill='#555555')
    if spec.get('ylabel'):
        label=Image.new('RGBA',(round(140*scale),round(12*scale)),(255,255,255,0));ld=ImageDraw.Draw(label);ld.text((0,0),spec['ylabel'],font=font(7*scale),fill='#333333');label=label.rotate(90,expand=True)
        im.paste(label,(0,round((im.height-label.height)/2)),label)
    im.save(path,dpi=(360,360))

def dcf_comparison(model,price,path,currency='USD',as_of='26 Jan 2026'):
    im=Image.new('RGB',(1700,950),'white');d=ImageDraw.Draw(im); blue='#00A6D8'; left,right,top,bottom=170,1550,140,730
    maxv=max(price,max(v['value_per_share'] for v in model.values()))*1.15
    def xx(v):return left+(right-left)*v/maxv
    prefix=currency+' ' if currency in ('CNY','HKD') else '$'
    step=max(1,math.ceil(maxv/6)) if currency=='CNY' else max(50,math.ceil(maxv/6/50)*50)
    for v in range(0,int(maxv)+1,step):
        d.line((xx(v),top,xx(v),bottom),fill='#DDE3E8',width=2);d.text((xx(v),bottom+20),f'{prefix}{v}',font=font(31),anchor='mt',fill='#555555')
    d.line((xx(price),top-35,xx(price),bottom),fill='#EE6B40',width=5)
    d.text((xx(price),top-72),f'Reference close {prefix}{price:.2f}',font=font(31,True),anchor='mt',fill='#B14A25')
    for y,(key,v) in zip([240,440,640],model.items()):
        d.text((30,y),key.upper(),font=font(32,True),anchor='lm',fill='#082C4A')
        d.line((xx(v['value_per_share']),y,xx(price),y),fill='#A5DCF0',width=16)
        d.ellipse((xx(v['value_per_share'])-13,y-13,xx(v['value_per_share'])+13,y+13),fill=blue)
        d.text((xx(v['value_per_share']),y-28),f"{prefix}{v['value_per_share']:.2f} ({v['upside']:+.1%})",font=font(34,True),anchor='mb',fill='#082C4A')
    d.text((left,850),'DCF values as of '+as_of+'; comparison only, no price path or probabilities.',font=font(30),fill='#666666')
    im.save(path,dpi=(360,360))

def build(figures,model,price,dest):
    dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    for ex,spec in figures.items():redraw(spec,dest/f'exhibit_{ex}.png')
    dcf_comparison(model,price,dest/'dcf_comparison.png')
