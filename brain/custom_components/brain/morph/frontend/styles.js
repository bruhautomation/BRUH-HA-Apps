// Morph's stylesheet. The tokens and motion classes are the prototype's
// (docs/design/morph-ui.html); the rest is the structure the prototype wrote
// inline, given names so morph-panel.js can render markup rather than
// style strings.

export const FONTS_URL = 'https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,300;12..96,400;12..96,500&family=Manrope:wght@400;500;600;700&display=swap';

export const CSS = `
:host{display:block;height:100%}
.t-dark{--lpull:#FFFFFF;--indigo:#9DAAF5;--peach:#F2B590;--bg:#0A0C0E;--surface:#15181B;--sunk:#0F1114;--line:rgba(255,255,255,.08);--line2:rgba(255,255,255,.2);--text:#EDEFF1;--muted:#A0A9B3;--quiet:#808994;--chip:rgba(255,255,255,.06);--hover:rgba(255,255,255,.035);--amber:#F4B969;--sand:#E9D3A6;--sky:#9CC2F5;--violet:#BBA6F2;--teal:#63CCC2;--lime:#BCD873;--rose:#F2907F;--ink:#15120D;color-scheme:dark}
.t-medium{--lpull:#FFFFFF;--indigo:#A9B4F2;--peach:#F0BC9C;--bg:#2A2D31;--surface:#34383D;--sunk:#25282C;--line:rgba(255,255,255,.1);--line2:rgba(255,255,255,.22);--text:#F1F2F3;--muted:#B5BCC4;--quiet:#949CA6;--chip:rgba(255,255,255,.07);--hover:rgba(255,255,255,.04);--amber:#F5C27F;--sand:#E6D3AC;--sky:#A7C8F2;--violet:#C3B1F0;--teal:#72CFC6;--lime:#C3DB86;--rose:#F29C8C;--ink:#15120D;color-scheme:dark}
.t-light{--lpull:#3A2E1A;--indigo:#4F5FC4;--peach:#B8622F;--bg:#ECEBE6;--surface:#FFFFFF;--sunk:#E4E3DD;--line:rgba(22,24,27,.1);--line2:rgba(22,24,27,.24);--text:#16181B;--muted:#535A63;--quiet:#68707A;--chip:rgba(22,24,27,.06);--hover:rgba(22,24,27,.03);--amber:#C27A1A;--sand:#9C7F3C;--sky:#3B78C9;--violet:#7A5FD0;--teal:#178A80;--lime:#5E8416;--rose:#C9503F;--ink:#FFFFFF;color-scheme:light}
.morph{--ease:cubic-bezier(.2,.8,.2,1);--ease-io:cubic-bezier(.65,0,.35,1);min-height:100%;background:var(--bg);color:var(--text);font-family:'Manrope',system-ui,sans-serif;font-size:15px;line-height:1.45;-webkit-font-smoothing:antialiased;overflow-anchor:none;box-sizing:border-box}
.morph *{box-sizing:border-box}
.morph h1,.morph h2,.morph h3,.morph p,.morph pre{margin:0}
.morph button,.morph input,.morph textarea,.morph select{font:inherit;color:inherit}
.morph button{-webkit-tap-highlight-color:transparent}
.morph button:focus-visible,.morph input:focus-visible,.morph [tabindex]:focus-visible{outline:2px solid var(--text);outline-offset:2px;border-radius:8px}
.disp{font-family:'Bricolage Grotesque','Manrope',sans-serif}
.wrap{max-width:1440px;margin:0 auto;padding:22px clamp(14px,3vw,44px) 120px;display:flex;flex-direction:column;gap:30px}
/* The scroller holds the page and, on a touch screen, the room rail beside
   it (rail.js): a slim column of notches, one per room, grouped by floor.
   A pull left widens it over the page's edge with the floor names beside
   it, and it is still while open (the owner's request: the notched rail
   itself, a bit wider; no lean, no pop). Its tips are vertical words inside
   it, beside the finger. */
.scroll{display:flex;align-items:flex-start}
.scroll>.wrap{flex:1 1 auto;min-width:0}
.srail{display:none}
@media (any-pointer:coarse){
.scroll>.wrap{padding-right:4px}
.srail{display:block;position:sticky;top:0;z-index:6;flex:0 0 28px;width:28px;height:var(--morph-h,100vh);touch-action:pan-y;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none}
.srpanel{position:absolute;top:0;right:0;bottom:0;width:28px;border-radius:14px 0 0 14px;transition:background .2s ease}
.srail.engaged .srpanel{background:var(--chip)}
.srail.open .srpanel{background:color-mix(in oklab,var(--text) 7%,var(--surface));box-shadow:-1px 0 0 var(--line)}
.srnotches i{position:absolute;right:9px;width:5px;border-radius:2px;opacity:.4}
.srnotches i.on{opacity:1}
.srail.open .srnotches i{opacity:.55}
.srail.open .srnotches i.on{opacity:1;box-shadow:0 0 0 1.5px var(--surface),0 0 0 3px currentColor;color:var(--line2)}
.srfloors span{position:absolute;right:50px;font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;line-height:20px;padding:0 8px;border-radius:10px;color:var(--muted);background:var(--surface);box-shadow:0 0 0 1px var(--line);white-space:nowrap;pointer-events:none}
.srtip{position:absolute;left:1px;writing-mode:vertical-rl;font-size:12px;font-weight:600;line-height:13px;color:var(--text);white-space:nowrap;pointer-events:none}
.srtip span{display:block}
.srtip .srsub{color:var(--muted);font-weight:500}
/* The room the rail is on: ringed and lit in its own colour (--rc), its
   title tinted, the other rooms dimmed. The engine writes opacity inline on
   every room and a room's state paints its own inset edge, so the dim and
   the ring are !important; the ring is inset because a room clips. */
.morph.railing section.sec[data-sec]:not(.railon){opacity:.55!important;transition:opacity .2s ease}
.morph section.sec.railon>.secbg{box-shadow:inset 0 0 0 1.5px color-mix(in oklab,var(--rc) 70%,transparent),inset 0 0 36px color-mix(in oklab,var(--rc) 16%,transparent)!important}
.morph section.sec.railon .sechead h2,.morph section.sec.railon .sechead .sectitle svg{color:var(--rc)}
.morph section.sec .sechead h2{transition:color .3s ease}
}
.bar{display:flex;align-items:center;gap:10px;min-height:44px}
.brand{font-weight:700;font-size:12px;letter-spacing:.24em;display:inline-flex;align-items:center;gap:8px}
.brand svg{color:var(--violet);letter-spacing:0}
.menu{background:none;border:0;padding:0 4px;margin:0;min-height:44px;cursor:pointer;color:var(--muted);display:inline-flex;align-items:center}
.date{font-size:13px;color:var(--quiet);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bartoast{font-size:13px;color:var(--muted);margin-left:12px;min-width:0;flex:0 1 auto}
.toastline{display:flex;align-items:center;min-height:44px;margin:-14px 0 -18px}.toastline .bartoast{margin-left:0}
.morph .editquiet{display:inline-flex;align-items:center;gap:6px;min-height:44px;padding:0 4px;font-size:13px;font-weight:600;color:var(--muted)}
.morph .editquiet:hover{color:var(--text)}
.bar>.go,.bar>.menu,.bar>.brand{flex-shrink:0}
.lede{font-size:13px;color:var(--muted);margin-top:-18px}
.mtile:focus-visible{outline:2px solid var(--text);outline-offset:2px}
/* The verdict (vision §2.1): the first clause in its meaning colour, the
   rest muted, each a jump, underlined 1px at half its colour. */
.morph .vjump{background:none;border:0;padding:0;margin:0;font:inherit;cursor:pointer;text-align:left;color:var(--vc,var(--text));text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:.28em;text-decoration-color:color-mix(in oklab,var(--vc,var(--text)) 50%,transparent)}
.morph .vjump.plain{color:var(--muted)}
.vq{color:var(--quiet);font-size:.6em}
.vthen{color:var(--violet)}
.needbrain{color:var(--text);padding:40px 0}
.topsec{position:relative}
.bigclock{position:absolute;right:0;top:-6px;display:flex;flex-direction:column;align-items:flex-end;color:var(--quiet);font-family:'Bricolage Grotesque','Manrope',sans-serif;pointer-events:none}
.bigclock b{font-size:clamp(56px,8vw,96px);font-weight:200;letter-spacing:-.04em;line-height:1;font-variant-numeric:tabular-nums}
.bigclock span{font-size:clamp(28px,4vw,48px);font-weight:200}
.thenrule{position:sticky;top:0;height:2px;background:var(--violet);z-index:6;transition:width .3s var(--ease)}
/* THEN: the page as it was. Desaturated, and nothing can be pressed. */
.then [data-board]{filter:saturate(.65)}
.then .mtile{cursor:default!important}
/* Still, night and away (§10): the rooms recede, the verdict and Now
   stay; at night the page dims to a floor of 40%. */
.form-still section.sec:not(.nowband),.form-still .flh{opacity:.35;transition:opacity .4s ease}
.form-still h1.hello{font-size:clamp(44px,6vw,64px)}
.form-still .story{font-size:clamp(24px,2.8vw,32px)}
.form-night.night-dim section.sec:not(.nowband),.form-night.night-dim .flh,.form-night.night-dim [data-region="scenes"],.form-night.night-dim [data-region="upcoming"],.form-night.night-dim [data-region="rooms"]{filter:brightness(.8);transition:filter 2s ease}
.form-night.night-dim,.form-night.night-dim .scroll{background:var(--bg)}
.t-light.form-night.night-dim{--bg:var(--sunk)}
.form-away section.sec:not(.nowband){opacity:.6}
/* The Now layer: the page's largest cards, on the surface at full
   opacity, no heading, no border. */
section.sec.nowband .secbg{background:transparent!important}
.mtile.lifted{background:var(--surface)}
.because{font-size:13px;line-height:1.35;padding:0 14px 10px;margin:0;opacity:.8;cursor:default;user-select:none;-webkit-user-select:none}
.sechead.nohead{min-height:0;padding:0}
.sectitle{flex:1;min-width:0;display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;position:relative}
.roomname{background:none;border:0;padding:0;margin:0;font:inherit;color:inherit;cursor:pointer;text-align:left}
.secscenes{display:inline-flex;gap:0 14px;flex-wrap:wrap}
.secscenes .wd{font-size:15px;color:var(--muted);min-height:32px}
.needs{font-size:13px;color:var(--rose);white-space:nowrap}
.trace{background:none;border:0;padding:0;margin:0;font:inherit;font-size:13px;cursor:pointer;min-height:28px;white-space:nowrap}
.secbecause{flex-basis:100%;font-size:13px;margin:-2px 0 0}
/* A header switch (options.header): a pill at the right of a room's title
   row, amber while on; a 44px target on touch. */
.morph .shtog{align-self:center;display:inline-flex;align-items:center;gap:7px;min-height:32px;padding:0 14px;border-radius:999px;border:1px solid var(--line2);background:transparent;color:var(--muted);font-size:13px;font-weight:600;white-space:nowrap;cursor:pointer;flex-shrink:0;transition:background .2s ease,color .2s ease,border-color .2s ease}
.morph .shtog i{width:7px;height:7px;border-radius:50%;box-shadow:inset 0 0 0 1.5px currentColor}
.morph .shtog.on{color:var(--amber);border-color:color-mix(in oklab,var(--amber) 55%,transparent);background:color-mix(in oklab,var(--amber) 16%,transparent)}
.morph .shtog.on i{background:var(--amber);box-shadow:none}
.morph .shtog:disabled{opacity:.45;cursor:default}
@media (pointer:coarse){.morph .shtog{min-height:44px}}
.chip{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--muted);white-space:nowrap}
.chip i{width:6px;height:6px;border-radius:50%;box-shadow:inset 0 0 0 1px var(--line2)}
.chip.on.rose i{background:var(--rose);box-shadow:none}.chip.on.amber i{background:var(--amber);box-shadow:none}
.litline{position:absolute;left:0;bottom:-4px;height:2px;border-radius:1px;background:var(--amber);opacity:.8}
section.sec.folded .sechead{min-height:44px;padding-top:10px;padding-bottom:8px}
section.sec[data-state="asleep"]{opacity:.45}
section.sec[data-state="asleep"] .secmeta{color:var(--indigo)}
section.sec[data-state="asleep"] .mtile{opacity:1}
.flrooms,.roomline{display:flex;flex-wrap:wrap;align-items:baseline;gap:0 14px;margin-top:6px}
.roomw{background:none;border:0;padding:0;margin:0;font:inherit;font-size:13px;cursor:pointer;min-height:30px;display:inline-flex;align-items:center;gap:6px;color:var(--muted)}
.roomw.rs-idle{color:var(--quiet)}.roomw.rs-active,.roomw.rs-occupied,.roomw.rs-attention{color:var(--text)}.roomw.rs-asleep{opacity:.45}
.rdot{width:4px;height:4px;border-radius:50%;background:var(--rose)}
.rlfloor{font-family:'Bricolage Grotesque','Manrope',sans-serif;font-size:18px;font-weight:300;margin-left:6px}
.rlfloor:first-child{margin-left:0}
[data-region="rooms"]{display:none}
@media (max-width:700px){[data-region="rooms"]{display:block;position:sticky;top:0;z-index:5;background:var(--bg);margin:-14px -4px -10px;padding:4px 4px 6px}.roomline{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none;margin-top:0}.roomline::-webkit-scrollbar{display:none}.flrooms{display:none}}
/* A case (§14): claim, ask, a reply line, the words. */
.case{display:flex;flex-direction:column;gap:6px;padding:12px 14px 6px 16px}
.case .claim{font-size:15px;line-height:1.45;color:var(--text)}
.case .caseask{font-size:14px;line-height:1.45;color:var(--muted)}
.casechip{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:var(--muted);letter-spacing:.01em}
.casechip i{width:7px;height:7px;border-radius:50%;background:var(--chip,var(--amber));flex-shrink:0}
.case .casebody{font-size:14px;line-height:1.45;color:var(--muted);display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.caseplan{display:flex;flex-direction:column;gap:2px;padding:6px 0}
.thread{display:flex;flex-direction:column;gap:4px;padding:2px 0}
.turnline{font-size:14px;line-height:1.45}
.turnline.brain{color:var(--muted)}.turnline.you{color:var(--text)}
.replyrow{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.morph .replyin{flex:1 1 200px;min-width:0;background:transparent;border:0;border-bottom:1px solid var(--cc,var(--line2));border-radius:0;padding:8px 0;font-size:16px;color:var(--text);outline:none}
.replyin::placeholder{color:var(--quiet)}
.casewords{display:inline-flex;flex-wrap:wrap;gap:0 14px}
.casewords .wd{font-size:13px;min-height:40px}
.todolist{display:flex;flex-direction:column;padding:2px 10px 8px}
.todorow{display:flex;align-items:center;gap:12px;min-height:44px;padding:6px 6px;border-top:1px solid var(--line);cursor:pointer;touch-action:pan-y;user-select:none;-webkit-user-select:none;transition:transform .2s var(--ease)}
.todorow:first-child{border-top:0}
.todorow .tick{width:18px;height:18px;border-radius:6px;box-shadow:inset 0 0 0 1.5px var(--line2);flex-shrink:0}
.todorow .lx span:first-child{font-size:14px}
.todoacts{display:inline-flex;gap:0 14px}
.actword{font-size:13px;font-weight:700;color:var(--ac);padding:0 2px;white-space:nowrap}
.actword.armed{color:var(--ink);background:var(--ac);border-radius:8px;padding:4px 10px}
.keeprow .wd{font-size:14px}
.mprog{will-change:width}
@keyframes mprog{from{width:var(--p0)}to{width:100%}}
.dstrip>span.gap{background:repeating-linear-gradient(135deg,var(--line2) 0 3px,transparent 3px 6px)}
.dstrip .dnow{position:absolute;top:0;bottom:0;width:2px;margin-left:-1px;background:var(--text);opacity:.5}
.chart.haslabs{margin-right:96px}
.chlabs{position:absolute;left:100%;top:0;width:92px;margin-left:4px;pointer-events:none}
.chlabs span{position:absolute;left:0;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:92px;line-height:14px}
.lede b{color:var(--text);font-weight:600}
h1.hello{font-family:'Bricolage Grotesque','Manrope',sans-serif;font-weight:400;font-size:clamp(36px,5vw,58px);letter-spacing:-.035em;line-height:1}
.story{font-family:'Bricolage Grotesque','Manrope',sans-serif;font-weight:300;font-size:clamp(20px,2.3vw,27px);line-height:1.45;letter-spacing:-.015em;color:var(--muted);max-width:980px}
.story .hi{color:var(--text)}
.story .warn{color:var(--rose)}
.storyx{display:block;font-family:'Manrope',sans-serif;font-size:15px;line-height:1.5;color:var(--muted);margin:6px 0 10px;padding-left:2px}
.holdable{border-radius:18px;margin:-6px -10px;padding:6px 10px;transition:background-color .4s ease}
.holdable.holding{background:color-mix(in oklab,var(--violet) 9%,transparent)}
.label{font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--quiet)}
.row{display:flex;align-items:center;gap:10px}
.rowb{display:flex;align-items:baseline;gap:12px}
.flex1{flex:1}
.nm{background:none;border:0;padding:0;margin:0;font:inherit;color:inherit;cursor:pointer;text-align:left;text-decoration:underline;text-decoration-style:dotted;text-decoration-color:var(--line2);text-decoration-thickness:1.5px;text-underline-offset:.32em;transition:text-decoration-color .3s ease}
.nm:hover,.nm[aria-expanded="true"]{text-decoration-style:solid;text-decoration-color:currentColor}
.wd{background:none;border:0;margin:0;font:inherit;cursor:pointer;color:var(--quiet);min-height:40px;padding:0 1px;transition:color .25s ease}
.wd:hover{color:var(--text)}
.cl-acts .wd{font-size:12px;min-height:0;padding:12px 2px;margin:-12px 0;color:var(--muted)}
.wd[aria-pressed="true"]{color:var(--text);text-decoration:underline;text-decoration-thickness:2px;text-underline-offset:8px}
.wd.go{font-weight:700;color:var(--teal)}
.wd.bad{color:var(--rose)}
.wd.strong{font-weight:600;color:var(--text)}
.sq{width:40px;height:40px;border-radius:12px;border:0;background:var(--chip);display:grid;place-items:center;cursor:pointer;transition:background-color .2s ease}
.sq:hover{background:var(--line2)}
.go{background:none;border:0;padding:0;margin:0;font:inherit;cursor:pointer;font-weight:700;min-height:40px}
.go:hover{text-decoration:underline;text-underline-offset:6px;text-decoration-thickness:1.5px}
.scenesline{display:flex;flex-wrap:wrap;align-items:center;gap:0 22px}
.scenesline .wd{font-family:'Bricolage Grotesque','Manrope',sans-serif;font-size:19px;letter-spacing:-.01em}
.askrow{display:flex;align-items:center;gap:12px;max-width:620px}
.askin{background:transparent;border:0;border-bottom:1px solid var(--line);border-radius:0;padding:8px 0;width:100%;font-size:17px;color:var(--text);outline:none;transition:border-color .3s ease}
.askin:focus{border-bottom-color:var(--line2)}
.askin::placeholder{color:var(--quiet)}
.answer{padding-left:30px;max-width:760px;display:flex;flex-direction:column;gap:4px;margin-top:4px}
.answer p .pulse{display:inline-block;margin-right:10px;vertical-align:middle}
.askrow .askbusy{margin-left:-4px}
.answer p{font-family:'Bricolage Grotesque','Manrope',sans-serif;font-size:19px;font-weight:300;line-height:1.5;letter-spacing:-.01em;color:var(--muted);white-space:pre-wrap}
.sugs{display:none;flex-wrap:wrap;gap:0 20px;padding-left:30px}
[data-ask]:focus-within .sugs,[data-ask]:has(.askin:not(:placeholder-shown)) .sugs{display:flex}
.cu{position:relative;--rp:min(30%,260px);--ty:50px}
.cu-vp{position:relative;height:76px;overflow:hidden;cursor:grab;touch-action:pan-y;user-select:none;-webkit-user-select:none;-webkit-mask-image:linear-gradient(90deg,transparent 0,#000 24px,#000 calc(100% - 48px),transparent 100%);mask-image:linear-gradient(90deg,transparent 0,#000 24px,#000 calc(100% - 48px),transparent 100%)}
.cu-vp:active{cursor:grabbing}
.cu-vp:focus-visible{outline:2px solid var(--text);outline-offset:-2px;border-radius:12px}
.cu-track{position:absolute;left:var(--rp);top:var(--ty);width:0;height:0;will-change:transform}
.cu-track.glide{transition:transform .55s cubic-bezier(.16,.84,.24,1)}
.cu-track>i,.cu-track>span{position:absolute}
.cu-night{top:-11px;height:22px;border-radius:11px;background:color-mix(in oklab,var(--indigo) 10%,transparent)}
.cu-line{top:-1px;height:2px;border-radius:1px;background:var(--line)}
.cu-tick{top:4px;width:1px;height:3px;background:var(--line2)}
.cu-tick.major{height:5px}
.cu-tl{top:11px;transform:translateX(-50%);font-size:11px;color:var(--quiet);font-variant-numeric:tabular-nums;white-space:nowrap}
.cu-tl.cu-mid{color:var(--text);font-weight:700}
.cu-nowm{left:-1px;top:-7px;width:2px;height:14px;border-radius:1px;background:var(--teal)}
.cu-bar{height:6px;border-radius:3px;background:color-mix(in oklab,var(--c) 22%,transparent);overflow:hidden;transition:background-color .2s ease}
.cu-bar>i{display:block;height:100%;background:color-mix(in oklab,var(--c) 70%,transparent)}
.cu-bar.on{background:color-mix(in oklab,var(--c) 46%,transparent)}
.cu-bar.past,.cu-pin.past{opacity:.4}
.cu-pin{top:-11px;width:22px;height:22px;margin-left:-11px;display:flex;align-items:center;justify-content:center}
.cu-dot{display:block;width:12px;height:12px;border-radius:50%;background:var(--bg);flex:none;transition:transform .18s ease-out}
.cu-n{position:absolute;top:-7px;right:-7px;font-size:10px;font-weight:700;color:var(--muted);font-variant-numeric:tabular-nums}
.cu-lens{position:absolute;left:calc(var(--rp) - 16px);top:calc(var(--ty) - 12px);width:32px;height:24px;border-radius:12px;background:var(--surface);box-shadow:0 0 0 1px var(--line2);transition:box-shadow .25s ease}
.cu-lens.hit{box-shadow:0 0 0 1.5px var(--c),0 4px 12px -4px rgba(0,0,0,.4)}
.cu-ph{position:absolute;left:calc(var(--rp) - 1px);top:8px;width:2px;height:calc(var(--ty) - 22px);border-radius:1px;background:var(--text)}
.cu-ph.low{top:calc(var(--ty) + 12px);height:auto;bottom:0;opacity:.3}
.cu-when{position:absolute;right:calc(100% - var(--rp) + 14px);top:8px;max-width:calc(var(--rp) - 24px);display:flex;flex-direction:row-reverse;align-items:baseline;gap:8px;white-space:nowrap;overflow:hidden}
.cu-when b{font-size:15px;font-weight:700;font-variant-numeric:tabular-nums}
.cu-when>span{font-size:13px;color:var(--quiet);overflow:hidden;text-overflow:ellipsis}
.cu-day2{display:none}
.cu-what{position:absolute;left:calc(var(--rp) + 14px);right:8px;top:8px;display:flex;align-items:baseline;gap:10px;min-width:0;white-space:nowrap}
.cu-l1{display:flex;align-items:center;gap:8px;min-width:0;flex:0 1 auto}
.cu-l1 .cu-dot{transition:none}
.cu-name{font-size:15px;font-weight:600;overflow:hidden;text-overflow:ellipsis;min-width:0;text-align:left;line-height:1.3}
.cu-name.go{min-height:28px;display:block}
.cu-name.quiet{font-weight:500;color:var(--muted)}
.cu-l2{font-size:13px;color:var(--quiet);overflow:hidden;text-overflow:ellipsis;min-width:0;flex:0 1000 auto}
.cu-back{position:absolute;right:0;bottom:0;font-size:13px;color:var(--teal);min-height:32px;padding:0 4px 0 18px;background:linear-gradient(90deg,transparent,var(--bg) 14px)}
.cu-hint{position:absolute;right:0;top:10px;padding:2px 8px 2px 24px;pointer-events:none;background:linear-gradient(90deg,transparent,var(--bg) 18px)}
@media (max-width:700px){.cu{--rp:min(32%,124px);--ty:62px}.cu-vp{height:88px}.cu-when{flex-direction:column;align-items:flex-end;gap:1px;top:6px}.cu-when b{font-size:14px}.cu-when>span{font-size:12px;max-width:100%}.cu-day{display:none}.cu-day2{display:inline}.cu-what{flex-direction:column;align-items:flex-start;gap:1px;top:6px}.cu-l1{max-width:100%}.cu-name{font-size:14px}.cu-l2{font-size:12px;max-width:100%}.cu-hint{display:none}}
/* Coming up unfolded under a card (a Next chip): sized by the card's row, not the window. */
.upcslot{container-type:inline-size}.upcslot .cu-back,.upcslot .cu-hint{background:none}
@container (max-width:700px){.cu{--rp:min(32%,124px);--ty:62px}.cu-vp{height:88px}.cu-when{flex-direction:column;align-items:flex-end;gap:1px;top:6px}.cu-when b{font-size:14px}.cu-when>span{font-size:12px;max-width:100%}.cu-day{display:none}.cu-day2{display:inline}.cu-what{flex-direction:column;align-items:flex-start;gap:1px;top:6px}.cu-l1{max-width:100%}.cu-name{font-size:14px}.cu-l2{font-size:12px;max-width:100%}.cu-hint{display:none}}
[data-board]{position:relative}
[data-sec],[data-tile],[data-glab],[data-gbg]{will-change:transform,width,height}
.flh{position:absolute;left:0;top:0;display:flex;flex-direction:column;justify-content:flex-end;padding:0 4px 16px;border-radius:18px;transition:background-color .4s ease}
.flh h2{font-family:'Bricolage Grotesque','Manrope',sans-serif;font-size:clamp(24px,2.6vw,30px);font-weight:300;letter-spacing:-.03em;line-height:1;white-space:nowrap}
.flrow{display:flex;align-items:flex-end;gap:16px}
.flr{flex:1;height:1px;background:linear-gradient(90deg,var(--line),transparent);align-self:center;margin-top:10px;min-width:20px}
.facts{font-size:14px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;font-variant-numeric:tabular-nums}
.facts .sep{color:var(--quiet)}
@media (max-width:700px){.flrow{flex-direction:column;align-items:flex-start!important;gap:6px!important}.flh{padding-bottom:14px!important}.flr{display:none}.flrow .facts{white-space:normal;max-width:100%}}
section.sec{position:absolute;left:0;top:0;border-radius:30px;overflow:hidden}
.secbg{position:absolute;inset:0;border-radius:30px;transition:box-shadow .3s ease}
.sechead{position:relative;display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:16px 12px 6px 22px;min-height:62px}
.sechead h2{font-family:'Bricolage Grotesque','Manrope',sans-serif;font-size:22px;font-weight:400;letter-spacing:-.02em;line-height:1.2;white-space:nowrap}
.secmeta{font-size:13px;color:var(--quiet);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.gbg{position:absolute;left:0;top:0;border-radius:22px}
.glab{position:absolute;left:0;top:0;display:flex;align-items:center;gap:10px;font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;white-space:nowrap;overflow:hidden}
.glab i{font-style:normal;font-weight:600;letter-spacing:.02em;text-transform:none;color:var(--quiet);opacity:.8}
.tile{position:absolute;left:0;top:0;contain:layout style}
.mtile{position:absolute;inset:0;overflow:hidden;border-radius:18px;touch-action:pan-y;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;transition:background-color .6s cubic-bezier(.2,.8,.2,1),transform .35s cubic-bezier(.2,.8,.2,1),box-shadow .3s ease}
.mtile.holding{transform:scale(.985)}
.tc{position:absolute;left:0;top:0}
.face{position:relative}
.holdbar{position:absolute;left:14px;right:14px;bottom:5px;height:2px;border-radius:1px;transform-origin:left center;pointer-events:none;animation:holdbar .54s linear forwards;z-index:3}
@keyframes holdbar{from{transform:scaleX(0);opacity:.4}to{transform:scaleX(1);opacity:1}}
.strip{position:relative;height:56px;border-radius:18px;overflow:hidden;transition:box-shadow .5s ease,background-color .5s ease}
.strip:hover{box-shadow:inset 0 0 0 1px var(--line2)!important}
.fill{position:absolute;left:0;top:0;bottom:0;pointer-events:none;transition:width .7s cubic-bezier(.2,.8,.2,1)}
.sliding .fill,.sliding .slats,.sliding .thumb,.sliding .lane>span{transition:none!important}
.thumb{position:absolute;top:0;bottom:0;width:2px;margin-left:-2px;background:var(--text);opacity:.4;pointer-events:none;transition:left .7s cubic-bezier(.2,.8,.2,1)}
.slats{position:absolute;left:0;top:0;bottom:0;background:repeating-linear-gradient(180deg,transparent 0 6px,color-mix(in oklab,var(--text) 9%,transparent) 6px 7px);pointer-events:none;transition:width .7s cubic-bezier(.2,.8,.2,1)}
.lanes{position:absolute;inset:0;display:flex;flex-direction:column;gap:1px;pointer-events:none}
.lane{flex:1;position:relative;transition:background-color .5s ease}
.lane>span{position:absolute;left:0;top:0;bottom:0;transition:width .7s cubic-bezier(.2,.8,.2,1)}
.sline{position:relative;height:100%;display:flex;align-items:center;gap:10px;padding:0 14px}
.sline svg{flex-shrink:0;overflow:visible;transition:color .4s ease}
.nv{display:flex;flex-direction:column;min-width:0;flex:0 1 auto;line-height:1.25}
.nv b{font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}
.nv span{font-size:12px;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:color .4s ease}
@media (max-width:520px){.sline{gap:8px;padding:0 11px}.nv b{font-size:13px}}
.track{position:relative;width:30px;height:18px;border-radius:6px;flex-shrink:0;transition:background-color .35s ease}
.knob{position:absolute;top:3px;width:12px;height:12px;border-radius:4px;transition:left .35s cubic-bezier(.25,1,.3,1),background-color .35s ease}
.hint{position:absolute;right:12px;bottom:6px;z-index:2;font-size:11px;font-weight:600;color:var(--muted);white-space:nowrap;padding:2px 8px;border-radius:6px;background:color-mix(in oklab,var(--surface) 88%,transparent);opacity:0;transform:translateY(3px);transition:opacity .2s ease,transform .2s ease;pointer-events:none}
.mtile:hover .hint{opacity:.95;transform:none;transition-delay:.3s}
@media (hover:none){.hint{display:none}}
.box{padding:12px 12px 12px 16px;display:flex;flex-direction:column;gap:2px;border-radius:18px}
.big{font-family:'Bricolage Grotesque','Manrope',sans-serif;font-size:42px;font-weight:300;letter-spacing:-.04em;line-height:1.05;font-variant-numeric:tabular-nums}
.mid{font-family:'Bricolage Grotesque','Manrope',sans-serif;font-size:28px;font-weight:300;letter-spacing:-.03em;line-height:1.1;font-variant-numeric:tabular-nums}
.small{font-size:12px;color:var(--quiet)}
.sm{font-size:13px;color:var(--muted)}
.ruler{position:relative;height:16px;margin-top:6px}
.ruler>div{position:absolute}
.scenes{display:flex;flex-wrap:wrap;align-items:center;gap:0 20px;padding:0 4px 0 14px;min-height:44px}
.scenes .wd{font-family:'Bricolage Grotesque','Manrope',sans-serif;font-size:17px;letter-spacing:-.01em}
.more{display:flex;flex-direction:column;gap:14px;padding:4px 14px 14px}
.more .label{margin-bottom:-6px}
.lrow{display:flex;align-items:baseline;gap:12px;width:100%;padding:9px 8px;margin:0;border:0;border-top:1px solid var(--line);background:none;font:inherit;font-size:14px;text-align:left;color:var(--text);border-radius:8px;cursor:pointer;transition:background-color .2s ease}
.lrow:hover{background:var(--hover)}
.lt{width:74px;flex-shrink:0;color:var(--quiet);font-size:12px;font-variant-numeric:tabular-nums}
.lx{flex:1;min-width:0;display:flex;flex-direction:column}
.lw{font-size:12px;color:var(--quiet)}
.dstrip{position:relative;height:22px;border-radius:7px;background:var(--sunk);overflow:hidden}
.dstrip>span{position:absolute;top:3px;bottom:3px;border-radius:4px}
.ticks{display:flex;justify-content:space-between;font-size:10px;color:var(--quiet);font-variant-numeric:tabular-nums;margin-top:3px}
.cols{display:flex;align-items:flex-end;gap:5px;height:84px}
.colb{flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;height:100%;justify-content:flex-end;min-width:0;border:0;background:none;padding:0;font:inherit;color:inherit;cursor:pointer}
.colbar{width:100%;border-radius:4px;transition:filter .2s ease,height .5s ease}
.colb:hover .colbar{filter:brightness(1.35)}
.colv{font-size:10px;color:var(--muted);white-space:nowrap}
.coll{font-size:10px;color:var(--quiet);white-space:nowrap}
.crumbs{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.crumb{background:none;border:0;padding:0 2px;margin:0;min-height:32px;font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--quiet);cursor:pointer}
.crumb:hover{color:var(--text)}
.chart{position:relative;touch-action:pan-y}
.chart svg{display:block;width:100%;overflow:visible}
.scrub{position:absolute;top:0;bottom:0;width:1px;background:var(--line2);pointer-events:none}
.readout{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums;min-height:18px}
.legend{display:flex;flex-wrap:wrap;gap:0 14px}
.ov{padding:12px 14px 12px 16px}
.ovhead{display:flex;align-items:baseline;gap:10px;min-height:20px}
.ovhead b{font-size:14px;font-weight:600;white-space:nowrap}
.ovsub{font-size:13px;color:var(--quiet);font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.ovrow{display:flex;gap:12px}
.ovside{width:138px;flex-shrink:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ovplot{flex:1;min-width:0;height:150px;cursor:crosshair}
.ovplot svg{overflow:visible}
.ovlabels{position:relative;height:150px}
.ovlab{position:absolute;left:0;right:0;height:18px;display:flex;align-items:center;gap:7px;border:0;background:none;padding:0;font:inherit;color:var(--text);cursor:pointer;transition:top .35s cubic-bezier(.25,1,.3,1),opacity .3s ease}
.ovlab .sw{width:10px;height:2px;border-radius:1px;flex-shrink:0}
.ovlab .nm{flex:1;min-width:0;text-align:left;font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ovlab b{font-size:13px;font-weight:600;font-variant-numeric:tabular-nums}
.ovdots{position:absolute;inset:0;pointer-events:none}
.ovdot{position:absolute;width:7px;height:7px;margin:-3.5px 0 0 -3.5px;border-radius:50%;box-shadow:0 0 0 2px var(--surface)}
.ovruns{position:relative;flex:1;min-width:0;height:4px;border-radius:2px;background:var(--line)}
.ovruns span{position:absolute;top:0;bottom:0;border-radius:2px}
.ovaxis{position:relative;flex:1;min-width:0;height:14px;font-size:11px;color:var(--quiet)}
.ovaxis span{position:absolute;top:0;white-space:nowrap}
.ovenv{display:flex;flex-wrap:wrap;gap:6px 24px;margin-top:12px;padding-top:10px;border-top:1px solid var(--line)}
.ovenvi{display:flex;align-items:center;gap:8px}
.ovenvi .nm{font-size:12px;color:var(--muted)}
.ovenvi b{font-size:14px;font-weight:600;font-variant-numeric:tabular-nums}
@media (max-width:520px){.ovside{width:104px}}
.legend .wd{min-height:30px;font-size:12px}
.field{position:relative;height:120px;border-radius:12px;cursor:crosshair;background:linear-gradient(to bottom,rgba(255,255,255,.75),rgba(255,255,255,0)),linear-gradient(90deg,#f00,#ff0,#0f0,#0ff,#00f,#f0f,#f00)}
.field i{position:absolute;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.5);pointer-events:none}
.swatches{display:flex;gap:8px;flex-wrap:wrap}
.sw{width:36px;height:36px;border-radius:10px;border:0;cursor:pointer;box-shadow:inset 0 0 0 1px var(--line2)}
.mrange{-webkit-appearance:none;appearance:none;width:100%;height:40px;cursor:pointer;margin:0;display:block;background:transparent}
.mrange::-webkit-slider-runnable-track{height:6px;border-radius:3px;background:var(--line2)}
.mrange::-moz-range-track{height:6px;border-radius:3px;background:var(--line2)}
.mrange::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;width:14px;height:26px;margin-top:-10px;border-radius:7px;background:#fff;border:0;box-shadow:0 1px 2px rgba(0,0,0,.2),0 4px 14px rgba(0,0,0,.3)}
.mrange::-moz-range-thumb{width:14px;height:26px;border-radius:7px;background:#fff;border:0}
.cam{width:100%;display:block;border-radius:14px;background:var(--sunk);aspect-ratio:16/9;object-fit:cover}
.camtile{padding:10px;border-radius:18px}
.camhead{display:flex;align-items:baseline;gap:8px;padding:0 6px 8px}
.camhead b{font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.campic{position:relative;height:104px;border-radius:12px;background:var(--sunk);overflow:hidden}
.campic .cam{position:absolute;inset:0;width:100%;height:100%;aspect-ratio:auto;border-radius:0}
.campic .live{position:absolute;top:8px;left:8px;display:inline-flex;align-items:center;gap:5px;font-size:10px;font-weight:700;letter-spacing:.1em;color:#fff;background:rgba(0,0,0,.5);padding:2px 8px;border-radius:6px}
.campic .live i{width:5px;height:5px;border-radius:1px;background:#FF6B5B}
.campic .live i.still{background:#9aa}
.campic .hint{position:absolute;bottom:8px;right:10px}
.avatar{width:32px;height:32px;border-radius:50%;object-fit:cover;flex-shrink:0;display:grid;place-items:center;font-weight:700;font-size:13px}
.ll{padding:4px}
.note{display:flex;flex-direction:column;gap:6px;padding:12px 14px;border-radius:16px}
.note p{font-size:14px;line-height:1.45}
.note .acts{display:flex;flex-wrap:wrap;gap:0 18px}
.bnote{flex-direction:row;gap:12px;align-items:flex-start;padding:12px 16px 6px 14px}
.bnote>svg{margin-top:3px}
.bnin{display:flex;flex-direction:column;min-width:0;gap:2px}
.bnote .say{font-size:14px;line-height:1.5;color:var(--muted)}
.bnote .sub{font-size:13px;line-height:1.45;color:var(--quiet)}
.bnote .wd{font-size:14px;font-weight:600;min-height:36px;color:var(--quiet)}
.bnote .wd.first{color:var(--text)}
.bnote .fld{margin-top:6px}
.notecard{border-radius:18px}
.tell{display:flex;flex-direction:column;gap:10px;padding:12px 14px 10px;border-radius:16px;text-align:left;cursor:auto;background:linear-gradient(100deg,color-mix(in oklab,var(--violet) 13%,var(--surface)),color-mix(in oklab,var(--teal) 6%,var(--surface)) 75%);box-shadow:inset 0 0 0 1px color-mix(in oklab,var(--violet) 34%,transparent);width:100%;flex-basis:100%}
.tellin,.fld,.code-ed{background:color-mix(in oklab,var(--bg) 55%,transparent);border:0;border-radius:12px;padding:10px 12px;width:100%;font:inherit;font-size:15px;line-height:1.45;color:var(--text);outline:none;box-shadow:inset 0 0 0 1px var(--line)}
.tellin{resize:vertical;min-height:78px}
.tellin:focus,.fld:focus,.code-ed:focus{box-shadow:inset 0 0 0 1px color-mix(in oklab,var(--violet) 55%,transparent)}
.tellin::placeholder,.fld::placeholder{color:var(--quiet)}
.fld{font-weight:500}
.code-ed{font-family:ui-monospace,'SF Mono',Menlo,monospace;font-size:12px;line-height:1.55;min-height:240px;white-space:pre;resize:vertical}
.steps{display:flex;flex-direction:column;gap:4px}
.step{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--muted)}
.step i{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.bstep{font-size:12.5px}
.bstep i{width:5px;height:5px;opacity:.7}
.earlier summary{cursor:pointer;min-height:28px;line-height:28px;font-size:12px;color:var(--quiet)}
.earlier .step{padding-left:2px}
.working{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--text);min-height:24px}
.pulse{width:8px;height:8px;border-radius:50%;flex-shrink:0;background:var(--violet);animation:breathe 1.6s ease-in-out infinite}
.turn{display:flex;flex-direction:column;gap:4px;padding-bottom:10px;border-bottom:1px solid var(--line)}
.turn .q{font-size:14px}
.turn .a{font-size:13px;line-height:1.45;color:var(--muted)}
.shots{display:flex;flex-wrap:wrap;gap:10px}
.shot{margin:0;display:flex;flex-direction:column;gap:4px;max-width:min(260px,100%);cursor:zoom-in}
.shot img{display:block;max-width:100%;max-height:170px;object-fit:contain;object-position:left top;border-radius:10px;box-shadow:inset 0 0 0 1px var(--line),0 0 0 1px var(--line);background:var(--sunk)}
.shot figcaption{font-size:11.5px;color:var(--quiet)}
.shot.zoom{max-width:100%;cursor:zoom-out}
.shot.zoom img{max-height:none}
.whatlist{display:flex;flex-direction:column;gap:6px;padding:8px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);font-size:13px;line-height:1.4}
.what{display:grid;grid-template-columns:112px minmax(0,1fr);gap:10px;align-items:baseline}
.what .wk{color:var(--muted);font-weight:600}
.what .wv{display:flex;flex-direction:column;gap:2px;min-width:0;overflow-wrap:anywhere}
.issue.askq{background:color-mix(in oklab,var(--violet) 8%,transparent);box-shadow:inset 0 0 0 1px color-mix(in oklab,var(--violet) 28%,transparent)}
.update{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:0 0 14px;padding:10px 14px;border-radius:14px;font-size:14px;background:color-mix(in oklab,var(--teal) 10%,transparent);box-shadow:inset 0 0 0 1px color-mix(in oklab,var(--teal) 30%,transparent)}
.update span{flex:1 1 220px}
.moreinfo{display:flex;flex-wrap:wrap;gap:0 18px;margin-top:8px;padding-top:6px;border-top:1px solid var(--line)}
.issue{display:flex;flex-direction:column;gap:6px;padding:10px 12px;border-radius:12px;font-size:14px;line-height:1.45;background:color-mix(in oklab,var(--amber) 9%,transparent);box-shadow:inset 0 0 0 1px color-mix(in oklab,var(--amber) 30%,transparent)}
.activity{display:flex;align-items:center;gap:12px;padding:10px 14px;margin-bottom:10px;border-radius:14px;background:color-mix(in oklab,var(--violet) 8%,var(--surface));box-shadow:inset 0 0 0 1px color-mix(in oklab,var(--violet) 25%,transparent)}
.activity .lx{display:flex;flex-direction:column;gap:2px;flex:1;min-width:0}
.activity .lx b{font-size:14px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.activity .lx span{font-size:12.5px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.payload summary{cursor:pointer;min-height:28px;line-height:28px;font-size:12px;color:var(--quiet)}
.payload pre{font-family:ui-monospace,monospace;margin-top:6px;max-height:240px;overflow:auto;white-space:pre-wrap;word-break:break-word;font-size:11px;line-height:1.5;color:var(--muted);background:var(--sunk);border-radius:10px;padding:10px 12px}
.edit{display:flex;flex-direction:column;gap:12px;padding:10px 14px 14px}
.flab{display:flex;flex-direction:column;gap:6px;font-size:12px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--quiet)}
.hues{display:flex;flex-wrap:wrap;gap:4px}
.hue{width:36px;height:36px;border:0;padding:0;background:none;display:grid;place-items:center;cursor:pointer}
.hue span{width:22px;height:22px;border-radius:7px}
.code{font-family:ui-monospace,'SF Mono',Menlo,monospace;font-size:12px;line-height:1.55;padding:12px 14px;border-radius:12px;background:var(--sunk);white-space:pre;overflow-x:auto;margin:0;color:var(--muted);user-select:text}
.settings{display:flex;flex-direction:column;gap:28px;max-width:860px}
.setsec{display:flex;flex-direction:column;gap:12px;padding:18px 20px;border-radius:24px;background:var(--surface)}
.setsec h2{font-family:'Bricolage Grotesque','Manrope',sans-serif;font-size:22px;font-weight:400;letter-spacing:-.02em}
.setrow{display:flex;align-items:center;gap:14px;padding:10px 0;border-top:1px solid var(--line);cursor:pointer}
.setrow:first-of-type{border-top:0}
.setrow .lx b{font-size:14px;font-weight:600}
.setrow .lx span{font-size:13px;color:var(--muted)}
.sswitch{position:relative;width:40px;height:24px;border-radius:8px;flex-shrink:0;background:var(--chip);box-shadow:inset 0 0 0 1px var(--line2);transition:background-color .3s ease}
.sswitch i{position:absolute;top:4px;left:4px;width:16px;height:16px;border-radius:5px;background:var(--quiet);transition:left .3s cubic-bezier(.25,1,.3,1),background-color .3s ease}
.sswitch.on{background:color-mix(in oklab,var(--teal) 30%,transparent);box-shadow:none}
.sswitch.on i{left:20px;background:var(--teal)}
.stats{display:flex;flex-wrap:wrap;gap:22px}
.stat b{display:block;font-family:'Bricolage Grotesque','Manrope',sans-serif;font-size:28px;font-weight:300;letter-spacing:-.03em}
.stat span{font-size:12px;color:var(--quiet)}
.hrow{display:flex;align-items:baseline;gap:12px;padding:8px 0;border-top:1px solid var(--line);font-size:14px}
.hrow .who{width:86px;flex-shrink:0;font-size:12px;font-weight:700;color:var(--quiet)}
.pill{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:6px;background:var(--chip);color:var(--muted)}
.banner{font-size:14px;color:var(--muted);padding:10px 14px;border-radius:14px;background:var(--surface)}
.banner.bad{color:var(--rose)}
.w{animation:wordin .75s cubic-bezier(.2,.8,.2,1) both}
@keyframes wordin{from{opacity:0}to{opacity:1}}
.rise{animation:rise .7s cubic-bezier(.2,.8,.2,1) both}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.nowdot{animation:nowdot 2.2s ease-out infinite}
@keyframes nowdot{0%{box-shadow:0 0 0 0 color-mix(in oklab,var(--teal) 70%,transparent)}100%{box-shadow:0 0 0 12px transparent}}
@keyframes spin{to{transform:rotate(360deg)}}
.spin{animation:spin linear infinite}
.breathe{animation:breathe 3.2s ease-in-out infinite}
@keyframes breathe{0%,100%{opacity:.4}50%{opacity:1}}
.bob{animation:bob 1.6s ease-in-out infinite}
.wave{animation:wave 2.4s ease-in-out infinite}
@keyframes wave{0%,100%{transform:translateY(0)}50%{transform:translateY(-1.6px)}}
@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(2px)}}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.reduce *,.reduce *::before,.reduce *::after{animation:none!important;transition:none!important}
@media (prefers-reduced-motion:reduce){.srpanel,.morph.railing section.sec[data-sec],.morph section.sec .sechead h2,.secbg{transition:none!important}.rise,.holdbar,.nowdot,.w,.spin,.breathe,.wave,.bob,.pulse,.mprog{animation:none}.mtile,.cu-track.glide,.cu-dot,.cu-lens,.cu-bar,.todorow,.thenrule{transition:none}.form-night section.sec,.form-night .flh{transition:none}}
`;
