/* Shared deck controller for all in-app help guides.
   Fixed 16:9 stage scaling + keyboard/wheel/touch nav + inline editing. */
class Deck{
    constructor(){
        this.slides=[...document.querySelectorAll('.slide')];
        this.i=0;this.stage=document.getElementById('deckStage');
        this.buildNav();
        this.scale();addEventListener('resize',()=>this.scale());this.nav();this.show(0);
    }
    /* bottom-center prev / page / next controls (injected, so every guide gets them) */
    buildNav(){
        const bar=document.createElement('div');bar.className='deck-nav';
        bar.innerHTML='<button class="dn-btn dn-prev" aria-label="上一页">‹</button>'
            +'<span class="dn-count">1 / '+this.slides.length+'</span>'
            +'<button class="dn-btn dn-next" aria-label="下一页">›</button>';
        document.body.appendChild(bar);
        this.count=bar.querySelector('.dn-count');
        this.prevBtn=bar.querySelector('.dn-prev');this.nextBtn=bar.querySelector('.dn-next');
        this.prevBtn.addEventListener('click',()=>this.prev());
        this.nextBtn.addEventListener('click',()=>this.next());
    }
    scale(){const f=Math.min(innerWidth/1920,innerHeight/1080);
        this.stage.style.transform=`translate(${(innerWidth-1920*f)/2}px,${(innerHeight-1080*f)/2}px) scale(${f})`}
    show(n){this.i=Math.max(0,Math.min(n,this.slides.length-1));
        this.slides.forEach((s,k)=>{s.classList.toggle('active',k===this.i);s.classList.toggle('visible',k===this.i)});
        if(this.count){this.count.textContent=(this.i+1)+' / '+this.slides.length;
            this.prevBtn.classList.toggle('off',this.i===0);
            this.nextBtn.classList.toggle('off',this.i===this.slides.length-1)}}
    next(){this.show(this.i+1)}prev(){this.show(this.i-1)}
    nav(){
        addEventListener('keydown',e=>{if(e.target.getAttribute&&e.target.getAttribute('contenteditable'))return;
            if(['ArrowRight','ArrowDown',' ','PageDown'].includes(e.key)){e.preventDefault();this.next()}
            if(['ArrowLeft','ArrowUp','PageUp'].includes(e.key)){e.preventDefault();this.prev()}
            if(e.key==='Home')this.show(0);if(e.key==='End')this.show(this.slides.length-1)});
        let wt=0;addEventListener('wheel',e=>{const t=Date.now();if(t-wt<700)return;if(Math.abs(e.deltaY)<24)return;wt=t;e.deltaY>0?this.next():this.prev()},{passive:true});
        let sx=0;addEventListener('touchstart',e=>{sx=e.touches[0].clientX},{passive:true});
        addEventListener('touchend',e=>{const dx=e.changedTouches[0].clientX-sx;if(Math.abs(dx)>60)dx<0?this.next():this.prev()},{passive:true});
    }
}
new Deck();
/* inline editing — hover top-left corner or press E */
const editor={isActive:false,toggle(){this.isActive=!this.isActive;document.body.classList.toggle('editing',this.isActive);
    const t=document.getElementById('editToggle');if(t)t.classList.toggle('active',this.isActive);
    document.querySelectorAll('.frame *').forEach(el=>{if(el.children.length===0&&el.textContent.trim())el.contentEditable=this.isActive})}};
(function(){const hz=document.querySelector('.edit-hotzone'),et=document.getElementById('editToggle');if(!hz||!et)return;let ht=null;
    hz.addEventListener('mouseenter',()=>{clearTimeout(ht);et.classList.add('show')});
    hz.addEventListener('mouseleave',()=>{ht=setTimeout(()=>{if(!editor.isActive)et.classList.remove('show')},400)});
    et.addEventListener('mouseenter',()=>clearTimeout(ht));
    et.addEventListener('mouseleave',()=>{ht=setTimeout(()=>{if(!editor.isActive)et.classList.remove('show')},400)});
    et.addEventListener('click',()=>editor.toggle());hz.addEventListener('click',()=>editor.toggle());
    addEventListener('keydown',e=>{if((e.key==='e'||e.key==='E')&&!(e.target.getAttribute&&e.target.getAttribute('contenteditable')))editor.toggle()});
})();
