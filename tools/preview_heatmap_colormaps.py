#!/usr/bin/env python3
"""Generate an offline color-map review page from the shipping registry.

This authoring tool may use the Qt adapter to include legacy/native maps.
The application never reads this script or its generated HTML.
"""
from __future__ import annotations

import argparse
import html
from importlib import resources
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_preview(colormap_id: str) -> str:
    from mf4_analyzer.colormaps import get_colormap_spec, load_rgb_lut
    from mf4_analyzer.qt_analysis_shared import _resolve_colormap

    spec = get_colormap_spec(colormap_id)
    if spec.provider == "rgb_lut":
        colors = load_rgb_lut(spec.id)
        source = json.loads(resources.files("mf4_analyzer.colormaps").joinpath(
            "resources", *spec.file.split("/"),
        ).read_text(encoding="utf-8"))
        evidence = source["evidence_level"]
        source_note = source["source_note"]
    else:
        colors = _resolve_colormap(spec.id).getLookupTable(
            0.0, 1.0, 256, alpha=False,
        ).tolist()
        evidence = "existing_provider"
        source_note = spec.provider
    baseline = _resolve_colormap("gnuplot2").getLookupTable(
        0.0, 1.0, 256, alpha=False,
    ).tolist()
    data = dict(id=spec.id, label=spec.label, rgb=colors, baseline=baseline,
                evidence_level=evidence, source_note=source_note)
    # Labels remain data even if an author accidentally includes HTML/script text.
    encoded = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return TEMPLATE.replace("__LABEL__", html.escape(spec.label)).replace(
        "__DATA__", encoded,
    )


TEMPLATE = r'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>色表校验 · __LABEL__</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f2f5f8;color:#243950;font:15px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}header{background:#132a4a;color:white;padding:25px max(24px,calc((100vw - 1200px)/2))}header h1{font-size:24px;margin:0}header p{color:#c4d1df;margin:4px 0 0;font-size:13px}main{max-width:1248px;margin:auto;padding:24px}.panel{background:white;border:1px solid #d9e2eb;border-radius:6px;margin-bottom:20px;padding:20px}h2{margin:0 0 12px;font-size:17px}button,input,select{font:inherit}button{background:white;color:#253950;border:1px solid #b7c8da;border-radius:4px;padding:6px 12px;cursor:pointer}button:hover,button.active{background:#173859;color:white}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #79a8df;outline-offset:2px}input[type=number]{width:86px;padding:5px;border:1px solid #b7c8da;border-radius:3px}.controls{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:20px}.fields{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.bar{height:32px;width:100%;display:block;border:1px solid #d4dde7}.bar-label{display:flex;justify-content:space-between;gap:12px;margin:14px 0 5px}.ticks{display:flex;justify-content:space-between;color:#63788d;font-size:12px;font-variant-numeric:tabular-nums}.probe{display:flex;gap:22px;flex-wrap:wrap;margin-top:16px;align-items:center}.probe input{width:250px;accent-color:#245fb0}.chip{display:inline-block;width:24px;height:24px;vertical-align:middle;border:1px solid #cdd7e3;margin-right:7px}.small{font-size:12px;color:#61758a}.error{color:#b13725;font-size:13px}.plots{display:grid;grid-template-columns:1fr 1fr;gap:22px}.heat{display:block;width:100%;height:245px;background:black}.plot-axis{display:flex;justify-content:space-between;font-size:12px;color:#61758a}.plot-title{display:flex;justify-content:space-between;margin-bottom:8px}#curve{width:100%;height:220px;display:block}.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:12px}.legend i{display:inline-block;width:18px;height:3px;margin-right:5px;vertical-align:middle}.footer{font-size:12px;color:#61758a}.id{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;overflow-wrap:anywhere}@media(max-width:700px){main{padding:14px}.panel{padding:14px}.plots{grid-template-columns:1fr}.probe{gap:10px}.probe input{width:100%}header{padding:20px}.bar-label{flex-wrap:wrap}}
</style>
<header><h1>色表与过渡区域校验</h1><p>从 TraceLab 正式色表目录生成 · 离线预览</p></header>
<main><section class="panel"><h2>__LABEL__</h2><p class="id" id="identity"></p>
<div class="controls"><button data-low="10" data-high="40" class="active">10～40 dB</button><button data-low="20" data-high="50">20～50 dB</button><button data-low="0" data-high="50">0～50 dB</button><form class="fields" id="rangeForm"><label>下限 <input type="number" id="low" value="10" step="any" required></label><label>上限 <input type="number" id="high" value="40" step="any" required></label><button>应用范围</button></form><span id="error" class="error" role="alert"></span></div>
<div class="bar-label"><strong>所选色表</strong><span class="small">完整 256 色数据</span></div><canvas id="selectedRamp" class="bar" aria-label="所选色表渐变"></canvas><div class="ticks" data-ticks></div>
<div class="bar-label"><strong>gnuplot2</strong><span class="small">旧版默认配色，保留用于对照</span></div><canvas id="baselineRamp" class="bar" aria-label="gnuplot2 渐变"></canvas><div class="ticks" data-ticks></div>
<div class="probe"><label for="position">位置 <strong id="positionText">50.0%</strong></label><input type="range" id="position" min="0" max="1000" value="500"><strong id="dbText"></strong><span><i class="chip" id="selectedChip"></i><span id="selectedRGB"></span></span><span><i class="chip" id="baselineChip"></i><span id="baselineRGB"></span></span></div><p class="small">切换范围后，渐变本身不变。同一相对位置始终对应同一颜色。拖动滑块或移动到色条上可检查过渡。</p></section>
<section class="panel"><h2>同一份合成数据</h2><p class="small">频率从下到上为 0～2000 Hz；合成数据固定，不是原始测量结果。切换色阶只改变颜色。</p><div class="plots"><div><div class="plot-title"><strong>所选色表</strong><span class="small">频率 / Hz</span></div><canvas id="selectedHeat" class="heat" aria-label="所选色表合成时频图"></canvas><div class="plot-axis"><span>0</span><span>10</span><span>20</span><span>30</span><span>40</span><span>50 s</span></div></div><div><div class="plot-title"><strong>gnuplot2</strong><span class="small">频率 / Hz</span></div><canvas id="baselineHeat" class="heat" aria-label="gnuplot2 合成时频图"></canvas><div class="plot-axis"><span>0</span><span>10</span><span>20</span><span>30</span><span>40</span><span>50 s</span></div></div></div></section>
<section class="panel"><h2>RGB 过渡曲线</h2><div class="legend"><span><i style="background:#c33d49"></i>R 红</span><span><i style="background:#2b8054"></i>G 绿</span><span><i style="background:#366acf"></i>B 蓝</span><span>实线：所选色表</span><span>虚线：gnuplot2</span></div><canvas id="curve" aria-label="完整 RGB 过渡曲线"></canvas><p class="small">横轴为归一化位置，纵轴为 RGB 分量 0～255。预览通过 RGB 插值展示渐变；Qt 实际图像仍须单独验证采样、色条和像素输出。</p></section>
<p class="footer" id="source"></p><p class="footer">这里的预览和数据一致性不等同于官方匹配认证。screenshot_approximation 表示截图重建，未验证与官方原始 LUT 精确一致。</p></main>
<script id="palette-data" type="application/json">__DATA__</script>
<script>
'use strict';
const data=JSON.parse(document.getElementById('palette-data').textContent),$=id=>document.getElementById(id),state={lo:10,hi:40,t:.5};
$('source').textContent=data.evidence_level+' · '+data.source_note;
const clamp=x=>Math.max(0,Math.min(1,x));
function rgb(lut,t){const z=clamp(t)*(lut.length-1),i=Math.floor(z),j=Math.min(i+1,lut.length-1);return lut[i].map((v,c)=>Math.round(v+(lut[j][c]-v)*(z-i)));}
const palettes={selected:data.rgb,baseline:data.baseline},W=400,H=190,values=new Float64Array(W*H);let seed=8761;
function random(){seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;}
for(let y=0;y<H;y++)for(let x=0;x<W;x++){const t=50*x/(W-1),f=(1-y/(H-1))*2000,on=1/(1+Math.exp(-(t-21)*2));let p=10**((2+11*random()+4*on)/10);for(let k=1;k<7;k++){const center=k*(90+4*t+20*Math.sin(t*.5));p+=10**((31-2*k+7*on)/10)*Math.exp(-.5*((f-center)/(8+2*k))**2);}for(const c of [28,34,40,46,49])p+=10**(39/10)*Math.exp(-.5*((t-c)/.5)**2)*Math.exp(-.5*((f-650)/350)**2);values[y*W+x]=10*Math.log10(p);}
function drawRamp(key){const c=$(key+'Ramp');c.width=1024;c.height=1;const ctx=c.getContext('2d'),im=ctx.createImageData(1024,1);for(let i=0;i<1024;i++)im.data.set([...rgb(palettes[key],i/1023),255],i*4);ctx.putImageData(im,0,0);}
function drawHeat(key){const c=$(key+'Heat');c.width=W;c.height=H;const ctx=c.getContext('2d'),im=ctx.createImageData(W,H);values.forEach((v,i)=>im.data.set([...rgb(palettes[key],(v-state.lo)/(state.hi-state.lo)),255],4*i));ctx.putImageData(im,0,0);}
function drawCurve(){const c=$('curve'),w=c.clientWidth,h=220,d=window.devicePixelRatio||1;c.width=Math.round(w*d);c.height=Math.round(h*d);const ctx=c.getContext('2d');ctx.scale(d,d);const left=34,right=w-12,top=12,bottom=h-26;ctx.font='11px sans-serif';ctx.fillStyle='#61758a';for(const v of [0,64,128,192,255]){const y=bottom-v/255*(bottom-top);ctx.strokeStyle='#e1e7ef';ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke();ctx.fillText(v,2,y+4);}for(const t of [0,.25,.5,.75,1])ctx.fillText(t*100+'%',left+t*(right-left)-7,h-5);for(const key of ['baseline','selected'])for(let channel=0;channel<3;channel++){ctx.strokeStyle=['#c33d49','#2b8054','#366acf'][channel];ctx.globalAlpha=key==='selected'?1:.5;ctx.setLineDash(key==='selected'?[]:[5,4]);ctx.lineWidth=key==='selected'?2:1;ctx.beginPath();palettes[key].forEach((v,i)=>{const x=left+i/255*(right-left),y=bottom-v[channel]/255*(bottom-top);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();}ctx.globalAlpha=1;ctx.setLineDash([]);ctx.strokeStyle='#8c9bad';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(left+state.t*(right-left),top);ctx.lineTo(left+state.t*(right-left),bottom);ctx.stroke();}
function updateProbe(){$('position').value=state.t*1000;$('positionText').textContent=(state.t*100).toFixed(1)+'%';$('dbText').textContent=(state.lo+state.t*(state.hi-state.lo)).toFixed(2)+' dB';for(const key of Object.keys(palettes)){const v=rgb(palettes[key],state.t);$(key+'Chip').style.background='rgb('+v.join(',')+')';$(key+'RGB').textContent=v.join(', ');}drawCurve();}
function setRange(lo,hi){if(!Number.isFinite(lo)||!Number.isFinite(hi)||lo>=hi||!Number.isFinite(hi-lo)){$('error').textContent='下限必须小于上限，且均为有限数值。';return;}state.lo=lo;state.hi=hi;$('low').value=lo;$('high').value=hi;$('error').textContent='';document.querySelectorAll('[data-low]').forEach(b=>b.classList.toggle('active',Number(b.dataset.low)===lo&&Number(b.dataset.high)===hi));document.querySelectorAll('[data-ticks]').forEach(el=>el.replaceChildren(...Array.from({length:6},(_,i)=>{const s=document.createElement('span');s.textContent=Number((lo+i/5*(hi-lo)).toFixed(2))+(i===5?' dB':'');return s;})));Object.keys(palettes).forEach(drawHeat);updateProbe();}
$('identity').textContent=data.id;$('rangeForm').addEventListener('submit',e=>{e.preventDefault();setRange($('low').valueAsNumber,$('high').valueAsNumber);});document.querySelectorAll('[data-low]').forEach(b=>b.addEventListener('click',()=>setRange(Number(b.dataset.low),Number(b.dataset.high))));$('position').addEventListener('input',()=>{state.t=Number($('position').value)/1000;updateProbe();});Object.keys(palettes).forEach(key=>{drawRamp(key);$(key+'Ramp').addEventListener('pointermove',e=>{const b=e.currentTarget.getBoundingClientRect();state.t=clamp((e.clientX-b.left)/b.width);updateProbe();});});window.addEventListener('resize',drawCurve);setRange(10,40);
</script></html>
'''


def main(argv: list[str] | None = None) -> int:
    from mf4_analyzer.colormaps import (
        ColormapResourceError, DEFAULT_HEATMAP_CMAP, UnknownColormapError,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", default=DEFAULT_HEATMAP_CMAP, dest="colormap_id")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        page = build_preview(args.colormap_id)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(page, encoding="utf-8")
    except (UnknownColormapError, ColormapResourceError, OSError) as exc:
        print(f"Color-map preview failed: {exc}", file=sys.stderr)
        return 1
    print(f"Created {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
