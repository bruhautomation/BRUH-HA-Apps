var Bt=globalThis,jt=Bt.ShadowRoot&&(Bt.ShadyCSS===void 0||Bt.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,Dr=Symbol(),xo=new WeakMap,yt=class{constructor(e,r,o){if(this._$cssResult$=!0,o!==Dr)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=e,this.t=r}get styleSheet(){let e=this.o,r=this.t;if(jt&&e===void 0){let o=r!==void 0&&r.length===1;o&&(e=xo.get(r)),e===void 0&&((this.o=e=new CSSStyleSheet).replaceSync(this.cssText),o&&xo.set(r,e))}return e}toString(){return this.cssText}},zo=t=>new yt(typeof t=="string"?t:t+"",void 0,Dr),P=(t,...e)=>{let r=t.length===1?t[0]:e.reduce((o,n,a)=>o+(i=>{if(i._$cssResult$===!0)return i.cssText;if(typeof i=="number")return i;throw Error("Value passed to 'css' function must be a 'css' function result: "+i+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(n)+t[a+1],t[0]);return new yt(r,t,Dr)},So=(t,e)=>{if(jt)t.adoptedStyleSheets=e.map(r=>r instanceof CSSStyleSheet?r:r.styleSheet);else for(let r of e){let o=document.createElement("style"),n=Bt.litNonce;n!==void 0&&o.setAttribute("nonce",n),o.textContent=r.cssText,t.appendChild(o)}},Or=jt?t=>t:t=>t instanceof CSSStyleSheet?(e=>{let r="";for(let o of e.cssRules)r+=o.cssText;return zo(r)})(t):t;var{is:Ra,defineProperty:Ea,getOwnPropertyDescriptor:La,getOwnPropertyNames:Ha,getOwnPropertySymbols:Da,getPrototypeOf:Oa}=Object,Gt=globalThis,Ao=Gt.trustedTypes,Ba=Ao?Ao.emptyScript:"",ja=Gt.reactiveElementPolyfillSupport,_t=(t,e)=>t,Br={toAttribute(t,e){switch(e){case Boolean:t=t?Ba:null;break;case Object:case Array:t=t==null?t:JSON.stringify(t)}return t},fromAttribute(t,e){let r=t;switch(e){case Boolean:r=t!==null;break;case Number:r=t===null?null:Number(t);break;case Object:case Array:try{r=JSON.parse(t)}catch{r=null}}return r}},Co=(t,e)=>!Ra(t,e),To={attribute:!0,type:String,converter:Br,reflect:!1,useDefault:!1,hasChanged:Co};Symbol.metadata??=Symbol("metadata"),Gt.litPropertyMetadata??=new WeakMap;var _e=class extends HTMLElement{static addInitializer(e){this._$Ei(),(this.l??=[]).push(e)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(e,r=To){if(r.state&&(r.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(e)&&((r=Object.create(r)).wrapped=!0),this.elementProperties.set(e,r),!r.noAccessor){let o=Symbol(),n=this.getPropertyDescriptor(e,o,r);n!==void 0&&Ea(this.prototype,e,n)}}static getPropertyDescriptor(e,r,o){let{get:n,set:a}=La(this.prototype,e)??{get(){return this[r]},set(i){this[r]=i}};return{get:n,set(i){let s=n?.call(this);a?.call(this,i),this.requestUpdate(e,s,o)},configurable:!0,enumerable:!0}}static getPropertyOptions(e){return this.elementProperties.get(e)??To}static _$Ei(){if(this.hasOwnProperty(_t("elementProperties")))return;let e=Oa(this);e.finalize(),e.l!==void 0&&(this.l=[...e.l]),this.elementProperties=new Map(e.elementProperties)}static finalize(){if(this.hasOwnProperty(_t("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(_t("properties"))){let r=this.properties,o=[...Ha(r),...Da(r)];for(let n of o)this.createProperty(n,r[n])}let e=this[Symbol.metadata];if(e!==null){let r=litPropertyMetadata.get(e);if(r!==void 0)for(let[o,n]of r)this.elementProperties.set(o,n)}this._$Eh=new Map;for(let[r,o]of this.elementProperties){let n=this._$Eu(r,o);n!==void 0&&this._$Eh.set(n,r)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(e){let r=[];if(Array.isArray(e)){let o=new Set(e.flat(1/0).reverse());for(let n of o)r.unshift(Or(n))}else e!==void 0&&r.push(Or(e));return r}static _$Eu(e,r){let o=r.attribute;return o===!1?void 0:typeof o=="string"?o:typeof e=="string"?e.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(e=>this.enableUpdating=e),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(e=>e(this))}addController(e){(this._$EO??=new Set).add(e),this.renderRoot!==void 0&&this.isConnected&&e.hostConnected?.()}removeController(e){this._$EO?.delete(e)}_$E_(){let e=new Map,r=this.constructor.elementProperties;for(let o of r.keys())this.hasOwnProperty(o)&&(e.set(o,this[o]),delete this[o]);e.size>0&&(this._$Ep=e)}createRenderRoot(){let e=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return So(e,this.constructor.elementStyles),e}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(e=>e.hostConnected?.())}enableUpdating(e){}disconnectedCallback(){this._$EO?.forEach(e=>e.hostDisconnected?.())}attributeChangedCallback(e,r,o){this._$AK(e,o)}_$ET(e,r){let o=this.constructor.elementProperties.get(e),n=this.constructor._$Eu(e,o);if(n!==void 0&&o.reflect===!0){let a=(o.converter?.toAttribute!==void 0?o.converter:Br).toAttribute(r,o.type);this._$Em=e,a==null?this.removeAttribute(n):this.setAttribute(n,a),this._$Em=null}}_$AK(e,r){let o=this.constructor,n=o._$Eh.get(e);if(n!==void 0&&this._$Em!==n){let a=o.getPropertyOptions(n),i=typeof a.converter=="function"?{fromAttribute:a.converter}:a.converter?.fromAttribute!==void 0?a.converter:Br;this._$Em=n;let s=i.fromAttribute(r,a.type);this[n]=s??this._$Ej?.get(n)??s,this._$Em=null}}requestUpdate(e,r,o,n=!1,a){if(e!==void 0){let i=this.constructor;if(n===!1&&(a=this[e]),o??=i.getPropertyOptions(e),!((o.hasChanged??Co)(a,r)||o.useDefault&&o.reflect&&a===this._$Ej?.get(e)&&!this.hasAttribute(i._$Eu(e,o))))return;this.C(e,r,o)}this.isUpdatePending===!1&&(this._$ES=this._$EP())}C(e,r,{useDefault:o,reflect:n,wrapped:a},i){o&&!(this._$Ej??=new Map).has(e)&&(this._$Ej.set(e,i??r??this[e]),a!==!0||i!==void 0)||(this._$AL.has(e)||(this.hasUpdated||o||(r=void 0),this._$AL.set(e,r)),n===!0&&this._$Em!==e&&(this._$Eq??=new Set).add(e))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(r){Promise.reject(r)}let e=this.scheduleUpdate();return e!=null&&await e,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[n,a]of this._$Ep)this[n]=a;this._$Ep=void 0}let o=this.constructor.elementProperties;if(o.size>0)for(let[n,a]of o){let{wrapped:i}=a,s=this[n];i!==!0||this._$AL.has(n)||s===void 0||this.C(n,void 0,a,s)}}let e=!1,r=this._$AL;try{e=this.shouldUpdate(r),e?(this.willUpdate(r),this._$EO?.forEach(o=>o.hostUpdate?.()),this.update(r)):this._$EM()}catch(o){throw e=!1,this._$EM(),o}e&&this._$AE(r)}willUpdate(e){}_$AE(e){this._$EO?.forEach(r=>r.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(e)),this.updated(e)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(e){return!0}update(e){this._$Eq&&=this._$Eq.forEach(r=>this._$ET(r,this[r])),this._$EM()}updated(e){}firstUpdated(e){}};_e.elementStyles=[],_e.shadowRootOptions={mode:"open"},_e[_t("elementProperties")]=new Map,_e[_t("finalized")]=new Map,ja?.({ReactiveElement:_e}),(Gt.reactiveElementVersions??=[]).push("2.1.2");var Gr=globalThis,Mo=t=>t,Nt=Gr.trustedTypes,Po=Nt?Nt.createPolicy("lit-html",{createHTML:t=>t}):void 0,Nr="$lit$",ke=`lit$${Math.random().toFixed(9).slice(2)}$`,Vr="?"+ke,Ga=`<${Vr}>`,Ze=document,wt=()=>Ze.createComment(""),xt=t=>t===null||typeof t!="object"&&typeof t!="function",Ir=Array.isArray,Oo=t=>Ir(t)||typeof t?.[Symbol.iterator]=="function",jr=`[ 	
\f\r]`,kt=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,Ro=/-->/g,Eo=/>/g,We=RegExp(`>|${jr}(?:([^\\s"'>=/]+)(${jr}*=${jr}*(?:[^ 	
\f\r"'\`<>=]|("|')|))|$)`,"g"),Lo=/'/g,Ho=/"/g,Bo=/^(?:script|style|textarea|title)$/i,Fr=t=>(e,...r)=>({_$litType$:t,strings:e,values:r}),h=Fr(1),p=Fr(2),sl=Fr(3),pe=Symbol.for("lit-noChange"),f=Symbol.for("lit-nothing"),Do=new WeakMap,qe=Ze.createTreeWalker(Ze,129);function jo(t,e){if(!Ir(t)||!t.hasOwnProperty("raw"))throw Error("invalid template strings array");return Po!==void 0?Po.createHTML(e):e}var Go=(t,e)=>{let r=t.length-1,o=[],n,a=e===2?"<svg>":e===3?"<math>":"",i=kt;for(let s=0;s<r;s++){let l=t[s],c,d,m=-1,b=0;for(;b<l.length&&(i.lastIndex=b,d=i.exec(l),d!==null);)b=i.lastIndex,i===kt?d[1]==="!--"?i=Ro:d[1]!==void 0?i=Eo:d[2]!==void 0?(Bo.test(d[2])&&(n=RegExp("</"+d[2],"g")),i=We):d[3]!==void 0&&(i=We):i===We?d[0]===">"?(i=n??kt,m=-1):d[1]===void 0?m=-2:(m=i.lastIndex-d[2].length,c=d[1],i=d[3]===void 0?We:d[3]==='"'?Ho:Lo):i===Ho||i===Lo?i=We:i===Ro||i===Eo?i=kt:(i=We,n=void 0);let $=i===We&&t[s+1].startsWith("/>")?" ":"";a+=i===kt?l+Ga:m>=0?(o.push(c),l.slice(0,m)+Nr+l.slice(m)+ke+$):l+ke+(m===-2?s:$)}return[jo(t,a+(t[r]||"<?>")+(e===2?"</svg>":e===3?"</math>":"")),o]},zt=class t{constructor({strings:e,_$litType$:r},o){let n;this.parts=[];let a=0,i=0,s=e.length-1,l=this.parts,[c,d]=Go(e,r);if(this.el=t.createElement(c,o),qe.currentNode=this.el.content,r===2||r===3){let m=this.el.content.firstChild;m.replaceWith(...m.childNodes)}for(;(n=qe.nextNode())!==null&&l.length<s;){if(n.nodeType===1){if(n.hasAttributes())for(let m of n.getAttributeNames())if(m.endsWith(Nr)){let b=d[i++],$=n.getAttribute(m).split(ke),v=/([.?@])?(.*)/.exec(b);l.push({type:1,index:a,name:v[2],strings:$,ctor:v[1]==="."?It:v[1]==="?"?Ft:v[1]==="@"?Ut:Je}),n.removeAttribute(m)}else m.startsWith(ke)&&(l.push({type:6,index:a}),n.removeAttribute(m));if(Bo.test(n.tagName)){let m=n.textContent.split(ke),b=m.length-1;if(b>0){n.textContent=Nt?Nt.emptyScript:"";for(let $=0;$<b;$++)n.append(m[$],wt()),qe.nextNode(),l.push({type:2,index:++a});n.append(m[b],wt())}}}else if(n.nodeType===8)if(n.data===Vr)l.push({type:2,index:a});else{let m=-1;for(;(m=n.data.indexOf(ke,m+1))!==-1;)l.push({type:7,index:a}),m+=ke.length-1}a++}}static createElement(e,r){let o=Ze.createElement("template");return o.innerHTML=e,o}};function Qe(t,e,r=t,o){if(e===pe)return e;let n=o!==void 0?r._$Co?.[o]:r._$Cl,a=xt(e)?void 0:e._$litDirective$;return n?.constructor!==a&&(n?._$AO?.(!1),a===void 0?n=void 0:(n=new a(t),n._$AT(t,r,o)),o!==void 0?(r._$Co??=[])[o]=n:r._$Cl=n),n!==void 0&&(e=Qe(t,n._$AS(t,e.values),n,o)),e}var Vt=class{constructor(e,r){this._$AV=[],this._$AN=void 0,this._$AD=e,this._$AM=r}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(e){let{el:{content:r},parts:o}=this._$AD,n=(e?.creationScope??Ze).importNode(r,!0);qe.currentNode=n;let a=qe.nextNode(),i=0,s=0,l=o[0];for(;l!==void 0;){if(i===l.index){let c;l.type===2?c=new nt(a,a.nextSibling,this,e):l.type===1?c=new l.ctor(a,l.name,l.strings,this,e):l.type===6&&(c=new Kt(a,this,e)),this._$AV.push(c),l=o[++s]}i!==l?.index&&(a=qe.nextNode(),i++)}return qe.currentNode=Ze,n}p(e){let r=0;for(let o of this._$AV)o!==void 0&&(o.strings!==void 0?(o._$AI(e,o,r),r+=o.strings.length-2):o._$AI(e[r])),r++}},nt=class t{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(e,r,o,n){this.type=2,this._$AH=f,this._$AN=void 0,this._$AA=e,this._$AB=r,this._$AM=o,this.options=n,this._$Cv=n?.isConnected??!0}get parentNode(){let e=this._$AA.parentNode,r=this._$AM;return r!==void 0&&e?.nodeType===11&&(e=r.parentNode),e}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(e,r=this){e=Qe(this,e,r),xt(e)?e===f||e==null||e===""?(this._$AH!==f&&this._$AR(),this._$AH=f):e!==this._$AH&&e!==pe&&this._(e):e._$litType$!==void 0?this.$(e):e.nodeType!==void 0?this.T(e):Oo(e)?this.k(e):this._(e)}O(e){return this._$AA.parentNode.insertBefore(e,this._$AB)}T(e){this._$AH!==e&&(this._$AR(),this._$AH=this.O(e))}_(e){this._$AH!==f&&xt(this._$AH)?this._$AA.nextSibling.data=e:this.T(Ze.createTextNode(e)),this._$AH=e}$(e){let{values:r,_$litType$:o}=e,n=typeof o=="number"?this._$AC(e):(o.el===void 0&&(o.el=zt.createElement(jo(o.h,o.h[0]),this.options)),o);if(this._$AH?._$AD===n)this._$AH.p(r);else{let a=new Vt(n,this),i=a.u(this.options);a.p(r),this.T(i),this._$AH=a}}_$AC(e){let r=Do.get(e.strings);return r===void 0&&Do.set(e.strings,r=new zt(e)),r}k(e){Ir(this._$AH)||(this._$AH=[],this._$AR());let r=this._$AH,o,n=0;for(let a of e)n===r.length?r.push(o=new t(this.O(wt()),this.O(wt()),this,this.options)):o=r[n],o._$AI(a),n++;n<r.length&&(this._$AR(o&&o._$AB.nextSibling,n),r.length=n)}_$AR(e=this._$AA.nextSibling,r){for(this._$AP?.(!1,!0,r);e!==this._$AB;){let o=Mo(e).nextSibling;Mo(e).remove(),e=o}}setConnected(e){this._$AM===void 0&&(this._$Cv=e,this._$AP?.(e))}},Je=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(e,r,o,n,a){this.type=1,this._$AH=f,this._$AN=void 0,this.element=e,this.name=r,this._$AM=n,this.options=a,o.length>2||o[0]!==""||o[1]!==""?(this._$AH=Array(o.length-1).fill(new String),this.strings=o):this._$AH=f}_$AI(e,r=this,o,n){let a=this.strings,i=!1;if(a===void 0)e=Qe(this,e,r,0),i=!xt(e)||e!==this._$AH&&e!==pe,i&&(this._$AH=e);else{let s=e,l,c;for(e=a[0],l=0;l<a.length-1;l++)c=Qe(this,s[o+l],r,l),c===pe&&(c=this._$AH[l]),i||=!xt(c)||c!==this._$AH[l],c===f?e=f:e!==f&&(e+=(c??"")+a[l+1]),this._$AH[l]=c}i&&!n&&this.j(e)}j(e){e===f?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,e??"")}},It=class extends Je{constructor(){super(...arguments),this.type=3}j(e){this.element[this.name]=e===f?void 0:e}},Ft=class extends Je{constructor(){super(...arguments),this.type=4}j(e){this.element.toggleAttribute(this.name,!!e&&e!==f)}},Ut=class extends Je{constructor(e,r,o,n,a){super(e,r,o,n,a),this.type=5}_$AI(e,r=this){if((e=Qe(this,e,r,0)??f)===pe)return;let o=this._$AH,n=e===f&&o!==f||e.capture!==o.capture||e.once!==o.once||e.passive!==o.passive,a=e!==f&&(o===f||n);n&&this.element.removeEventListener(this.name,this,o),a&&this.element.addEventListener(this.name,this,e),this._$AH=e}handleEvent(e){typeof this._$AH=="function"?this._$AH.call(this.options?.host??this.element,e):this._$AH.handleEvent(e)}},Kt=class{constructor(e,r,o){this.element=e,this.type=6,this._$AN=void 0,this._$AM=r,this.options=o}get _$AU(){return this._$AM._$AU}_$AI(e){Qe(this,e)}},No={M:Nr,P:ke,A:Vr,C:1,L:Go,R:Vt,D:Oo,V:Qe,I:nt,H:Je,N:Ft,U:Ut,B:It,F:Kt},Na=Gr.litHtmlPolyfillSupport;Na?.(zt,nt),(Gr.litHtmlVersions??=[]).push("3.3.3");var Vo=(t,e,r)=>{let o=r?.renderBefore??e,n=o._$litPart$;if(n===void 0){let a=r?.renderBefore??null;o._$litPart$=n=new nt(e.insertBefore(wt(),a),a,void 0,r??{})}return n._$AI(t),n};var Ur=globalThis,E=class extends _e{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let e=super.createRenderRoot();return this.renderOptions.renderBefore??=e.firstChild,e}update(e){let r=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(e),this._$Do=Vo(r,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return pe}};E._$litElement$=!0,E.finalized=!0,Ur.litElementHydrateSupport?.({LitElement:E});var Va=Ur.litElementPolyfillSupport;Va?.({LitElement:E});(Ur.litElementVersions??=[]).push("4.2.2");function Ia(t,e){if(t===e)return null;switch(e){case"ready":return"announce.ready";case"cooking":return t==="preheating"?"announce.preheated":null;case"done":return"announce.done";case"door_open":return"announce.door_open";case"press_start":return"announce.press_start";case"error":return"announce.error";case"offline":return"announce.offline";default:return null}}var Wt=class{constructor(){this.phases=new Map}observe(e,r){let o=[];for(let n of e){let a=this.phases.get(n.id);if(this.phases.set(n.id,n.phase),a===void 0)continue;let i=Ia(a,n.phase);i&&o.push(r(i,{name:n.name,error:n.error??""}))}return o.length?o.join(" "):null}};var Io={"panel.title":"Breville+","panel.menu":"Seitenleiste \xF6ffnen","panel.back":"Zur\xFCck","overview.no_area":"Kein Bereich","overview.loading":"Ger\xE4te werden geladen\u2026","overview.error_title":"Ger\xE4te konnten nicht geladen werden","overview.retry":"Erneut versuchen","overview.empty_title":"Noch keine Ger\xE4te","overview.empty_text":"Ger\xE4te erscheinen hier, sobald die Integration Breville+ Cooking sie hinzugef\xFCgt hat. F\xFCge ein Konto hinzu oder schalte in ihren Optionen das Panel in der Seitenleiste ein.","overview.empty_text_user":"Ger\xE4te erscheinen hier, sobald ein Administrator sie zur Integration Breville+ Cooking hinzugef\xFCgt hat.","overview.empty_link":"Einstellungen von Breville+ Cooking \xF6ffnen","overview.not_found_title":"Ger\xE4t nicht gefunden","overview.not_found_text":"Dieses Ger\xE4t ist nicht mehr Teil der Integration Breville+ Cooking, oder der Link ist falsch.","overview.back":"Zur\xFCck zu allen Ger\xE4ten","card.open_hint":"Alle Bedienelemente anzeigen","status.offline":"Offline","status.error":"Fehler","status.updating":"Aktualisierung","status.door_open":"T\xFCr offen","status.press_start_oven":"Start am Ofen dr\xFCcken","status.press_button_joule":"Taste am Joule dr\xFCcken","status.preheating":"Vorheizen","status.preheating_pct":"Vorheizen {n}\xA0%","status.ready":"Bereit zum Einlegen","status.cooking":"Garen","status.done":"Fertig","status.keeping_warm":"Warmhalten","status.idle":"Inaktiv","display.ready":"Bereit","display.end":"Fertig","display.press_start":"Start dr\xFCcken","display.error":"Fehler","display.off":"Aus","info.water":"Wasser","info.now_of_target":"{now} von {target}","info.time_left":"Restzeit","info.time":"Dauer","info.ends":"endet um {time}","info.paused":"pausiert","info.cook_time":"Garzeit","info.next":"Als N\xE4chstes","info.add_food":"Lebensmittel einlegen, dann \u201EWeiter\u201C dr\xFCcken","info.remove_food":"Lebensmittel entnehmen","info.oven_finished":"Lebensmittel entnehmen, dann \u201EBeenden\u201C dr\xFCcken","info.next_cook":"N\xE4chster Garvorgang","info.problem":"Problem","info.mode":"Modus","info.oven":"Ofen","info.rack":"Einschub","info.rack_value":"Ebene {n} \xB7 {accessory}","section.cook":"Garen","section.next_cook":"N\xE4chster Garvorgang","section.this_cook":"Dieser Garvorgang","section.presets":"Voreinstellungen","section.chart":"Temperatur","section.details":"Details","control.cook":"Garen","control.food_in":"Lebensmittel eingelegt","control.food_out":"Lebensmittel entnommen","control.water_temperature":"Wassertemperatur","control.oven_temperature":"Ofentemperatur","control.target":"Ziel","control.target_temperature":"Zieltemperatur","control.temperature":"Temperatur","control.time_left":"Restzeit","control.cook_time":"Garzeit","control.auto_start_timer":"Timer automatisch starten","control.mode":"Modus","control.level_broil":"Grillst\xE4rke","control.level_slow_cook":"Schongarstufe","control.convection":"Umluft","control.frozen":"Tiefk\xFChlware","control.keep_warm":"Warmhalten","control.door":"T\xFCr","control.rack":"Einschub","control.model":"Modell","control.finish":"Ausf\xFChrung","control.firmware":"Firmware","control.error":"Fehler","control.tested":"Steuerung","action.start":"Starten","action.stop":"Stoppen","action.finish":"Beenden","action.food_in":"Timer starten","action.food_out":"Beenden","confirm.start_sous_vide":"{name} mit {temp} f\xFCr {time} starten?","confirm.start_sous_vide_hold":"{name} mit {temp} ohne Zeitlimit starten?","confirm.start_oven":"Ofen im Modus {mode} f\xFCr {time} starten?","confirm.stop":"Garvorgang stoppen?","hint.start":"Startet einen Garvorgang mit den Einstellungen unten.","hint.finish":"Der Garvorgang ist vorbei. \u201EBeenden\u201C schlie\xDFt ihn ab.","hint.food_in":"Lege die Lebensmittel ein und starte dann den Timer.","hint.food_out":"Entnimm zum Abschluss die Lebensmittel.","hint.paused":"Pausiert","hint.changes_cook":"\xC4ndert den laufenden Garvorgang.","hint.changes_time_left":"Legt die Restzeit des laufenden Garvorgangs fest.","hint.auto_start_timer":"Startet den Timer, sobald das Wasser auf Temperatur ist, ohne auf die Lebensmittel zu warten.","hint.auto_start_timer_oven":"Startet den Timer, sobald der Ofen vorgeheizt ist, ohne auf die Lebensmittel zu warten.","hint.sensor_target":"Der Ofen h\xE4lt seinen Sensor bei {temp}, unter dem Sollwert.","hint.frozen":"Gart etwas l\xE4nger f\xFCr Tiefk\xFChlware.","hint.keep_warm":"H\xE4lt die Speisen warm, wenn der Garvorgang endet.","hint.untested":"Dieses Modell wurde noch nicht mit Home Assistant getestet.","reason.offline":"Das Ger\xE4t ist offline.","reason.unavailable":"Gerade nicht verf\xFCgbar.","reason.untested":"Die Steuerung des {product} wurde noch nicht getestet, daher \xFCberwacht Home Assistant das Ger\xE4t nur.","reason.open_options":"Steuerung in den Optionen der Integration erlauben","reason.oven_running":"Ein laufender Garvorgang im Ofen l\xE4sst sich nicht \xE4ndern. Stoppe ihn, um die Einstellungen zu \xE4ndern.","value.until_stopped":"Bis zum Stoppen","value.open":"Offen","value.closed":"Geschlossen","value.no_error":"Keiner","value.untested":"Noch nicht getestet","value.now":"Aktuell {value}","full.appliance":"Ger\xE4t","full.failed":"Das hat nicht geklappt.","full.preheat":"Vorheizen","full.preheat_value":"{n} Prozent","ctl.saving":"Wird gespeichert\u2026","ctl.decrease":"Verringern","ctl.increase":"Erh\xF6hen","ctl.off":"Aus","ctl.custom":"Andere","ctl.hours":"Stunden","ctl.minutes":"Minuten","ctl.h":"Std.","ctl.min":"Min.","ctl.set":"\xDCbernehmen","ctl.not_now":"Nicht jetzt","ctl.out_of_range":"W\xE4hle eine Dauer von {min} bis {max} aus.","unit.minutes":"{n} Min.","unit.hours":"{n} Std.","unit.hours_minutes":"{h} Std. {m} Min.","unit.days":"{n} Tg.","unit.days_hours":"{d} Tg. {h} Std.","finish.white_polished":"Wei\xDF mit poliertem Edelstahl","finish.brushed_stainless":"Geb\xFCrsteter Edelstahl","finish.black_stainless":"Schwarzer Edelstahl","mode.bake":"Backen","mode.air_fry":"Hei\xDFluftfrittieren","mode.roast":"Braten","mode.broil":"Grillen","mode.pizza":"Pizza","mode.cookies":"Kekse","mode.reheat":"Aufw\xE4rmen","mode.slow_cook":"Schongaren","mode.proof":"G\xE4ren","mode.warm":"Warmhalten","mode.dehydrate":"D\xF6rren","mode.bottom_bake":"Unterhitze","mode.gentle_broil":"Knuspriges Hei\xDFluftfrittieren","mode.bottom_broil":"Untere Grillfunktion","mode.outer_top_broil":"\xC4u\xDFere Grillfunktion","mode.middle_top_broil":"Mittlere Obergrillfunktion","mode.windy_broil":"Umluft-Grillen","mode.toast":"Toast","mode.bagel":"Bagel","mode.keep_warm":"Warmhalten","mode.crispy_reheat":"Knusprig aufw\xE4rmen","level.low":"Niedrig","level.medium":"Mittel","level.high":"Hoch","convection.off":"Aus","convection.on":"Ein","convection.super":"Super","convection_summary.off":"Ohne Umluft","convection_summary.on":"Umluft","convection_summary.super":"Super-Umluft","accessory.roasting_pan":"Fettpfanne","accessory.broil_rack":"Grillrost in der Fettpfanne","accessory.air_fry_basket":"Frittierkorb","accessory.pizza_pan":"Pizzablech","accessory.wire_rack":"Rost","accessory.pot":"Topf mit Deckel","food.croissants":"Croissants","food.casserole":"einem Auflauf","food.chicken":"einem ganzen H\xE4hnchen","food.steak":"einem Steak","food.fries":"Pommes frites","food.pizza":"einer Pizza","food.cookies":"Keksen","food.plate":"Resten auf einem Teller","food.dough":"einer Sch\xFCssel Teig","food.covered_dish":"einem abgedeckten Teller","food.fruit":"Obstscheiben","food.bread":"Brotscheiben","food.bagel":"Bagelh\xE4lften","food.pizza_slice":"einem St\xFCck Pizza","describe.sous_vide":"{product}, an einem Beh\xE4lter mit Wasser befestigt.","describe.water":"Das Wasser hat {now}.","describe.water_target":"Das Wasser hat {now}, Ziel {target}.","describe.time_left":"Noch {time}.","describe.time_paused":"Pausiert, noch {time}.","describe.food_bag":"Ein Beutel mit Lebensmitteln ist im Wasser.","describe.tipped":"Das Ger\xE4t ist umgekippt.","describe.low_water":"Der Wasserstand ist zu niedrig.","describe.oven_brushed_stainless":"{product} in geb\xFCrstetem Edelstahl.","describe.oven_black_stainless":"{product} in schwarzem Edelstahl.","describe.mode":"{mode}.","describe.oven_temperature":"Im Garraum {temp}.","describe.rack":"Ebene {n}: {accessory}.","describe.rack_food":"Ebene {n}: {accessory} mit {food}.","describe.door_open":"Die T\xFCr ist offen.","describe.fan_on":"Der L\xFCfter l\xE4uft.","describe.fan_super":"Der L\xFCfter l\xE4uft auf hoher Stufe.","announce.ready":"{name} ist bereit zum Einlegen.","announce.preheated":"{name} ist vorgeheizt und gart.","announce.done":"{name} ist fertig.","announce.door_open":"{name}: Die T\xFCr ist offen.","announce.press_start":"{name}: Start am Ger\xE4t dr\xFCcken.","announce.error":"{name}: {error}.","announce.offline":"{name} ist offline.","presets.builtin":"Vordefiniert","presets.custom":"Gespeichert","presets.none":"Noch keine gespeicherten Voreinstellungen. Ein Administrator kann welche speichern.","presets.none_admin":"Noch keine gespeicherten Voreinstellungen. Richte einen Garvorgang ein und speichere ihn dann hier.","presets.disabled_cooking":"Voreinstellungen gelten f\xFCr den n\xE4chsten Garvorgang. Stoppe oder beende zuerst den laufenden.","presets.applied":"Aus {name} \xFCbernommen. Dr\xFCcke \u201EStarten\u201C, wenn du so weit bist.","presets.saved":"{name} gespeichert.","presets.renamed":"Umbenannt in {name}.","presets.updated":"{name} mit den aktuellen Einstellungen aktualisiert.","presets.deleted":"{name} gel\xF6scht.","presets.save_current":"Aktuelle Einstellungen als Voreinstellung speichern","presets.save_hint":"Gespeicherte Voreinstellungen werden mit allen geteilt, die Home Assistant nutzen.","presets.name":"Name der Voreinstellung","presets.save":"Speichern","presets.cancel":"Abbrechen","presets.update":"Aktualisieren","presets.delete":"L\xF6schen","presets.rename_named":"{name} umbenennen","presets.update_named":"{name} mit den aktuellen Einstellungen aktualisieren","presets.delete_named":"{name} l\xF6schen","presets.delete_confirm":"{name} f\xFCr alle l\xF6schen?","presets.update_confirm":"Einstellungen von {name} durch die aktuellen ersetzen?","presets.frozen":"Tiefgek\xFChlt","presets.note.raw_safe_fish":"Verwende nur Fisch, der zum Rohverzehr geeignet ist.","presets.disclaimer":"Voreinstellungen sind ein Ausgangspunkt. Halte dich an eine verl\xE4ssliche Anleitung und pr\xFCfe, ob die Lebensmittel sicher gegart sind.","presets.error.cook_running":"Stoppe zuerst den Garvorgang: Voreinstellungen gelten f\xFCr den n\xE4chsten.","presets.error.unknown_appliance":"Dieses Ger\xE4t ist nicht mehr im Panel.","presets.error.unknown_preset":"Diese Voreinstellung gibt es nicht mehr.","presets.error.invalid_preset":"Diese Voreinstellung passt nicht zu diesem Ger\xE4t.","presets.error.too_many_presets":"Es sind h\xF6chstens 50 gespeicherte Voreinstellungen m\xF6glich. L\xF6sche zuerst eine.","presets.error.unavailable":"Das Ger\xE4t ist gerade nicht verf\xFCgbar.","presets.error.unauthorized":"Nur Administratoren k\xF6nnen gespeicherte Voreinstellungen \xE4ndern.","preset.steak_rare":"Steak, blutig","preset.steak_medium_rare":"Steak, rosa","preset.steak_medium":"Steak, medium","preset.steak_well_done":"Steak, durchgebraten","preset.beef_roast":"Rinderbraten","preset.short_ribs":"Querrippe vom Rind","preset.pork_chop":"Schweinekotelett","preset.pulled_pork":"Gezupfte Schweineschulter","preset.chicken_breast":"H\xE4hnchenbrust","preset.chicken_thighs":"H\xE4hnchenoberschenkel","preset.salmon":"Lachs","preset.white_fish":"Wei\xDFer Fisch","preset.shrimp":"Garnelen","preset.soft_eggs":"Weiche Eier","preset.vegetables":"Gem\xFCse","preset.frozen_fries":"Tiefk\xFChl-Pommes","preset.chicken_wings":"H\xE4hnchenfl\xFCgel","preset.frozen_pizza":"Tiefk\xFChlpizza","preset.fresh_pizza":"Frische Pizza","preset.roast_vegetables":"Ofengem\xFCse","preset.roast_chicken":"Brath\xE4hnchen","preset.cookies":"Kekse","preset.cake":"Kuchen","preset.leftovers":"Reste","preset.salmon_fillets":"Lachsfilets","preset.dried_fruit":"D\xF6rrobst","preset.bread_dough":"Brotteig","preset.pot_roast":"Schmorbraten","chart.loading":"Temperaturen des Garvorgangs werden geladen\u2026","chart.failed":"Der Temperaturverlauf konnte nicht gelesen werden. In einer Minute wird es erneut versucht.","chart.none":"Kein Garvorgang in den letzten Tagen. Das Diagramm zeigt den aktuellen oder den letzten Garvorgang.","chart.summary_now":"Aktuell {now}.","chart.summary_now_target":"Aktuell {now}, Ziel {target}.","chart.summary_last":"Am Ende waren es {now}.","chart.summary_last_target":"Am Ende waren es {now}, Ziel {target}.","chart.last_cook":"Letzter Garvorgang, {start} bis {end}.","chart.at_temperature_since":"Auf Temperatur seit {time}.","chart.sensor_summary":"Der Ofen h\xE4lt seinen Sensor bei {temp}.","chart.sensor_caption":"Die gestrichelte Linie zeigt, wo der Ofen seinen eigenen Sensor h\xE4lt: bewusst unter dem Sollwert, die Abweichung ist also kein Fehler.","chart.last_day":"Angezeigt wird der letzte Tag.","chart.temperature":"Temperatur","chart.target":"Ziel","chart.sensor_target":"Sensorziel","chart.time":"Uhrzeit","chart.show_table":"Als Tabelle anzeigen","chart.hide_table":"Tabelle ausblenden","chart.table_caption":"Temperaturen w\xE4hrend des Garvorgangs"};var Fo={"panel.title":"Breville+","panel.menu":"Open the sidebar","panel.back":"Back","overview.no_area":"No area","overview.loading":"Loading appliances\u2026","overview.error_title":"Couldn't load the appliances","overview.retry":"Try again","overview.empty_title":"No appliances yet","overview.empty_text":"Appliances appear here once the Breville+ Cooking integration has added them. Add an account, or turn on the sidebar panel in its options.","overview.empty_text_user":"Appliances appear here once an administrator has added them to the Breville+ Cooking integration.","overview.empty_link":"Open Breville+ Cooking settings","overview.not_found_title":"Appliance not found","overview.not_found_text":"This appliance isn't in the Breville+ Cooking integration any more, or the link is wrong.","overview.back":"Back to all appliances","card.open_hint":"Show all controls","status.offline":"Offline","status.error":"Error","status.updating":"Updating","status.door_open":"Door open","status.press_start_oven":"Press Start on the oven","status.press_button_joule":"Press the button on the Joule","status.preheating":"Preheating","status.preheating_pct":"Preheating {n}%","status.ready":"Ready for food","status.cooking":"Cooking","status.done":"Done","status.keeping_warm":"Keeping warm","status.idle":"Idle","display.ready":"Ready","display.end":"Done","display.press_start":"Press Start","display.error":"Error","display.off":"Off","info.water":"Water","info.now_of_target":"{now} of {target}","info.time_left":"Time left","info.time":"Time","info.ends":"ends {time}","info.paused":"paused","info.cook_time":"Cook time","info.next":"Next","info.add_food":"Add the food, then press Continue","info.remove_food":"Take the food out","info.oven_finished":"Take the food out, then press Finish","info.next_cook":"Next cook","info.problem":"Problem","info.mode":"Mode","info.oven":"Oven","info.rack":"Rack","info.rack_value":"Position {n} \xB7 {accessory}","section.cook":"Cook","section.next_cook":"Next cook","section.this_cook":"This cook","section.presets":"Presets","section.chart":"Temperature","section.details":"Details","control.cook":"Cook","control.food_in":"Food is in","control.food_out":"Food is out","control.water_temperature":"Water temperature","control.oven_temperature":"Oven temperature","control.target":"Target","control.target_temperature":"Target temperature","control.temperature":"Temperature","control.time_left":"Time left","control.cook_time":"Cook time","control.auto_start_timer":"Start timer automatically","control.mode":"Mode","control.level_broil":"Broil level","control.level_slow_cook":"Slow cook level","control.convection":"Convection","control.frozen":"Frozen food","control.keep_warm":"Keep warm","control.door":"Door","control.rack":"Rack","control.model":"Model","control.finish":"Finish","control.firmware":"Firmware","control.error":"Error","control.tested":"Control","action.start":"Start","action.stop":"Stop","action.finish":"Finish","action.food_in":"Start the timer","action.food_out":"Finish","confirm.start_sous_vide":"Start the {name} at {temp} for {time}?","confirm.start_sous_vide_hold":"Start the {name} at {temp} until it's stopped?","confirm.start_oven":"Start the oven at {mode} for {time}?","confirm.stop":"Stop the cook?","hint.start":"Starts a cook with the settings below.","hint.finish":"The cook is over. Finish closes it.","hint.food_in":"Put the food in, then start the timer.","hint.food_out":"Take the food out to finish.","hint.paused":"Paused","hint.changes_cook":"Changes the running cook.","hint.changes_time_left":"Sets the time left of the running cook.","hint.auto_start_timer":"Start the timer once the water is up to temperature, without waiting for the food.","hint.auto_start_timer_oven":"Start the timer once the oven is preheated, without waiting for the food.","hint.sensor_target":"It holds its sensor at {temp}, below the setpoint.","hint.frozen":"Cooks a little longer for frozen food.","hint.keep_warm":"Keeps the food warm when the cook ends.","hint.untested":"Nobody has tested this model with Home Assistant yet.","reason.offline":"The appliance is offline.","reason.unavailable":"Not available right now.","reason.untested":"Control of the {product} hasn't been tested yet, so Home Assistant only monitors it.","reason.open_options":"Allow control in the integration's options","reason.oven_running":"A running oven cook can't be changed. Stop it to change the settings.","value.until_stopped":"Until stopped","value.open":"Open","value.closed":"Closed","value.no_error":"None","value.untested":"Not tested yet","value.now":"Now {value}","full.appliance":"Appliance","full.failed":"That didn't work.","full.preheat":"Preheating","full.preheat_value":"{n} percent","ctl.saving":"Saving\u2026","ctl.decrease":"Decrease","ctl.increase":"Increase","ctl.off":"Off","ctl.custom":"Custom","ctl.hours":"Hours","ctl.minutes":"Minutes","ctl.h":"h","ctl.min":"min","ctl.set":"Set","ctl.not_now":"Not now","ctl.out_of_range":"Choose from {min} to {max}.","unit.minutes":"{n} min","unit.hours":"{n} h","unit.hours_minutes":"{h} h {m} min","unit.days":"{n} d","unit.days_hours":"{d} d {h} h","finish.white_polished":"White with polished stainless","finish.brushed_stainless":"Brushed stainless steel","finish.black_stainless":"Black stainless steel","mode.bake":"Bake","mode.air_fry":"Air fry","mode.roast":"Roast","mode.broil":"Broil","mode.pizza":"Pizza","mode.cookies":"Cookies","mode.reheat":"Reheat","mode.slow_cook":"Slow cook","mode.proof":"Proof","mode.warm":"Warm","mode.dehydrate":"Dehydrate","mode.bottom_bake":"Bottom bake","mode.gentle_broil":"Crispier air fry","mode.bottom_broil":"Bottom broil","mode.outer_top_broil":"Outer broil","mode.middle_top_broil":"Middle top broil","mode.windy_broil":"Convection broil","mode.toast":"Toast","mode.bagel":"Bagel","mode.keep_warm":"Keep warm","mode.crispy_reheat":"Crispy reheat","level.low":"Low","level.medium":"Medium","level.high":"High","convection.off":"Off","convection.on":"On","convection.super":"Super","convection_summary.off":"No convection","convection_summary.on":"Convection","convection_summary.super":"Super convection","accessory.roasting_pan":"roasting pan","accessory.broil_rack":"broil rack in the roasting pan","accessory.air_fry_basket":"air fry basket","accessory.pizza_pan":"pizza pan","accessory.wire_rack":"wire rack","accessory.pot":"covered pot","food.croissants":"croissants","food.casserole":"a casserole","food.chicken":"a whole chicken","food.steak":"a steak","food.fries":"fries","food.pizza":"a pizza","food.cookies":"cookies","food.plate":"a plate of leftovers","food.dough":"a bowl of dough","food.covered_dish":"a covered dish","food.fruit":"fruit slices","food.bread":"slices of bread","food.bagel":"bagel halves","food.pizza_slice":"a slice of pizza","describe.sous_vide":"{product} clipped in a container of water.","describe.water":"Water {now}.","describe.water_target":"Water {now}, target {target}.","describe.time_left":"{time} left.","describe.time_paused":"Paused with {time} left.","describe.food_bag":"A bag of food is in the water.","describe.tipped":"It has tipped over.","describe.low_water":"The water is too low.","describe.oven_brushed_stainless":"{product} in brushed stainless steel.","describe.oven_black_stainless":"{product} in black stainless steel.","describe.mode":"{mode}.","describe.oven_temperature":"Inside {temp}.","describe.rack":"Rack in position {n} with the {accessory}.","describe.rack_food":"Rack in position {n} with {food} on the {accessory}.","describe.door_open":"The door is open.","describe.fan_on":"The fan is on.","describe.fan_super":"The fan is on high.","announce.ready":"{name} is ready for food.","announce.preheated":"{name} is preheated and cooking.","announce.done":"{name} is done.","announce.door_open":"{name}: the door is open.","announce.press_start":"{name}: press Start on the appliance.","announce.error":"{name}: {error}.","announce.offline":"{name} is offline.","presets.builtin":"Built-in","presets.custom":"Saved","presets.none":"No saved presets yet. An administrator can save some.","presets.none_admin":"No saved presets yet. Set up a cook, then save it here.","presets.disabled_cooking":"Presets fill in the next cook. Stop or finish this one first.","presets.applied":"Filled in from {name}. Press Start when you're ready.","presets.saved":"Saved {name}.","presets.renamed":"Renamed to {name}.","presets.updated":"Updated {name} with the current settings.","presets.deleted":"Deleted {name}.","presets.save_current":"Save the current settings as a preset","presets.save_hint":"Saved presets are shared with everyone who uses Home Assistant.","presets.name":"Preset name","presets.save":"Save","presets.cancel":"Cancel","presets.update":"Update","presets.delete":"Delete","presets.rename_named":"Rename {name}","presets.update_named":"Update {name} with the current settings","presets.delete_named":"Delete {name}","presets.delete_confirm":"Delete {name} for everyone?","presets.update_confirm":"Replace {name}'s settings with the current ones?","presets.frozen":"Frozen","presets.note.raw_safe_fish":"Use fish that's safe to eat raw.","presets.disclaimer":"Presets are a starting point. Follow a trusted cooking guide, and check that food is cooked safely.","presets.error.cook_running":"Stop the cook first: presets fill in the next one.","presets.error.unknown_appliance":"This appliance isn't in the panel any more.","presets.error.unknown_preset":"That preset isn't there any more.","presets.error.invalid_preset":"That preset doesn't fit this appliance.","presets.error.too_many_presets":"There can be at most 50 saved presets. Delete one first.","presets.error.unavailable":"The appliance isn't available right now.","presets.error.unauthorized":"Only administrators can change saved presets.","preset.steak_rare":"Steak, rare","preset.steak_medium_rare":"Steak, medium-rare","preset.steak_medium":"Steak, medium","preset.steak_well_done":"Steak, well done","preset.beef_roast":"Beef roast","preset.short_ribs":"Short ribs","preset.pork_chop":"Pork chop","preset.pulled_pork":"Pulled pork shoulder","preset.chicken_breast":"Chicken breast","preset.chicken_thighs":"Chicken thighs","preset.salmon":"Salmon","preset.white_fish":"White fish","preset.shrimp":"Shrimp","preset.soft_eggs":"Soft eggs","preset.vegetables":"Vegetables","preset.frozen_fries":"Frozen fries","preset.chicken_wings":"Chicken wings","preset.frozen_pizza":"Frozen pizza","preset.fresh_pizza":"Fresh pizza","preset.roast_vegetables":"Roast vegetables","preset.roast_chicken":"Roast chicken","preset.cookies":"Cookies","preset.cake":"Cake","preset.leftovers":"Leftovers","preset.salmon_fillets":"Salmon fillets","preset.dried_fruit":"Dried fruit","preset.bread_dough":"Bread dough","preset.pot_roast":"Pot roast","chart.loading":"Loading the cook's temperatures\u2026","chart.failed":"Couldn't read the temperature history. It's tried again in a minute.","chart.none":"No cook in the last few days. The chart shows the current cook, or the last one.","chart.summary_now":"Now {now}.","chart.summary_now_target":"Now {now}, target {target}.","chart.summary_last":"It ended at {now}.","chart.summary_last_target":"It ended at {now}, target {target}.","chart.last_cook":"Last cook, {start} to {end}.","chart.at_temperature_since":"At temperature since {time}.","chart.sensor_summary":"The oven holds its sensor at {temp}.","chart.sensor_caption":"The dashed line is where the oven holds its own sensor: below the setpoint, by design, so the gap isn't a fault.","chart.last_day":"Showing the last day.","chart.temperature":"Temperature","chart.target":"Target","chart.sensor_target":"Sensor target","chart.time":"Time","chart.show_table":"Show as a table","chart.hide_table":"Hide the table","chart.table_caption":"Temperatures during the cook"};var Uo={"panel.title":"Breville+","panel.menu":"Abrir la barra lateral","panel.back":"Atr\xE1s","overview.no_area":"Sin \xE1rea","overview.loading":"Cargando aparatos\u2026","overview.error_title":"No se han podido cargar los aparatos","overview.retry":"Reintentar","overview.empty_title":"A\xFAn no hay aparatos","overview.empty_text":"Los aparatos aparecer\xE1n aqu\xED en cuanto la integraci\xF3n Breville+ Cooking los a\xF1ada. A\xF1ade una cuenta o activa el panel de la barra lateral en sus opciones.","overview.empty_text_user":"Los aparatos aparecer\xE1n aqu\xED en cuanto un administrador los a\xF1ada a la integraci\xF3n Breville+ Cooking.","overview.empty_link":"Abrir los ajustes de Breville+ Cooking","overview.not_found_title":"Aparato no encontrado","overview.not_found_text":"Este aparato ya no est\xE1 en la integraci\xF3n Breville+ Cooking o el enlace es incorrecto.","overview.back":"Volver a todos los aparatos","card.open_hint":"Mostrar todos los controles","status.offline":"Sin conexi\xF3n","status.error":"Error","status.updating":"Actualizando","status.door_open":"Puerta abierta","status.press_start_oven":"Pulsa Start en el horno","status.press_button_joule":"Pulsa el bot\xF3n del Joule","status.preheating":"Precalentando","status.preheating_pct":"Precalentando {n} %","status.ready":"Listo para a\xF1adir la comida","status.cooking":"Cocinando","status.done":"Terminado","status.keeping_warm":"Manteniendo caliente","status.idle":"Inactivo","display.ready":"Listo","display.end":"Fin","display.press_start":"Pulsa Start","display.error":"Error","display.off":"Apagado","info.water":"Agua","info.now_of_target":"{now} de {target}","info.time_left":"Tiempo restante","info.time":"Tiempo","info.ends":"termina a las {time}","info.paused":"en pausa","info.cook_time":"Tiempo de cocci\xF3n","info.next":"Siguiente paso","info.add_food":"A\xF1ade la comida y pulsa Continuar","info.remove_food":"Saca la comida","info.oven_finished":"Saca la comida y pulsa Finalizar","info.next_cook":"Pr\xF3xima cocci\xF3n","info.problem":"Problema","info.mode":"Modo","info.oven":"Horno","info.rack":"Rejilla","info.rack_value":"Posici\xF3n {n} \xB7 {accessory}","section.cook":"Cocci\xF3n","section.next_cook":"Pr\xF3xima cocci\xF3n","section.this_cook":"Esta cocci\xF3n","section.presets":"Preajustes","section.chart":"Temperatura","section.details":"Detalles","control.cook":"Cocci\xF3n","control.food_in":"Comida dentro","control.food_out":"Comida fuera","control.water_temperature":"Temperatura del agua","control.oven_temperature":"Temperatura del horno","control.target":"Objetivo","control.target_temperature":"Temperatura deseada","control.temperature":"Temperatura","control.time_left":"Tiempo restante","control.cook_time":"Tiempo de cocci\xF3n","control.auto_start_timer":"Iniciar temporizador autom\xE1ticamente","control.mode":"Modo","control.level_broil":"Nivel de gratinado","control.level_slow_cook":"Nivel de cocci\xF3n lenta","control.convection":"Convecci\xF3n","control.frozen":"Alimentos congelados","control.keep_warm":"Mantener caliente","control.door":"Puerta","control.rack":"Rejilla","control.model":"Modelo","control.finish":"Acabado","control.firmware":"Firmware","control.error":"Error","control.tested":"Control","action.start":"Iniciar","action.stop":"Detener","action.finish":"Finalizar","action.food_in":"Iniciar temporizador","action.food_out":"Finalizar","confirm.start_sous_vide":"\xBFIniciar el {name} a {temp} durante {time}?","confirm.start_sous_vide_hold":"\xBFIniciar el {name} a {temp} hasta que lo detengas?","confirm.start_oven":"\xBFIniciar el horno en modo {mode} durante {time}?","confirm.stop":"\xBFDetener la cocci\xF3n?","hint.start":"Inicia una cocci\xF3n con los ajustes de abajo.","hint.finish":"La cocci\xF3n ha terminado. Pulsa Finalizar para cerrarla.","hint.food_in":"A\xF1ade la comida y luego inicia el temporizador.","hint.food_out":"Saca la comida para finalizar.","hint.paused":"En pausa","hint.changes_cook":"Cambia la cocci\xF3n en curso.","hint.changes_time_left":"Ajusta el tiempo restante de la cocci\xF3n en curso.","hint.auto_start_timer":"Inicia el temporizador en cuanto el agua alcance la temperatura, sin esperar a la comida.","hint.auto_start_timer_oven":"Inicia el temporizador en cuanto el horno est\xE9 precalentado, sin esperar a la comida.","hint.sensor_target":"Mantiene su sensor a {temp}, por debajo de la temperatura programada.","hint.frozen":"Alarga un poco la cocci\xF3n para alimentos congelados.","hint.keep_warm":"Mantiene la comida caliente cuando termina la cocci\xF3n.","hint.untested":"Nadie ha probado a\xFAn este modelo con Home Assistant.","reason.offline":"El aparato est\xE1 sin conexi\xF3n.","reason.unavailable":"No disponible en este momento.","reason.untested":"El control del {product} a\xFAn no se ha probado, as\xED que Home Assistant solo lo supervisa.","reason.open_options":"Permitir el control en las opciones de la integraci\xF3n","reason.oven_running":"No se puede cambiar una cocci\xF3n del horno en curso. Detenla para cambiar los ajustes.","value.until_stopped":"Sin l\xEDmite","value.open":"Abierta","value.closed":"Cerrada","value.no_error":"Ninguno","value.untested":"A\xFAn no probado","value.now":"Ahora: {value}","full.appliance":"Aparato","full.failed":"No ha funcionado.","full.preheat":"Precalentamiento","full.preheat_value":"{n} por ciento","ctl.saving":"Guardando\u2026","ctl.decrease":"Disminuir","ctl.increase":"Aumentar","ctl.off":"Desactivado","ctl.custom":"Personalizado","ctl.hours":"Horas","ctl.minutes":"Minutos","ctl.h":"h","ctl.min":"min","ctl.set":"Aplicar","ctl.not_now":"Ahora no","ctl.out_of_range":"Elige entre {min} y {max}.","unit.minutes":"{n} min","unit.hours":"{n} h","unit.hours_minutes":"{h} h {m} min","unit.days":"{n} d","unit.days_hours":"{d} d {h} h","finish.white_polished":"Blanco con acero inoxidable pulido","finish.brushed_stainless":"Acero inoxidable cepillado","finish.black_stainless":"Acero inoxidable negro","mode.bake":"Hornear","mode.air_fry":"Fre\xEDr con aire","mode.roast":"Asar","mode.broil":"Gratinar","mode.pizza":"Pizza","mode.cookies":"Galletas","mode.reheat":"Recalentar","mode.slow_cook":"Cocci\xF3n lenta","mode.proof":"Fermentar","mode.warm":"Mantener caliente","mode.dehydrate":"Deshidratar","mode.bottom_bake":"Hornear por abajo","mode.gentle_broil":"Fre\xEDr con aire m\xE1s crujiente","mode.bottom_broil":"Gratinar por abajo","mode.outer_top_broil":"Gratinar exterior","mode.middle_top_broil":"Gratinar centro superior","mode.windy_broil":"Gratinar con convecci\xF3n","mode.toast":"Tostada","mode.bagel":"Bagel","mode.keep_warm":"Mantener caliente","mode.crispy_reheat":"Recalentar crujiente","level.low":"Bajo","level.medium":"Medio","level.high":"Alto","convection.off":"Desactivada","convection.on":"Activada","convection.super":"S\xFAper","convection_summary.off":"Sin convecci\xF3n","convection_summary.on":"Convecci\xF3n","convection_summary.super":"S\xFAper convecci\xF3n","accessory.roasting_pan":"bandeja para asar","accessory.broil_rack":"rejilla para gratinar sobre la bandeja para asar","accessory.air_fry_basket":"cesta para fre\xEDr con aire","accessory.pizza_pan":"bandeja para pizza","accessory.wire_rack":"rejilla","accessory.pot":"olla tapada","food.croissants":"cruasanes","food.casserole":"un gratinado","food.chicken":"un pollo entero","food.steak":"un filete","food.fries":"patatas fritas","food.pizza":"una pizza","food.cookies":"galletas","food.plate":"un plato de sobras","food.dough":"un bol de masa","food.covered_dish":"un plato tapado","food.fruit":"rodajas de fruta","food.bread":"rebanadas de pan","food.bagel":"mitades de bagel","food.pizza_slice":"una porci\xF3n de pizza","describe.sous_vide":"{product} enganchado a un recipiente con agua.","describe.water":"Agua a {now}.","describe.water_target":"Agua a {now}, objetivo {target}.","describe.time_left":"Tiempo restante: {time}.","describe.time_paused":"En pausa. Tiempo restante: {time}.","describe.food_bag":"Hay una bolsa de comida en el agua.","describe.tipped":"Se ha volcado.","describe.low_water":"El nivel de agua es demasiado bajo.","describe.oven_brushed_stainless":"{product} de acero inoxidable cepillado.","describe.oven_black_stainless":"{product} de acero inoxidable negro.","describe.mode":"{mode}.","describe.oven_temperature":"Temperatura interior: {temp}.","describe.rack":"En la posici\xF3n {n} est\xE1 la {accessory}.","describe.rack_food":"En la posici\xF3n {n} hay {food} en la {accessory}.","describe.door_open":"La puerta est\xE1 abierta.","describe.fan_on":"El ventilador est\xE1 encendido.","describe.fan_super":"El ventilador est\xE1 al m\xE1ximo.","announce.ready":"{name}: ya puedes a\xF1adir la comida.","announce.preheated":"{name} ya se ha precalentado y est\xE1 cocinando.","announce.done":"{name} ha terminado.","announce.door_open":"{name}: la puerta est\xE1 abierta.","announce.press_start":"{name}: pulsa Start en el aparato.","announce.error":"{name}: {error}.","announce.offline":"{name} est\xE1 sin conexi\xF3n.","presets.builtin":"Predefinidos","presets.custom":"Guardados","presets.none":"A\xFAn no hay preajustes guardados. Un administrador puede guardar algunos.","presets.none_admin":"A\xFAn no hay preajustes guardados. Configura una cocci\xF3n y gu\xE1rdala aqu\xED.","presets.disabled_cooking":"Los preajustes se aplican a la pr\xF3xima cocci\xF3n. Primero det\xE9n o finaliza la actual.","presets.applied":"Ajustes cargados desde {name}. Pulsa Iniciar cuando quieras.","presets.saved":"Se ha guardado {name}.","presets.renamed":"Nuevo nombre: {name}.","presets.updated":"Se ha actualizado {name} con los ajustes actuales.","presets.deleted":"Se ha eliminado {name}.","presets.save_current":"Guardar los ajustes actuales como preajuste","presets.save_hint":"Los preajustes guardados se comparten con todos los que usan Home Assistant.","presets.name":"Nombre del preajuste","presets.save":"Guardar","presets.cancel":"Cancelar","presets.update":"Actualizar","presets.delete":"Eliminar","presets.rename_named":"Cambiar el nombre de {name}","presets.update_named":"Actualizar {name} con los ajustes actuales","presets.delete_named":"Eliminar {name}","presets.delete_confirm":"\xBFEliminar {name} para todos?","presets.update_confirm":"\xBFSustituir los ajustes de {name} por los actuales?","presets.frozen":"Congelado","presets.note.raw_safe_fish":"Usa pescado apto para comer crudo.","presets.disclaimer":"Los preajustes son un punto de partida. Sigue una gu\xEDa de cocina fiable y comprueba que la comida se cocina de forma segura.","presets.error.cook_running":"Det\xE9n primero la cocci\xF3n: los preajustes se aplican a la siguiente.","presets.error.unknown_appliance":"Este aparato ya no est\xE1 en el panel.","presets.error.unknown_preset":"Ese preajuste ya no existe.","presets.error.invalid_preset":"Ese preajuste no es compatible con este aparato.","presets.error.too_many_presets":"Se pueden guardar 50 preajustes como m\xE1ximo. Elimina uno primero.","presets.error.unavailable":"El aparato no est\xE1 disponible en este momento.","presets.error.unauthorized":"Solo los administradores pueden cambiar los preajustes guardados.","preset.steak_rare":"Filete, poco hecho","preset.steak_medium_rare":"Filete, al punto","preset.steak_medium":"Filete, hecho","preset.steak_well_done":"Filete, muy hecho","preset.beef_roast":"Rosbif","preset.short_ribs":"Costilla de vaca","preset.pork_chop":"Chuleta de cerdo","preset.pulled_pork":"Paleta de cerdo desmenuzada","preset.chicken_breast":"Pechuga de pollo","preset.chicken_thighs":"Contramuslos de pollo","preset.salmon":"Salm\xF3n","preset.white_fish":"Pescado blanco","preset.shrimp":"Gambas","preset.soft_eggs":"Huevos pasados por agua","preset.vegetables":"Verduras","preset.frozen_fries":"Patatas fritas congeladas","preset.chicken_wings":"Alitas de pollo","preset.frozen_pizza":"Pizza congelada","preset.fresh_pizza":"Pizza fresca","preset.roast_vegetables":"Verduras asadas","preset.roast_chicken":"Pollo asado","preset.cookies":"Galletas","preset.cake":"Bizcocho","preset.leftovers":"Sobras","preset.salmon_fillets":"Filetes de salm\xF3n","preset.dried_fruit":"Fruta deshidratada","preset.bread_dough":"Masa de pan","preset.pot_roast":"Estofado de ternera","chart.loading":"Cargando las temperaturas de la cocci\xF3n\u2026","chart.failed":"No se ha podido leer el historial de temperaturas. Se volver\xE1 a intentar en un minuto.","chart.none":"No ha habido cocciones en los \xFAltimos d\xEDas. El gr\xE1fico muestra la cocci\xF3n actual o la \xFAltima.","chart.summary_now":"Ahora est\xE1 a {now}.","chart.summary_now_target":"Ahora est\xE1 a {now}, objetivo {target}.","chart.summary_last":"Termin\xF3 a {now}.","chart.summary_last_target":"Termin\xF3 a {now}, objetivo {target}.","chart.last_cook":"\xDAltima cocci\xF3n, de {start} a {end}.","chart.at_temperature_since":"A temperatura desde {time}.","chart.sensor_summary":"El horno mantiene su sensor a {temp}.","chart.sensor_caption":"La l\xEDnea discontinua indica la temperatura a la que el horno mantiene su propio sensor: por debajo de la programada, por dise\xF1o, as\xED que la diferencia no es una aver\xEDa.","chart.last_day":"Se muestra el \xFAltimo d\xEDa.","chart.temperature":"Temperatura","chart.target":"Objetivo","chart.sensor_target":"Objetivo del sensor","chart.time":"Hora","chart.show_table":"Mostrar como tabla","chart.hide_table":"Ocultar la tabla","chart.table_caption":"Temperaturas durante la cocci\xF3n"};var Ko={"panel.title":"Breville+","panel.menu":"Ouvrir la barre lat\xE9rale","panel.back":"Retour","overview.no_area":"Aucune pi\xE8ce","overview.loading":"Chargement des appareils\u2026","overview.error_title":"Impossible de charger les appareils","overview.retry":"R\xE9essayer","overview.empty_title":"Aucun appareil pour l'instant","overview.empty_text":"Les appareils apparaissent ici d\xE8s que l'int\xE9gration Breville+ Cooking les a ajout\xE9s. Ajoutez un compte ou activez le panneau de la barre lat\xE9rale dans ses options.","overview.empty_text_user":"Les appareils apparaissent ici d\xE8s qu'un administrateur les a ajout\xE9s \xE0 l'int\xE9gration Breville+ Cooking.","overview.empty_link":"Ouvrir les param\xE8tres de Breville+ Cooking","overview.not_found_title":"Appareil introuvable","overview.not_found_text":"Cet appareil ne fait plus partie de l'int\xE9gration Breville+ Cooking, ou le lien est incorrect.","overview.back":"Retour \xE0 tous les appareils","card.open_hint":"Afficher toutes les commandes","status.offline":"Hors ligne","status.error":"Erreur","status.updating":"Mise \xE0 jour","status.door_open":"Porte ouverte","status.press_start_oven":"Appuyez sur Start sur le four","status.press_button_joule":"Appuyez sur le bouton du Joule","status.preheating":"Pr\xE9chauffage","status.preheating_pct":"Pr\xE9chauffage {n}\xA0%","status.ready":"Pr\xEAt pour les aliments","status.cooking":"Cuisson en cours","status.done":"Termin\xE9","status.keeping_warm":"Maintien au chaud","status.idle":"Inactif","display.ready":"Pr\xEAt","display.end":"Termin\xE9","display.press_start":"Appuyez sur Start","display.error":"Erreur","display.off":"\xC9teint","info.water":"Eau","info.now_of_target":"{now} sur {target}","info.time_left":"Temps restant","info.time":"Dur\xE9e","info.ends":"fin \xE0 {time}","info.paused":"en pause","info.cook_time":"Temps de cuisson","info.next":"Ensuite","info.add_food":"Ajoutez les aliments, puis appuyez sur Continuer","info.remove_food":"Retirez les aliments","info.oven_finished":"Retirez les aliments, puis appuyez sur Terminer","info.next_cook":"Prochaine cuisson","info.problem":"Probl\xE8me","info.mode":"Mode","info.oven":"Four","info.rack":"Grille","info.rack_value":"Niveau {n} \xB7 {accessory}","section.cook":"Cuisson","section.next_cook":"Prochaine cuisson","section.this_cook":"Cette cuisson","section.presets":"Pr\xE9r\xE9glages","section.chart":"Temp\xE9rature","section.details":"D\xE9tails","control.cook":"Cuisson","control.food_in":"Aliments en place","control.food_out":"Aliments retir\xE9s","control.water_temperature":"Temp\xE9rature de l'eau","control.oven_temperature":"Temp\xE9rature du four","control.target":"Cible","control.target_temperature":"Temp\xE9rature cible","control.temperature":"Temp\xE9rature","control.time_left":"Temps restant","control.cook_time":"Temps de cuisson","control.auto_start_timer":"D\xE9marrer le minuteur automatiquement","control.mode":"Mode","control.level_broil":"Intensit\xE9 du gril","control.level_slow_cook":"Niveau de cuisson lente","control.convection":"Convection","control.frozen":"Aliments surgel\xE9s","control.keep_warm":"Maintien au chaud","control.door":"Porte","control.rack":"Grille","control.model":"Mod\xE8le","control.finish":"Finition","control.firmware":"Micrologiciel","control.error":"Erreur","control.tested":"Contr\xF4le","action.start":"D\xE9marrer","action.stop":"Arr\xEAter","action.finish":"Terminer","action.food_in":"D\xE9marrer le minuteur","action.food_out":"Terminer","confirm.start_sous_vide":"D\xE9marrer le {name} \xE0 {temp} pendant {time}\xA0?","confirm.start_sous_vide_hold":"D\xE9marrer le {name} \xE0 {temp} jusqu'\xE0 l'arr\xEAt\xA0?","confirm.start_oven":"D\xE9marrer le four en mode {mode} pendant {time}\xA0?","confirm.stop":"Arr\xEAter la cuisson\xA0?","hint.start":"Lance une cuisson avec les r\xE9glages ci-dessous.","hint.finish":"La cuisson est termin\xE9e. Appuyez sur Terminer pour la clore.","hint.food_in":"Ajoutez les aliments, puis d\xE9marrez le minuteur.","hint.food_out":"Retirez les aliments pour terminer.","hint.paused":"En pause","hint.changes_cook":"Modifie la cuisson en cours.","hint.changes_time_left":"D\xE9finit le temps restant de la cuisson en cours.","hint.auto_start_timer":"D\xE9marre le minuteur d\xE8s que l'eau est \xE0 temp\xE9rature, sans attendre les aliments.","hint.auto_start_timer_oven":"D\xE9marre le minuteur d\xE8s que le four est pr\xE9chauff\xE9, sans attendre les aliments.","hint.sensor_target":"Le four maintient son capteur \xE0 {temp}, sous la consigne.","hint.frozen":"Cuit un peu plus longtemps pour les aliments surgel\xE9s.","hint.keep_warm":"Garde les aliments au chaud \xE0 la fin de la cuisson.","hint.untested":"Personne n'a encore test\xE9 ce mod\xE8le avec Home Assistant.","reason.offline":"L'appareil est hors ligne.","reason.unavailable":"Indisponible pour le moment.","reason.untested":"Le contr\xF4le du {product} n'a pas encore \xE9t\xE9 test\xE9\xA0: Home Assistant se contente donc de le surveiller.","reason.open_options":"Autoriser le contr\xF4le dans les options de l'int\xE9gration","reason.oven_running":"Une cuisson au four en cours ne peut pas \xEAtre modifi\xE9e. Arr\xEAtez-la pour changer les r\xE9glages.","value.until_stopped":"Jusqu'\xE0 l'arr\xEAt","value.open":"Ouverte","value.closed":"Ferm\xE9e","value.no_error":"Aucune","value.untested":"Pas encore test\xE9","value.now":"Actuellement {value}","full.appliance":"Appareil","full.failed":"Cela n'a pas fonctionn\xE9.","full.preheat":"Pr\xE9chauffage","full.preheat_value":"{n} pour cent","ctl.saving":"Enregistrement\u2026","ctl.decrease":"Diminuer","ctl.increase":"Augmenter","ctl.off":"D\xE9sactiv\xE9","ctl.custom":"Autre","ctl.hours":"Heures","ctl.minutes":"Minutes","ctl.h":"h","ctl.min":"min","ctl.set":"Valider","ctl.not_now":"Pas maintenant","ctl.out_of_range":"Choisissez une dur\xE9e entre {min} et {max}.","unit.minutes":"{n}\xA0min","unit.hours":"{n}\xA0h","unit.hours_minutes":"{h}\xA0h {m}\xA0min","unit.days":"{n}\xA0j","unit.days_hours":"{d}\xA0j {h}\xA0h","finish.white_polished":"Blanc et inox poli","finish.brushed_stainless":"Inox bross\xE9","finish.black_stainless":"Inox noir","mode.bake":"Cuisson","mode.air_fry":"Friture \xE0 air chaud","mode.roast":"R\xF4tissage","mode.broil":"Gril","mode.pizza":"Pizza","mode.cookies":"Biscuits","mode.reheat":"R\xE9chauffage","mode.slow_cook":"Cuisson lente","mode.proof":"Lev\xE9e de la p\xE2te","mode.warm":"Maintien au chaud","mode.dehydrate":"D\xE9shydratation","mode.bottom_bake":"Cuisson par le dessous","mode.gentle_broil":"Friture \xE0 air chaud plus croustillante","mode.bottom_broil":"Gril par le dessous","mode.outer_top_broil":"Gril ext\xE9rieur","mode.middle_top_broil":"Gril central sup\xE9rieur","mode.windy_broil":"Gril \xE0 convection","mode.toast":"Pain grill\xE9","mode.bagel":"Bagel","mode.keep_warm":"Maintien au chaud","mode.crispy_reheat":"R\xE9chauffage croustillant","level.low":"Faible","level.medium":"Moyen","level.high":"\xC9lev\xE9","convection.off":"D\xE9sactiv\xE9e","convection.on":"Activ\xE9e","convection.super":"Super","convection_summary.off":"Sans convection","convection_summary.on":"Convection","convection_summary.super":"Super convection","accessory.roasting_pan":"l\xE8chefrite","accessory.broil_rack":"grille \xE0 r\xF4tir dans la l\xE8chefrite","accessory.air_fry_basket":"panier \xE0 friture","accessory.pizza_pan":"plaque \xE0 pizza","accessory.wire_rack":"grille","accessory.pot":"cocotte ferm\xE9e","food.croissants":"des croissants","food.casserole":"un gratin","food.chicken":"un poulet entier","food.steak":"un steak","food.fries":"des frites","food.pizza":"une pizza","food.cookies":"des biscuits","food.plate":"une assiette de restes","food.dough":"un bol de p\xE2te","food.covered_dish":"un plat couvert","food.fruit":"des tranches de fruits","food.bread":"des tranches de pain","food.bagel":"des moiti\xE9s de bagel","food.pizza_slice":"une part de pizza","describe.sous_vide":"{product} clips\xE9 sur un r\xE9cipient d'eau.","describe.water":"L'eau est \xE0 {now}.","describe.water_target":"L'eau est \xE0 {now}, cible {target}.","describe.time_left":"Il reste {time}.","describe.time_paused":"En pause, il reste {time}.","describe.food_bag":"Un sachet d'aliments est dans l'eau.","describe.tipped":"L'appareil s'est renvers\xE9.","describe.low_water":"Le niveau d'eau est trop bas.","describe.oven_brushed_stainless":"{product} en inox bross\xE9.","describe.oven_black_stainless":"{product} en inox noir.","describe.mode":"{mode}.","describe.oven_temperature":"{temp} \xE0 l'int\xE9rieur.","describe.rack":"Niveau {n}\xA0: {accessory}.","describe.rack_food":"Niveau {n}\xA0: {accessory} avec {food}.","describe.door_open":"La porte est ouverte.","describe.fan_on":"Le ventilateur tourne.","describe.fan_super":"Le ventilateur tourne \xE0 vitesse \xE9lev\xE9e.","announce.ready":"{name} est pr\xEAt pour les aliments.","announce.preheated":"{name} est pr\xE9chauff\xE9, la cuisson commence.","announce.done":"{name} a termin\xE9.","announce.door_open":"{name}\xA0: la porte est ouverte.","announce.press_start":"{name}\xA0: appuyez sur Start sur l'appareil.","announce.error":"{name}\xA0: {error}.","announce.offline":"{name} est hors ligne.","presets.builtin":"Pr\xE9d\xE9finis","presets.custom":"Enregistr\xE9s","presets.none":"Aucun pr\xE9r\xE9glage enregistr\xE9 pour l'instant. Un administrateur peut en enregistrer.","presets.none_admin":"Aucun pr\xE9r\xE9glage enregistr\xE9 pour l'instant. Configurez une cuisson, puis enregistrez-la ici.","presets.disabled_cooking":"Les pr\xE9r\xE9glages s'appliquent \xE0 la prochaine cuisson. Arr\xEAtez ou terminez d'abord celle en cours.","presets.applied":"R\xE9glages repris de {name}. Appuyez sur D\xE9marrer le moment venu.","presets.saved":"{name} enregistr\xE9.","presets.renamed":"Renomm\xE9 en {name}.","presets.updated":"{name} mis \xE0 jour avec les r\xE9glages actuels.","presets.deleted":"{name} supprim\xE9.","presets.save_current":"Enregistrer les r\xE9glages actuels comme pr\xE9r\xE9glage","presets.save_hint":"Les pr\xE9r\xE9glages enregistr\xE9s sont partag\xE9s avec tous les utilisateurs de Home Assistant.","presets.name":"Nom du pr\xE9r\xE9glage","presets.save":"Enregistrer","presets.cancel":"Annuler","presets.update":"Mettre \xE0 jour","presets.delete":"Supprimer","presets.rename_named":"Renommer {name}","presets.update_named":"Mettre \xE0 jour {name} avec les r\xE9glages actuels","presets.delete_named":"Supprimer {name}","presets.delete_confirm":"Supprimer {name} pour tout le monde\xA0?","presets.update_confirm":"Remplacer les r\xE9glages de {name} par les r\xE9glages actuels\xA0?","presets.frozen":"Surgel\xE9","presets.note.raw_safe_fish":"Utilisez un poisson pouvant \xEAtre consomm\xE9 cru.","presets.disclaimer":"Les pr\xE9r\xE9glages sont un point de d\xE9part. Suivez un guide de cuisson fiable et v\xE9rifiez que les aliments sont cuits sans risque.","presets.error.cook_running":"Arr\xEAtez d'abord la cuisson\xA0: les pr\xE9r\xE9glages s'appliquent \xE0 la suivante.","presets.error.unknown_appliance":"Cet appareil ne figure plus dans le panneau.","presets.error.unknown_preset":"Ce pr\xE9r\xE9glage n'existe plus.","presets.error.invalid_preset":"Ce pr\xE9r\xE9glage ne convient pas \xE0 cet appareil.","presets.error.too_many_presets":"Vous pouvez enregistrer 50 pr\xE9r\xE9glages au maximum. Supprimez-en un d'abord.","presets.error.unavailable":"L'appareil n'est pas disponible pour le moment.","presets.error.unauthorized":"Seuls les administrateurs peuvent modifier les pr\xE9r\xE9glages enregistr\xE9s.","preset.steak_rare":"Steak, saignant","preset.steak_medium_rare":"Steak, mi-saignant","preset.steak_medium":"Steak, \xE0 point","preset.steak_well_done":"Steak, bien cuit","preset.beef_roast":"R\xF4ti de b\u0153uf","preset.short_ribs":"Plat de c\xF4tes","preset.pork_chop":"C\xF4te de porc","preset.pulled_pork":"\xC9paule de porc effiloch\xE9e","preset.chicken_breast":"Blanc de poulet","preset.chicken_thighs":"Hauts de cuisse de poulet","preset.salmon":"Saumon","preset.white_fish":"Poisson blanc","preset.shrimp":"Crevettes","preset.soft_eggs":"\u0152ufs mollets","preset.vegetables":"L\xE9gumes","preset.frozen_fries":"Frites surgel\xE9es","preset.chicken_wings":"Ailes de poulet","preset.frozen_pizza":"Pizza surgel\xE9e","preset.fresh_pizza":"Pizza fra\xEEche","preset.roast_vegetables":"L\xE9gumes r\xF4tis","preset.roast_chicken":"Poulet r\xF4ti","preset.cookies":"Biscuits","preset.cake":"G\xE2teau","preset.leftovers":"Restes","preset.salmon_fillets":"Filets de saumon","preset.dried_fruit":"Fruits s\xE9ch\xE9s","preset.bread_dough":"P\xE2te \xE0 pain","preset.pot_roast":"B\u0153uf brais\xE9","chart.loading":"Chargement des temp\xE9ratures de la cuisson\u2026","chart.failed":"Impossible de lire l'historique des temp\xE9ratures. Nouvel essai dans une minute.","chart.none":"Aucune cuisson ces derniers jours. Le graphique montre la cuisson en cours, ou la derni\xE8re.","chart.summary_now":"Actuellement {now}.","chart.summary_now_target":"Actuellement {now}, cible {target}.","chart.summary_last":"Elle s'est termin\xE9e \xE0 {now}.","chart.summary_last_target":"Elle s'est termin\xE9e \xE0 {now}, cible {target}.","chart.last_cook":"Derni\xE8re cuisson, de {start} \xE0 {end}.","chart.at_temperature_since":"\xC0 temp\xE9rature depuis {time}.","chart.sensor_summary":"Le four maintient son capteur \xE0 {temp}.","chart.sensor_caption":"La ligne en pointill\xE9s montre o\xF9 le four maintient son propre capteur\xA0: volontairement sous la consigne, l'\xE9cart n'est donc pas une anomalie.","chart.last_day":"Affichage du dernier jour.","chart.temperature":"Temp\xE9rature","chart.target":"Cible","chart.sensor_target":"Cible du capteur","chart.time":"Heure","chart.show_table":"Afficher sous forme de tableau","chart.hide_table":"Masquer le tableau","chart.table_caption":"Temp\xE9ratures pendant la cuisson"};var Wo={"panel.title":"Breville+","panel.menu":"Apri la barra laterale","panel.back":"Indietro","overview.no_area":"Nessuna area","overview.loading":"Caricamento degli elettrodomestici\u2026","overview.error_title":"Impossibile caricare gli elettrodomestici","overview.retry":"Riprova","overview.empty_title":"Ancora nessun elettrodomestico","overview.empty_text":"Gli elettrodomestici compaiono qui quando l'integrazione Breville+ Cooking li aggiunge. Aggiungi un account o attiva il pannello della barra laterale nelle sue opzioni.","overview.empty_text_user":"Gli elettrodomestici compaiono qui quando un amministratore li aggiunge all'integrazione Breville+ Cooking.","overview.empty_link":"Apri le impostazioni di Breville+ Cooking","overview.not_found_title":"Elettrodomestico non trovato","overview.not_found_text":"Questo elettrodomestico non \xE8 pi\xF9 nell'integrazione Breville+ Cooking, oppure il link \xE8 errato.","overview.back":"Torna a tutti gli elettrodomestici","card.open_hint":"Mostra tutti i comandi","status.offline":"Offline","status.error":"Errore","status.updating":"Aggiornamento","status.door_open":"Sportello aperto","status.press_start_oven":"Premi Start sul forno","status.press_button_joule":"Premi il pulsante sul Joule","status.preheating":"Preriscaldamento","status.preheating_pct":"Preriscaldamento {n}%","status.ready":"Pronto per il cibo","status.cooking":"In cottura","status.done":"Terminato","status.keeping_warm":"Mantenimento in caldo","status.idle":"Inattivo","display.ready":"Pronto","display.end":"Fine","display.press_start":"Premi Start","display.error":"Errore","display.off":"Spento","info.water":"Acqua","info.now_of_target":"{now} di {target}","info.time_left":"Tempo rimanente","info.time":"Tempo","info.ends":"termina alle {time}","info.paused":"in pausa","info.cook_time":"Tempo di cottura","info.next":"Prossimo passo","info.add_food":"Aggiungi il cibo, poi premi Continua","info.remove_food":"Estrai il cibo","info.oven_finished":"Estrai il cibo, poi premi Concludi","info.next_cook":"Prossima cottura","info.problem":"Problema","info.mode":"Modalit\xE0","info.oven":"Forno","info.rack":"Griglia","info.rack_value":"Posizione {n} \xB7 {accessory}","section.cook":"Cottura","section.next_cook":"Prossima cottura","section.this_cook":"Questa cottura","section.presets":"Preimpostazioni","section.chart":"Temperatura","section.details":"Dettagli","control.cook":"Cottura","control.food_in":"Cibo inserito","control.food_out":"Cibo estratto","control.water_temperature":"Temperatura dell'acqua","control.oven_temperature":"Temperatura del forno","control.target":"Obiettivo","control.target_temperature":"Temperatura desiderata","control.temperature":"Temperatura","control.time_left":"Tempo rimanente","control.cook_time":"Tempo di cottura","control.auto_start_timer":"Avvia il timer automaticamente","control.mode":"Modalit\xE0","control.level_broil":"Livello del grill","control.level_slow_cook":"Livello di cottura lenta","control.convection":"Convezione","control.frozen":"Cibi surgelati","control.keep_warm":"Mantenimento in caldo","control.door":"Sportello","control.rack":"Griglia","control.model":"Modello","control.finish":"Finitura","control.firmware":"Firmware","control.error":"Errore","control.tested":"Controllo","action.start":"Avvia","action.stop":"Interrompi","action.finish":"Concludi","action.food_in":"Avvia il timer","action.food_out":"Concludi","confirm.start_sous_vide":"Avviare il {name} a {temp} per {time}?","confirm.start_sous_vide_hold":"Avviare il {name} a {temp} finch\xE9 non lo fermi?","confirm.start_oven":"Avviare il forno in modalit\xE0 {mode} per {time}?","confirm.stop":"Interrompere la cottura?","hint.start":"Avvia una cottura con le impostazioni qui sotto.","hint.finish":"La cottura \xE8 terminata. Premi Concludi per chiuderla.","hint.food_in":"Inserisci il cibo, poi avvia il timer.","hint.food_out":"Estrai il cibo per concludere.","hint.paused":"In pausa","hint.changes_cook":"Modifica la cottura in corso.","hint.changes_time_left":"Imposta il tempo rimanente della cottura in corso.","hint.auto_start_timer":"Avvia il timer appena l'acqua raggiunge la temperatura, senza aspettare il cibo.","hint.auto_start_timer_oven":"Avvia il timer appena il forno \xE8 preriscaldato, senza aspettare il cibo.","hint.sensor_target":"Mantiene il suo sensore a {temp}, sotto la temperatura impostata.","hint.frozen":"Cuoce un po' pi\xF9 a lungo per i cibi surgelati.","hint.keep_warm":"Mantiene caldo il cibo al termine della cottura.","hint.untested":"Nessuno ha ancora testato questo modello con Home Assistant.","reason.offline":"L'elettrodomestico \xE8 offline.","reason.unavailable":"Non disponibile al momento.","reason.untested":"Il controllo del {product} non \xE8 ancora stato testato, quindi Home Assistant si limita a monitorarlo.","reason.open_options":"Consenti il controllo nelle opzioni dell'integrazione","reason.oven_running":"Una cottura del forno in corso non si pu\xF2 modificare. Interrompila per cambiare le impostazioni.","value.until_stopped":"Fino all'arresto","value.open":"Aperto","value.closed":"Chiuso","value.no_error":"Nessuno","value.untested":"Non ancora testato","value.now":"Ora: {value}","full.appliance":"Elettrodomestico","full.failed":"Non ha funzionato.","full.preheat":"Preriscaldamento","full.preheat_value":"{n} per cento","ctl.saving":"Salvataggio\u2026","ctl.decrease":"Diminuisci","ctl.increase":"Aumenta","ctl.off":"Disattivato","ctl.custom":"Personalizzato","ctl.hours":"Ore","ctl.minutes":"Minuti","ctl.h":"h","ctl.min":"min","ctl.set":"Imposta","ctl.not_now":"Non ora","ctl.out_of_range":"Scegli tra {min} e {max}.","unit.minutes":"{n} min","unit.hours":"{n} h","unit.hours_minutes":"{h} h {m} min","unit.days":"{n} gg","unit.days_hours":"{d} gg {h} h","finish.white_polished":"Bianco con acciaio inox lucidato","finish.brushed_stainless":"Acciaio inox spazzolato","finish.black_stainless":"Acciaio inox nero","mode.bake":"Cottura al forno","mode.air_fry":"Frittura ad aria","mode.roast":"Arrosto","mode.broil":"Grill","mode.pizza":"Pizza","mode.cookies":"Biscotti","mode.reheat":"Riscaldamento","mode.slow_cook":"Cottura lenta","mode.proof":"Lievitazione","mode.warm":"Mantenimento in caldo","mode.dehydrate":"Essiccazione","mode.bottom_bake":"Cottura dal basso","mode.gentle_broil":"Frittura ad aria pi\xF9 croccante","mode.bottom_broil":"Grill inferiore","mode.outer_top_broil":"Grill esterno","mode.middle_top_broil":"Grill centrale superiore","mode.windy_broil":"Grill ventilato","mode.toast":"Toast","mode.bagel":"Bagel","mode.keep_warm":"Mantenimento in caldo","mode.crispy_reheat":"Riscaldamento croccante","level.low":"Basso","level.medium":"Medio","level.high":"Alto","convection.off":"Disattivata","convection.on":"Attivata","convection.super":"Super","convection_summary.off":"Senza convezione","convection_summary.on":"Convezione","convection_summary.super":"Super convezione","accessory.roasting_pan":"teglia per arrosti","accessory.broil_rack":"griglia per grill nella teglia per arrosti","accessory.air_fry_basket":"cestello per frittura ad aria","accessory.pizza_pan":"teglia per pizza","accessory.wire_rack":"griglia","accessory.pot":"pentola con coperchio","food.croissants":"cornetti","food.casserole":"uno sformato","food.chicken":"un pollo intero","food.steak":"una bistecca","food.fries":"patatine fritte","food.pizza":"una pizza","food.cookies":"biscotti","food.plate":"un piatto di avanzi","food.dough":"una ciotola di impasto","food.covered_dish":"un piatto coperto","food.fruit":"fette di frutta","food.bread":"fette di pane","food.bagel":"mezzi bagel","food.pizza_slice":"una fetta di pizza","describe.sous_vide":"{product} agganciato a un contenitore d'acqua.","describe.water":"Acqua a {now}.","describe.water_target":"Acqua a {now}, obiettivo {target}.","describe.time_left":"Tempo rimanente: {time}.","describe.time_paused":"In pausa. Tempo rimanente: {time}.","describe.food_bag":"C'\xE8 un sacchetto di cibo nell'acqua.","describe.tipped":"Si \xE8 ribaltato.","describe.low_water":"Il livello dell'acqua \xE8 troppo basso.","describe.oven_brushed_stainless":"{product} in acciaio inox spazzolato.","describe.oven_black_stainless":"{product} in acciaio inox nero.","describe.mode":"{mode}.","describe.oven_temperature":"Temperatura interna: {temp}.","describe.rack":"In posizione {n}: {accessory}.","describe.rack_food":"In posizione {n}: {accessory} con {food}.","describe.door_open":"Lo sportello \xE8 aperto.","describe.fan_on":"La ventola \xE8 accesa.","describe.fan_super":"La ventola \xE8 al massimo.","announce.ready":"{name}: puoi inserire il cibo.","announce.preheated":"{name} ha terminato il preriscaldamento ed \xE8 in cottura.","announce.done":"{name} ha terminato.","announce.door_open":"{name}: lo sportello \xE8 aperto.","announce.press_start":"{name}: premi Start sull'elettrodomestico.","announce.error":"{name}: {error}.","announce.offline":"{name} \xE8 offline.","presets.builtin":"Predefinite","presets.custom":"Salvate","presets.none":"Ancora nessuna preimpostazione salvata. Un amministratore pu\xF2 salvarne alcune.","presets.none_admin":"Ancora nessuna preimpostazione salvata. Configura una cottura, poi salvala qui.","presets.disabled_cooking":"Le preimpostazioni valgono per la prossima cottura. Prima interrompi o concludi quella in corso.","presets.applied":"Impostazioni caricate da {name}. Premi Avvia quando vuoi.","presets.saved":"Hai salvato {name}.","presets.renamed":"Nuovo nome: {name}.","presets.updated":"Hai aggiornato {name} con le impostazioni attuali.","presets.deleted":"Hai eliminato {name}.","presets.save_current":"Salva le impostazioni attuali come preimpostazione","presets.save_hint":"Le preimpostazioni salvate sono condivise con tutti gli utenti di Home Assistant.","presets.name":"Nome della preimpostazione","presets.save":"Salva","presets.cancel":"Annulla","presets.update":"Aggiorna","presets.delete":"Elimina","presets.rename_named":"Rinomina {name}","presets.update_named":"Aggiorna {name} con le impostazioni attuali","presets.delete_named":"Elimina {name}","presets.delete_confirm":"Eliminare {name} per tutti?","presets.update_confirm":"Sostituire le impostazioni di {name} con quelle attuali?","presets.frozen":"Surgelato","presets.note.raw_safe_fish":"Usa pesce adatto al consumo crudo.","presets.disclaimer":"Le preimpostazioni sono un punto di partenza. Segui una guida di cucina affidabile e verifica che il cibo sia cotto in modo sicuro.","presets.error.cook_running":"Prima interrompi la cottura: le preimpostazioni valgono per la successiva.","presets.error.unknown_appliance":"Questo elettrodomestico non \xE8 pi\xF9 nel pannello.","presets.error.unknown_preset":"Quella preimpostazione non esiste pi\xF9.","presets.error.invalid_preset":"Quella preimpostazione non \xE8 adatta a questo elettrodomestico.","presets.error.too_many_presets":"Si possono salvare al massimo 50 preimpostazioni. Prima eliminane una.","presets.error.unavailable":"L'elettrodomestico non \xE8 disponibile al momento.","presets.error.unauthorized":"Solo gli amministratori possono modificare le preimpostazioni salvate.","preset.steak_rare":"Bistecca, al sangue","preset.steak_medium_rare":"Bistecca, media al sangue","preset.steak_medium":"Bistecca, media","preset.steak_well_done":"Bistecca, ben cotta","preset.beef_roast":"Arrosto di manzo","preset.short_ribs":"Costine di manzo","preset.pork_chop":"Braciola di maiale","preset.pulled_pork":"Spalla di maiale sfilacciata","preset.chicken_breast":"Petto di pollo","preset.chicken_thighs":"Sovracosce di pollo","preset.salmon":"Salmone","preset.white_fish":"Pesce bianco","preset.shrimp":"Gamberi","preset.soft_eggs":"Uova alla coque","preset.vegetables":"Verdure","preset.frozen_fries":"Patatine fritte surgelate","preset.chicken_wings":"Alette di pollo","preset.frozen_pizza":"Pizza surgelata","preset.fresh_pizza":"Pizza fresca","preset.roast_vegetables":"Verdure arrosto","preset.roast_chicken":"Pollo arrosto","preset.cookies":"Biscotti","preset.cake":"Torta","preset.leftovers":"Avanzi","preset.salmon_fillets":"Filetti di salmone","preset.dried_fruit":"Frutta essiccata","preset.bread_dough":"Impasto per il pane","preset.pot_roast":"Brasato di manzo","chart.loading":"Caricamento delle temperature della cottura\u2026","chart.failed":"Impossibile leggere la cronologia delle temperature. Nuovo tentativo tra un minuto.","chart.none":"Nessuna cottura negli ultimi giorni. Il grafico mostra la cottura in corso o l'ultima.","chart.summary_now":"Attualmente {now}.","chart.summary_now_target":"Attualmente {now}, obiettivo {target}.","chart.summary_last":"\xC8 terminata a {now}.","chart.summary_last_target":"\xC8 terminata a {now}, obiettivo {target}.","chart.last_cook":"Ultima cottura, da {start} a {end}.","chart.at_temperature_since":"In temperatura da {time}.","chart.sensor_summary":"Il forno mantiene il suo sensore a {temp}.","chart.sensor_caption":"La linea tratteggiata indica la temperatura a cui il forno mantiene il proprio sensore: sotto quella impostata, per scelta progettuale, quindi la differenza non \xE8 un guasto.","chart.last_day":"Viene mostrato l'ultimo giorno.","chart.temperature":"Temperatura","chart.target":"Obiettivo","chart.sensor_target":"Obiettivo del sensore","chart.time":"Ora","chart.show_table":"Mostra come tabella","chart.hide_table":"Nascondi la tabella","chart.table_caption":"Temperature durante la cottura"};var qo={"panel.title":"Breville+","panel.menu":"Zijbalk openen","panel.back":"Terug","overview.no_area":"Geen ruimte","overview.loading":"Apparaten laden\u2026","overview.error_title":"Kan de apparaten niet laden","overview.retry":"Opnieuw proberen","overview.empty_title":"Nog geen apparaten","overview.empty_text":"Apparaten verschijnen hier zodra de integratie Breville+ Cooking ze heeft toegevoegd. Voeg een account toe, of zet het zijbalkpaneel aan in de opties van de integratie.","overview.empty_text_user":"Apparaten verschijnen hier zodra een beheerder ze aan de integratie Breville+ Cooking heeft toegevoegd.","overview.empty_link":"Instellingen van Breville+ Cooking openen","overview.not_found_title":"Apparaat niet gevonden","overview.not_found_text":"Dit apparaat zit niet meer in de integratie Breville+ Cooking, of de link klopt niet.","overview.back":"Terug naar alle apparaten","card.open_hint":"Alle bediening tonen","status.offline":"Offline","status.error":"Fout","status.updating":"Bijwerken","status.door_open":"Deur open","status.press_start_oven":"Druk op Start op de oven","status.press_button_joule":"Druk op de knop van de Joule","status.preheating":"Voorverwarmen","status.preheating_pct":"Voorverwarmen {n}%","status.ready":"Klaar om eten toe te voegen","status.cooking":"Koken","status.done":"Voltooid","status.keeping_warm":"Warmhouden","status.idle":"Inactief","display.ready":"Gereed","display.end":"Klaar","display.press_start":"Druk op Start","display.error":"Fout","display.off":"Uit","info.water":"Water","info.now_of_target":"{now} van {target}","info.time_left":"Resterende tijd","info.time":"Tijd","info.ends":"klaar om {time}","info.paused":"gepauzeerd","info.cook_time":"Kooktijd","info.next":"Volgende stap","info.add_food":"Voeg het eten toe en druk dan op Doorgaan","info.remove_food":"Haal het eten eruit","info.oven_finished":"Haal het eten eruit en druk dan op Afronden","info.next_cook":"Volgend kookproces","info.problem":"Probleem","info.mode":"Modus","info.oven":"Oven","info.rack":"Rooster","info.rack_value":"Positie {n} \xB7 {accessory}","section.cook":"Koken","section.next_cook":"Volgend kookproces","section.this_cook":"Huidig kookproces","section.presets":"Voorinstellingen","section.chart":"Temperatuur","section.details":"Details","control.cook":"Koken","control.food_in":"Eten zit erin","control.food_out":"Eten is eruit","control.water_temperature":"Watertemperatuur","control.oven_temperature":"Oventemperatuur","control.target":"Doel","control.target_temperature":"Doeltemperatuur","control.temperature":"Temperatuur","control.time_left":"Resterende tijd","control.cook_time":"Kooktijd","control.auto_start_timer":"Timer automatisch starten","control.mode":"Modus","control.level_broil":"Grillsterkte","control.level_slow_cook":"Stand voor langzaam garen","control.convection":"Convectie","control.frozen":"Diepvriesproducten","control.keep_warm":"Warmhouden","control.door":"Deur","control.rack":"Rooster","control.model":"Model","control.finish":"Afwerking","control.firmware":"Firmware","control.error":"Fout","control.tested":"Bediening","action.start":"Starten","action.stop":"Stoppen","action.finish":"Afronden","action.food_in":"Timer starten","action.food_out":"Afronden","confirm.start_sous_vide":"De {name} starten op {temp} voor {time}?","confirm.start_sous_vide_hold":"De {name} starten op {temp} tot je stopt?","confirm.start_oven":"De oven starten op {mode} voor {time}?","confirm.stop":"Kookproces stoppen?","hint.start":"Start een kookproces met de instellingen hieronder.","hint.finish":"Het kookproces is voorbij. Met Afronden sluit je het af.","hint.food_in":"Doe het eten erin en start dan de timer.","hint.food_out":"Haal het eten eruit om af te ronden.","hint.paused":"Gepauzeerd","hint.changes_cook":"Wijzigt het lopende kookproces.","hint.changes_time_left":"Stelt de resterende tijd van het lopende kookproces in.","hint.auto_start_timer":"Start de timer zodra het water op temperatuur is, zonder op het eten te wachten.","hint.auto_start_timer_oven":"Start de timer zodra de oven is voorverwarmd, zonder op het eten te wachten.","hint.sensor_target":"De oven houdt zijn sensor op {temp}, onder de ingestelde temperatuur.","hint.frozen":"Bereidt iets langer voor diepvriesproducten.","hint.keep_warm":"Houdt het eten warm als het kookproces klaar is.","hint.untested":"Niemand heeft dit model nog met Home Assistant getest.","reason.offline":"Het apparaat is offline.","reason.unavailable":"Nu niet beschikbaar.","reason.untested":"Bediening van de {product} is nog niet getest, dus Home Assistant houdt het apparaat alleen in de gaten.","reason.open_options":"Bediening toestaan in de opties van de integratie","reason.oven_running":"Een lopend kookproces in de oven kun je niet wijzigen. Stop het om de instellingen aan te passen.","value.until_stopped":"Tot je stopt","value.open":"Open","value.closed":"Gesloten","value.no_error":"Geen","value.untested":"Nog niet getest","value.now":"Nu: {value}","full.appliance":"Apparaat","full.failed":"Dat is niet gelukt.","full.preheat":"Voorverwarmen","full.preheat_value":"{n} procent","ctl.saving":"Opslaan\u2026","ctl.decrease":"Verlagen","ctl.increase":"Verhogen","ctl.off":"Uit","ctl.custom":"Aangepast","ctl.hours":"Uren","ctl.minutes":"Minuten","ctl.h":"u","ctl.min":"min","ctl.set":"Instellen","ctl.not_now":"Niet nu","ctl.out_of_range":"Kies tussen {min} en {max}.","unit.minutes":"{n} min","unit.hours":"{n} u","unit.hours_minutes":"{h} u {m} min","unit.days":"{n} d","unit.days_hours":"{d} d {h} u","finish.white_polished":"Wit met gepolijst roestvrij staal","finish.brushed_stainless":"Geborsteld roestvrij staal","finish.black_stainless":"Zwart roestvrij staal","mode.bake":"Bakken","mode.air_fry":"Airfryen","mode.roast":"Braden","mode.broil":"Grillen","mode.pizza":"Pizza","mode.cookies":"Koekjes","mode.reheat":"Opwarmen","mode.slow_cook":"Langzaam garen","mode.proof":"Rijzen","mode.warm":"Warmhouden","mode.dehydrate":"Drogen","mode.bottom_bake":"Onderkant bakken","mode.gentle_broil":"Krokanter airfryen","mode.bottom_broil":"Onderkant grillen","mode.outer_top_broil":"Buitenkant grillen","mode.middle_top_broil":"Midden-boven grillen","mode.windy_broil":"Convectie grillen","mode.toast":"Toast","mode.bagel":"Bagel","mode.keep_warm":"Warmhouden","mode.crispy_reheat":"Krokant opwarmen","level.low":"Laag","level.medium":"Gemiddeld","level.high":"Hoog","convection.off":"Uit","convection.on":"Aan","convection.super":"Super","convection_summary.off":"Geen convectie","convection_summary.on":"Convectie","convection_summary.super":"Superconvectie","accessory.roasting_pan":"braadslede","accessory.broil_rack":"grillrooster in de braadslede","accessory.air_fry_basket":"airfryermand","accessory.pizza_pan":"pizzaplaat","accessory.wire_rack":"ovenrooster","accessory.pot":"pan met deksel","food.croissants":"croissants","food.casserole":"een ovenschotel","food.chicken":"een hele kip","food.steak":"een biefstuk","food.fries":"friet","food.pizza":"een pizza","food.cookies":"koekjes","food.plate":"een bord restjes","food.dough":"een kom deeg","food.covered_dish":"een afgedekte schaal","food.fruit":"schijfjes fruit","food.bread":"sneetjes brood","food.bagel":"bagelhelften","food.pizza_slice":"een stuk pizza","describe.sous_vide":"{product} vastgeklemd in een bak met water.","describe.water":"Het water is {now}.","describe.water_target":"Het water is {now}, doel {target}.","describe.time_left":"Nog {time}.","describe.time_paused":"Gepauzeerd met nog {time} te gaan.","describe.food_bag":"Er zit een zak eten in het water.","describe.tipped":"Hij is omgevallen.","describe.low_water":"Het waterniveau is te laag.","describe.oven_brushed_stainless":"{product} in geborsteld roestvrij staal.","describe.oven_black_stainless":"{product} in zwart roestvrij staal.","describe.mode":"{mode}.","describe.oven_temperature":"In de oven is het {temp}.","describe.rack":"Rooster op positie {n}: een {accessory}.","describe.rack_food":"Rooster op positie {n}: een {accessory} met {food}.","describe.door_open":"De deur staat open.","describe.fan_on":"De ventilator staat aan.","describe.fan_super":"De ventilator staat op de hoogste stand.","announce.ready":"{name} is klaar om eten toe te voegen.","announce.preheated":"{name} is voorverwarmd en aan het koken.","announce.done":"{name} is klaar.","announce.door_open":"{name}: de deur staat open.","announce.press_start":"{name}: druk op Start op het apparaat.","announce.error":"{name}: {error}.","announce.offline":"{name} is offline.","presets.builtin":"Ingebouwd","presets.custom":"Opgeslagen","presets.none":"Nog geen opgeslagen voorinstellingen. Een beheerder kan er een paar opslaan.","presets.none_admin":"Nog geen opgeslagen voorinstellingen. Stel een kookproces in en sla het hier op.","presets.disabled_cooking":"Voorinstellingen vullen het volgende kookproces in. Stop of rond eerst het huidige af.","presets.applied":"Ingevuld met {name}. Druk op Starten als je klaar bent.","presets.saved":"{name} opgeslagen.","presets.renamed":"Hernoemd naar {name}.","presets.updated":"{name} bijgewerkt met de huidige instellingen.","presets.deleted":"{name} verwijderd.","presets.save_current":"Huidige instellingen opslaan als voorinstelling","presets.save_hint":"Opgeslagen voorinstellingen worden gedeeld met iedereen die Home Assistant gebruikt.","presets.name":"Naam van de voorinstelling","presets.save":"Opslaan","presets.cancel":"Annuleren","presets.update":"Bijwerken","presets.delete":"Verwijderen","presets.rename_named":"{name} hernoemen","presets.update_named":"{name} bijwerken met de huidige instellingen","presets.delete_named":"{name} verwijderen","presets.delete_confirm":"{name} voor iedereen verwijderen?","presets.update_confirm":"Instellingen van {name} vervangen door de huidige?","presets.frozen":"Diepvries","presets.note.raw_safe_fish":"Gebruik vis die geschikt is om rauw te eten.","presets.disclaimer":"Voorinstellingen zijn een startpunt. Volg een betrouwbare kookgids en controleer of het eten veilig gegaard is.","presets.error.cook_running":"Stop eerst het kookproces: voorinstellingen vullen het volgende in.","presets.error.unknown_appliance":"Dit apparaat staat niet meer in het paneel.","presets.error.unknown_preset":"Die voorinstelling is er niet meer.","presets.error.invalid_preset":"Die voorinstelling past niet bij dit apparaat.","presets.error.too_many_presets":"Er kunnen maximaal 50 voorinstellingen worden opgeslagen. Verwijder er eerst een.","presets.error.unavailable":"Het apparaat is nu niet beschikbaar.","presets.error.unauthorized":"Alleen beheerders kunnen opgeslagen voorinstellingen wijzigen.","preset.steak_rare":"Biefstuk, rood","preset.steak_medium_rare":"Biefstuk, ros\xE9","preset.steak_medium":"Biefstuk, medium","preset.steak_well_done":"Biefstuk, doorbakken","preset.beef_roast":"Rosbief","preset.short_ribs":"Klapstuk","preset.pork_chop":"Karbonade","preset.pulled_pork":"Getrokken varkensschouder","preset.chicken_breast":"Kipfilet","preset.chicken_thighs":"Kippendijen","preset.salmon":"Zalm","preset.white_fish":"Witvis","preset.shrimp":"Garnalen","preset.soft_eggs":"Zachte eieren","preset.vegetables":"Groenten","preset.frozen_fries":"Diepvriesfriet","preset.chicken_wings":"Kippenvleugels","preset.frozen_pizza":"Diepvriespizza","preset.fresh_pizza":"Verse pizza","preset.roast_vegetables":"Geroosterde groenten","preset.roast_chicken":"Gebraden kip","preset.cookies":"Koekjes","preset.cake":"Cake","preset.leftovers":"Restjes","preset.salmon_fillets":"Zalmfilets","preset.dried_fruit":"Gedroogd fruit","preset.bread_dough":"Brooddeeg","preset.pot_roast":"Stoofvlees","chart.loading":"Temperaturen van het kookproces laden\u2026","chart.failed":"Kan de temperatuurgeschiedenis niet lezen. Over een minuut wordt het opnieuw geprobeerd.","chart.none":"Geen kookproces in de afgelopen dagen. De grafiek toont het huidige kookproces, of het laatste.","chart.summary_now":"Nu {now}.","chart.summary_now_target":"Nu {now}, doel {target}.","chart.summary_last":"Het eindigde op {now}.","chart.summary_last_target":"Het eindigde op {now}, doel {target}.","chart.last_cook":"Laatste kookproces, {start} tot {end}.","chart.at_temperature_since":"Op temperatuur sinds {time}.","chart.sensor_summary":"De oven houdt zijn sensor op {temp}.","chart.sensor_caption":"De stippellijn toont op welke temperatuur de oven zijn eigen sensor houdt: bewust onder de ingestelde temperatuur, dus het verschil is geen storing.","chart.last_day":"Toont de afgelopen dag.","chart.temperature":"Temperatuur","chart.target":"Doel","chart.sensor_target":"Sensordoel","chart.time":"Tijd","chart.show_table":"Als tabel tonen","chart.hide_table":"Tabel verbergen","chart.table_caption":"Temperaturen tijdens het kookproces"};var Zo={"panel.title":"Breville+","panel.menu":"Otw\xF3rz pasek boczny","panel.back":"Wstecz","overview.no_area":"Bez obszaru","overview.loading":"Wczytywanie urz\u0105dze\u0144\u2026","overview.error_title":"Nie uda\u0142o si\u0119 wczyta\u0107 urz\u0105dze\u0144","overview.retry":"Spr\xF3buj ponownie","overview.empty_title":"Nie ma jeszcze urz\u0105dze\u0144","overview.empty_text":"Urz\u0105dzenia pojawi\u0105 si\u0119 tutaj, gdy doda je integracja Breville+ Cooking. Dodaj konto lub w\u0142\u0105cz w jej opcjach panel na pasku bocznym.","overview.empty_text_user":"Urz\u0105dzenia pojawi\u0105 si\u0119 tutaj, gdy administrator doda je do integracji Breville+ Cooking.","overview.empty_link":"Otw\xF3rz ustawienia Breville+ Cooking","overview.not_found_title":"Nie znaleziono urz\u0105dzenia","overview.not_found_text":"Tego urz\u0105dzenia nie ma ju\u017C w integracji Breville+ Cooking albo link jest nieprawid\u0142owy.","overview.back":"Wr\xF3\u0107 do wszystkich urz\u0105dze\u0144","card.open_hint":"Poka\u017C wszystkie opcje sterowania","status.offline":"Offline","status.error":"B\u0142\u0105d","status.updating":"Aktualizacja","status.door_open":"Drzwi otwarte","status.press_start_oven":"Naci\u015Bnij Start na piekarniku","status.press_button_joule":"Naci\u015Bnij przycisk na Joule","status.preheating":"Podgrzewanie wst\u0119pne","status.preheating_pct":"Podgrzewanie wst\u0119pne {n}%","status.ready":"Gotowe do w\u0142o\u017Cenia jedzenia","status.cooking":"Gotowanie","status.done":"Zako\u0144czono","status.keeping_warm":"Podtrzymywanie temperatury","status.idle":"Bezczynny","display.ready":"Gotowe","display.end":"Koniec","display.press_start":"Naci\u015Bnij Start","display.error":"B\u0142\u0105d","display.off":"Wy\u0142.","info.water":"Woda","info.now_of_target":"{now} z {target}","info.time_left":"Pozosta\u0142y czas","info.time":"Czas","info.ends":"koniec o {time}","info.paused":"wstrzymano","info.cook_time":"Czas gotowania","info.next":"Nast\u0119pny krok","info.add_food":"W\u0142\xF3\u017C jedzenie, a potem naci\u015Bnij Kontynuuj","info.remove_food":"Wyjmij jedzenie","info.oven_finished":"Wyjmij jedzenie, a potem naci\u015Bnij Zako\u0144cz","info.next_cook":"Nast\u0119pne gotowanie","info.problem":"Problem","info.mode":"Tryb","info.oven":"Piekarnik","info.rack":"Ruszt","info.rack_value":"Pozycja {n} \xB7 {accessory}","section.cook":"Gotowanie","section.next_cook":"Nast\u0119pne gotowanie","section.this_cook":"Bie\u017C\u0105ce gotowanie","section.presets":"Programy","section.chart":"Temperatura","section.details":"Szczeg\xF3\u0142y","control.cook":"Gotowanie","control.food_in":"Jedzenie w\u0142o\u017Cone","control.food_out":"Jedzenie wyj\u0119te","control.water_temperature":"Temperatura wody","control.oven_temperature":"Temperatura piekarnika","control.target":"Cel","control.target_temperature":"Temperatura docelowa","control.temperature":"Temperatura","control.time_left":"Pozosta\u0142y czas","control.cook_time":"Czas gotowania","control.auto_start_timer":"Automatyczne uruchamianie minutnika","control.mode":"Tryb","control.level_broil":"Poziom grilla","control.level_slow_cook":"Poziom wolnego gotowania","control.convection":"Termoobieg","control.frozen":"Mro\u017Conki","control.keep_warm":"Podtrzymywanie temperatury","control.door":"Drzwi","control.rack":"Ruszt","control.model":"Model","control.finish":"Wyko\u0144czenie","control.firmware":"Oprogramowanie uk\u0142adowe","control.error":"B\u0142\u0105d","control.tested":"Sterowanie","action.start":"Uruchom","action.stop":"Zatrzymaj","action.finish":"Zako\u0144cz","action.food_in":"Uruchom minutnik","action.food_out":"Zako\u0144cz","confirm.start_sous_vide":"Uruchomi\u0107 {name} w temperaturze {temp} na {time}?","confirm.start_sous_vide_hold":"Uruchomi\u0107 {name} w temperaturze {temp} do zatrzymania?","confirm.start_oven":"Uruchomi\u0107 piekarnik: {mode}, {time}?","confirm.stop":"Zatrzyma\u0107 gotowanie?","hint.start":"Rozpoczyna gotowanie z poni\u017Cszymi ustawieniami.","hint.finish":"Gotowanie dobieg\u0142o ko\u0144ca. Przycisk Zako\u0144cz je zamyka.","hint.food_in":"W\u0142\xF3\u017C jedzenie, a potem uruchom minutnik.","hint.food_out":"Wyjmij jedzenie, aby zako\u0144czy\u0107.","hint.paused":"Wstrzymano","hint.changes_cook":"Zmienia trwaj\u0105ce gotowanie.","hint.changes_time_left":"Ustawia pozosta\u0142y czas trwaj\u0105cego gotowania.","hint.auto_start_timer":"Uruchamia minutnik, gdy woda si\u0119 nagrzeje, bez czekania na w\u0142o\u017Cenie jedzenia.","hint.auto_start_timer_oven":"Uruchamia minutnik, gdy piekarnik si\u0119 nagrzeje, bez czekania na w\u0142o\u017Cenie jedzenia.","hint.sensor_target":"Piekarnik utrzymuje na czujniku {temp}, poni\u017Cej ustawionej temperatury.","hint.frozen":"Gotuje nieco d\u0142u\u017Cej w przypadku mro\u017Conek.","hint.keep_warm":"Utrzymuje jedzenie w cieple po zako\u0144czeniu gotowania.","hint.untested":"Nikt jeszcze nie przetestowa\u0142 tego modelu z Home Assistant.","reason.offline":"Urz\u0105dzenie jest offline.","reason.unavailable":"Obecnie niedost\u0119pne.","reason.untested":"Sterowanie urz\u0105dzeniem {product} nie zosta\u0142o jeszcze przetestowane, wi\u0119c Home Assistant tylko je monitoruje.","reason.open_options":"Zezw\xF3l na sterowanie w opcjach integracji","reason.oven_running":"Trwaj\u0105cego gotowania w piekarniku nie mo\u017Cna zmieni\u0107. Zatrzymaj je, aby zmieni\u0107 ustawienia.","value.until_stopped":"Do zatrzymania","value.open":"Otwarte","value.closed":"Zamkni\u0119te","value.no_error":"Brak","value.untested":"Jeszcze nie przetestowano","value.now":"Teraz: {value}","full.appliance":"Urz\u0105dzenie","full.failed":"Nie uda\u0142o si\u0119.","full.preheat":"Podgrzewanie wst\u0119pne","full.preheat_value":"{n} procent","ctl.saving":"Zapisywanie\u2026","ctl.decrease":"Zmniejsz","ctl.increase":"Zwi\u0119ksz","ctl.off":"Wy\u0142.","ctl.custom":"W\u0142asny","ctl.hours":"Godziny","ctl.minutes":"Minuty","ctl.h":"godz.","ctl.min":"min","ctl.set":"Ustaw","ctl.not_now":"Nie teraz","ctl.out_of_range":"Wybierz czas od {min} do {max}.","unit.minutes":"{n} min","unit.hours":"{n} godz.","unit.hours_minutes":"{h} godz. {m} min","unit.days":"{n} d","unit.days_hours":"{d} d {h} godz.","finish.white_polished":"Bia\u0142y z polerowan\u0105 stal\u0105 nierdzewn\u0105","finish.brushed_stainless":"Szczotkowana stal nierdzewna","finish.black_stainless":"Czarna stal nierdzewna","mode.bake":"Pieczenie","mode.air_fry":"Sma\u017Cenie bez t\u0142uszczu","mode.roast":"Opiekanie","mode.broil":"Grill","mode.pizza":"Pizza","mode.cookies":"Ciastka","mode.reheat":"Odgrzewanie","mode.slow_cook":"Wolne gotowanie","mode.proof":"Wyrastanie ciasta","mode.warm":"Podtrzymywanie temperatury","mode.dehydrate":"Suszenie","mode.bottom_bake":"Pieczenie od do\u0142u","mode.gentle_broil":"Chrupi\u0105ce sma\u017Cenie bez t\u0142uszczu","mode.bottom_broil":"Grill od do\u0142u","mode.outer_top_broil":"Grill zewn\u0119trzny","mode.middle_top_broil":"Grill \u015Brodkowy g\xF3rny","mode.windy_broil":"Grill z termoobiegiem","mode.toast":"Tost","mode.bagel":"Bajgiel","mode.keep_warm":"Podtrzymywanie temperatury","mode.crispy_reheat":"Chrupi\u0105ce odgrzewanie","level.low":"Niski","level.medium":"\u015Aredni","level.high":"Wysoki","convection.off":"Wy\u0142\u0105czony","convection.on":"W\u0142\u0105czony","convection.super":"Super","convection_summary.off":"Bez termoobiegu","convection_summary.on":"Termoobieg","convection_summary.super":"Termoobieg Super","accessory.roasting_pan":"brytfanna","accessory.broil_rack":"ruszt do grillowania w brytfannie","accessory.air_fry_basket":"kosz do sma\u017Cenia bez t\u0142uszczu","accessory.pizza_pan":"blacha do pizzy","accessory.wire_rack":"ruszt","accessory.pot":"garnek z pokrywk\u0105","food.croissants":"croissanty","food.casserole":"zapiekanka","food.chicken":"ca\u0142y kurczak","food.steak":"stek","food.fries":"frytki","food.pizza":"pizza","food.cookies":"ciastka","food.plate":"talerz z resztkami","food.dough":"miska z ciastem","food.covered_dish":"przykryte naczynie","food.fruit":"plasterki owoc\xF3w","food.bread":"kromki chleba","food.bagel":"po\u0142\xF3wki bajgla","food.pizza_slice":"kawa\u0142ek pizzy","describe.sous_vide":"{product} przypi\u0119ty do pojemnika z wod\u0105.","describe.water":"Woda: {now}.","describe.water_target":"Woda: {now}, cel: {target}.","describe.time_left":"Pozosta\u0142o: {time}.","describe.time_paused":"Wstrzymano, pozosta\u0142o: {time}.","describe.food_bag":"W wodzie jest woreczek z jedzeniem.","describe.tipped":"Urz\u0105dzenie si\u0119 przewr\xF3ci\u0142o.","describe.low_water":"Poziom wody jest zbyt niski.","describe.oven_brushed_stainless":"{product} ze szczotkowanej stali nierdzewnej.","describe.oven_black_stainless":"{product} z czarnej stali nierdzewnej.","describe.mode":"{mode}.","describe.oven_temperature":"Wewn\u0105trz {temp}.","describe.rack":"Ruszt w pozycji {n}: {accessory}.","describe.rack_food":"Ruszt w pozycji {n}: {accessory} i {food}.","describe.door_open":"Drzwi s\u0105 otwarte.","describe.fan_on":"Wentylator jest w\u0142\u0105czony.","describe.fan_super":"Wentylator pracuje na wysokich obrotach.","announce.ready":"{name}: gotowe do w\u0142o\u017Cenia jedzenia.","announce.preheated":"{name}: podgrzewanie wst\u0119pne zako\u0144czone, trwa gotowanie.","announce.done":"{name}: gotowanie zako\u0144czone.","announce.door_open":"{name}: drzwi s\u0105 otwarte.","announce.press_start":"{name}: naci\u015Bnij Start na urz\u0105dzeniu.","announce.error":"{name}: {error}.","announce.offline":"{name} jest offline.","presets.builtin":"Wbudowane","presets.custom":"Zapisane","presets.none":"Nie ma jeszcze zapisanych program\xF3w. Mo\u017Ce je doda\u0107 administrator.","presets.none_admin":"Nie ma jeszcze zapisanych program\xF3w. Ustaw gotowanie, a potem zapisz je tutaj.","presets.disabled_cooking":"Programy ustawiaj\u0105 nast\u0119pne gotowanie. Najpierw zatrzymaj lub zako\u0144cz bie\u017C\u0105ce.","presets.applied":"Wczytano ustawienia z programu \u201E{name}\u201D. Naci\u015Bnij Uruchom, gdy zechcesz zacz\u0105\u0107.","presets.saved":"Zapisano program \u201E{name}\u201D.","presets.renamed":"Zmieniono nazw\u0119 na \u201E{name}\u201D.","presets.updated":"Zaktualizowano program \u201E{name}\u201D bie\u017C\u0105cymi ustawieniami.","presets.deleted":"Usuni\u0119to program \u201E{name}\u201D.","presets.save_current":"Zapisz bie\u017C\u0105ce ustawienia jako program","presets.save_hint":"Zapisane programy s\u0105 dost\u0119pne dla ka\u017Cdego, kto korzysta z Home Assistant.","presets.name":"Nazwa programu","presets.save":"Zapisz","presets.cancel":"Anuluj","presets.update":"Aktualizuj","presets.delete":"Usu\u0144","presets.rename_named":"Zmie\u0144 nazw\u0119 programu \u201E{name}\u201D","presets.update_named":"Zaktualizuj program \u201E{name}\u201D bie\u017C\u0105cymi ustawieniami","presets.delete_named":"Usu\u0144 program \u201E{name}\u201D","presets.delete_confirm":"Usun\u0105\u0107 program \u201E{name}\u201D dla wszystkich?","presets.update_confirm":"Zast\u0105pi\u0107 ustawienia programu \u201E{name}\u201D bie\u017C\u0105cymi?","presets.frozen":"Mro\u017Conki","presets.note.raw_safe_fish":"U\u017Cyj ryby, kt\xF3r\u0105 mo\u017Cna je\u015B\u0107 na surowo.","presets.disclaimer":"Programy to punkt wyj\u015Bcia. Kieruj si\u0119 sprawdzonym poradnikiem kulinarnym i upewnij si\u0119, \u017Ce jedzenie jest bezpiecznie przyrz\u0105dzone.","presets.error.cook_running":"Najpierw zatrzymaj gotowanie: programy ustawiaj\u0105 nast\u0119pne.","presets.error.unknown_appliance":"Tego urz\u0105dzenia nie ma ju\u017C w panelu.","presets.error.unknown_preset":"Tego programu ju\u017C nie ma.","presets.error.invalid_preset":"Ten program nie pasuje do tego urz\u0105dzenia.","presets.error.too_many_presets":"Mo\u017Cna zapisa\u0107 najwy\u017Cej 50 program\xF3w. Najpierw usu\u0144 kt\xF3ry\u015B z nich.","presets.error.unavailable":"Urz\u0105dzenie jest obecnie niedost\u0119pne.","presets.error.unauthorized":"Tylko administratorzy mog\u0105 zmienia\u0107 zapisane programy.","preset.steak_rare":"Stek, krwisty","preset.steak_medium_rare":"Stek, \u015Brednio krwisty","preset.steak_medium":"Stek, \u015Brednio wysma\u017Cony","preset.steak_well_done":"Stek, dobrze wysma\u017Cony","preset.beef_roast":"Piecze\u0144 wo\u0142owa","preset.short_ribs":"\u017Beberka wo\u0142owe","preset.pork_chop":"Kotlet wieprzowy","preset.pulled_pork":"Szarpana \u0142opatka wieprzowa","preset.chicken_breast":"Pier\u015B z kurczaka","preset.chicken_thighs":"Uda z kurczaka","preset.salmon":"\u0141oso\u015B","preset.white_fish":"Bia\u0142a ryba","preset.shrimp":"Krewetki","preset.soft_eggs":"Jajka na mi\u0119kko","preset.vegetables":"Warzywa","preset.frozen_fries":"Mro\u017Cone frytki","preset.chicken_wings":"Skrzyde\u0142ka z kurczaka","preset.frozen_pizza":"Mro\u017Cona pizza","preset.fresh_pizza":"\u015Awie\u017Ca pizza","preset.roast_vegetables":"Pieczone warzywa","preset.roast_chicken":"Pieczony kurczak","preset.cookies":"Ciastka","preset.cake":"Ciasto","preset.leftovers":"Resztki","preset.salmon_fillets":"Filety z \u0142ososia","preset.dried_fruit":"Suszone owoce","preset.bread_dough":"Ciasto na chleb","preset.pot_roast":"Duszona wo\u0142owina","chart.loading":"Wczytywanie temperatur gotowania\u2026","chart.failed":"Nie uda\u0142o si\u0119 odczyta\u0107 historii temperatury. Ponowna pr\xF3ba za minut\u0119.","chart.none":"Brak gotowania w ostatnich dniach. Wykres pokazuje bie\u017C\u0105ce lub ostatnie gotowanie.","chart.summary_now":"Teraz: {now}.","chart.summary_now_target":"Teraz: {now}, cel: {target}.","chart.summary_last":"Temperatura ko\u0144cowa: {now}.","chart.summary_last_target":"Temperatura ko\u0144cowa: {now}, cel: {target}.","chart.last_cook":"Ostatnie gotowanie: od {start} do {end}.","chart.at_temperature_since":"Temperatura docelowa utrzymywana od {time}.","chart.sensor_summary":"Piekarnik utrzymuje na czujniku {temp}.","chart.sensor_caption":"Linia przerywana pokazuje temperatur\u0119, kt\xF3r\u0105 piekarnik utrzymuje na w\u0142asnym czujniku: celowo poni\u017Cej ustawionej temperatury, wi\u0119c ta r\xF3\u017Cnica nie oznacza usterki.","chart.last_day":"Pokazano ostatni\u0105 dob\u0119.","chart.temperature":"Temperatura","chart.target":"Cel","chart.sensor_target":"Cel czujnika","chart.time":"Czas","chart.show_table":"Poka\u017C jako tabel\u0119","chart.hide_table":"Ukryj tabel\u0119","chart.table_caption":"Temperatury podczas gotowania"};var Qo={"panel.title":"Breville+","panel.menu":"\xD6ppna sidof\xE4ltet","panel.back":"Tillbaka","overview.no_area":"Inget omr\xE5de","overview.loading":"L\xE4ser in apparater\u2026","overview.error_title":"Det gick inte att l\xE4sa in apparaterna","overview.retry":"F\xF6rs\xF6k igen","overview.empty_title":"Inga apparater \xE4n","overview.empty_text":"Apparaterna visas h\xE4r n\xE4r integrationen Breville+ Cooking har lagt till dem. L\xE4gg till ett konto, eller sl\xE5 p\xE5 sidof\xE4ltspanelen i integrationens alternativ.","overview.empty_text_user":"Apparaterna visas h\xE4r n\xE4r en administrat\xF6r har lagt till dem i integrationen Breville+ Cooking.","overview.empty_link":"\xD6ppna inst\xE4llningarna f\xF6r Breville+ Cooking","overview.not_found_title":"Apparaten hittades inte","overview.not_found_text":"Den h\xE4r apparaten finns inte l\xE4ngre i integrationen Breville+ Cooking, eller s\xE5 \xE4r l\xE4nken fel.","overview.back":"Tillbaka till alla apparater","card.open_hint":"Visa alla reglage","status.offline":"Offline","status.error":"Fel","status.updating":"Uppdaterar","status.door_open":"Luckan \xF6ppen","status.press_start_oven":"Tryck p\xE5 Start p\xE5 ugnen","status.press_button_joule":"Tryck p\xE5 knappen p\xE5 Joule","status.preheating":"F\xF6rv\xE4rmning","status.preheating_pct":"F\xF6rv\xE4rmning {n} %","status.ready":"Redo f\xF6r maten","status.cooking":"Tillagning","status.done":"Klar","status.keeping_warm":"Varmh\xE5llning","status.idle":"Inaktiv","display.ready":"Redo","display.end":"Klar","display.press_start":"Tryck p\xE5 Start","display.error":"Fel","display.off":"Av","info.water":"Vatten","info.now_of_target":"{now} av {target}","info.time_left":"\xC5terst\xE5ende tid","info.time":"Tid","info.ends":"klar kl. {time}","info.paused":"pausad","info.cook_time":"Tillagningstid","info.next":"N\xE4sta steg","info.add_food":"L\xE4gg i maten och tryck sedan p\xE5 Forts\xE4tt","info.remove_food":"Ta ut maten","info.oven_finished":"Ta ut maten och tryck sedan p\xE5 Avsluta","info.next_cook":"N\xE4sta tillagning","info.problem":"Problem","info.mode":"L\xE4ge","info.oven":"Ugn","info.rack":"Galler","info.rack_value":"Niv\xE5 {n} \xB7 {accessory}","section.cook":"Tillagning","section.next_cook":"N\xE4sta tillagning","section.this_cook":"P\xE5g\xE5ende tillagning","section.presets":"F\xF6rinst\xE4llningar","section.chart":"Temperatur","section.details":"Detaljer","control.cook":"Tillagning","control.food_in":"Maten \xE4r ilagd","control.food_out":"Maten \xE4r uttagen","control.water_temperature":"Vattentemperatur","control.oven_temperature":"Ugnstemperatur","control.target":"M\xE5l","control.target_temperature":"M\xE5ltemperatur","control.temperature":"Temperatur","control.time_left":"\xC5terst\xE5ende tid","control.cook_time":"Tillagningstid","control.auto_start_timer":"Starta timer automatiskt","control.mode":"L\xE4ge","control.level_broil":"Grillstyrka","control.level_slow_cook":"Niv\xE5 f\xF6r l\xE5ngkok","control.convection":"Konvektion","control.frozen":"Fryst mat","control.keep_warm":"Varmh\xE5llning","control.door":"Lucka","control.rack":"Galler","control.model":"Modell","control.finish":"Utf\xF6rande","control.firmware":"Firmware","control.error":"Fel","control.tested":"Styrning","action.start":"Starta","action.stop":"Stoppa","action.finish":"Avsluta","action.food_in":"Starta timern","action.food_out":"Avsluta","confirm.start_sous_vide":"Starta {name} p\xE5 {temp} i {time}?","confirm.start_sous_vide_hold":"Starta {name} p\xE5 {temp} tills du stoppar?","confirm.start_oven":"Starta ugnen p\xE5 {mode} i {time}?","confirm.stop":"Stoppa tillagningen?","hint.start":"Startar en tillagning med inst\xE4llningarna nedan.","hint.finish":"Tillagningen \xE4r klar. Med Avsluta st\xE4nger du den.","hint.food_in":"L\xE4gg i maten och starta sedan timern.","hint.food_out":"Ta ut maten f\xF6r att avsluta.","hint.paused":"Pausad","hint.changes_cook":"\xC4ndrar den p\xE5g\xE5ende tillagningen.","hint.changes_time_left":"St\xE4ller in \xE5terst\xE5ende tid f\xF6r den p\xE5g\xE5ende tillagningen.","hint.auto_start_timer":"Startar timern n\xE4r vattnet \xE4r uppe i temperatur, utan att v\xE4nta p\xE5 maten.","hint.auto_start_timer_oven":"Startar timern n\xE4r ugnen \xE4r f\xF6rv\xE4rmd, utan att v\xE4nta p\xE5 maten.","hint.sensor_target":"Ugnen h\xE5ller sin sensor p\xE5 {temp}, under den inst\xE4llda temperaturen.","hint.frozen":"Tillagar lite l\xE4ngre f\xF6r fryst mat.","hint.keep_warm":"H\xE5ller maten varm n\xE4r tillagningen \xE4r klar.","hint.untested":"Ingen har testat den h\xE4r modellen med Home Assistant \xE4n.","reason.offline":"Apparaten \xE4r offline.","reason.unavailable":"Inte tillg\xE4nglig just nu.","reason.untested":"Styrning av {product} har inte testats \xE4n, s\xE5 Home Assistant \xF6vervakar den bara.","reason.open_options":"Till\xE5t styrning i integrationens alternativ","reason.oven_running":"En p\xE5g\xE5ende tillagning i ugnen kan inte \xE4ndras. Stoppa den f\xF6r att \xE4ndra inst\xE4llningarna.","value.until_stopped":"Tills du stoppar","value.open":"\xD6ppen","value.closed":"St\xE4ngd","value.no_error":"Inget","value.untested":"Inte testad \xE4n","value.now":"Nu: {value}","full.appliance":"Apparat","full.failed":"Det gick inte.","full.preheat":"F\xF6rv\xE4rmning","full.preheat_value":"{n} procent","ctl.saving":"Sparar\u2026","ctl.decrease":"Minska","ctl.increase":"\xD6ka","ctl.off":"Av","ctl.custom":"Anpassad","ctl.hours":"Timmar","ctl.minutes":"Minuter","ctl.h":"tim","ctl.min":"min","ctl.set":"St\xE4ll in","ctl.not_now":"Inte nu","ctl.out_of_range":"V\xE4lj mellan {min} och {max}.","unit.minutes":"{n} min","unit.hours":"{n} tim","unit.hours_minutes":"{h} tim {m} min","unit.days":"{n} d","unit.days_hours":"{d} d {h} tim","finish.white_polished":"Vit med polerat rostfritt st\xE5l","finish.brushed_stainless":"Borstat rostfritt st\xE5l","finish.black_stainless":"Svart rostfritt st\xE5l","mode.bake":"Gr\xE4dda","mode.air_fry":"Varmluftsfritering","mode.roast":"Ugnsstekning","mode.broil":"Grilla","mode.pizza":"Pizza","mode.cookies":"Kakor","mode.reheat":"\xC5teruppv\xE4rmning","mode.slow_cook":"L\xE5ngkok","mode.proof":"J\xE4sning","mode.warm":"Varmh\xE5llning","mode.dehydrate":"Torkning","mode.bottom_bake":"Underv\xE4rme","mode.gentle_broil":"Krispigare airfry","mode.bottom_broil":"Grill underifr\xE5n","mode.outer_top_broil":"Yttre grill","mode.middle_top_broil":"\xD6vre grill i mitten","mode.windy_broil":"Konvektionsgrill","mode.toast":"Toast","mode.bagel":"Bagel","mode.keep_warm":"Varmh\xE5llning","mode.crispy_reheat":"Krispig uppv\xE4rmning","level.low":"L\xE5g","level.medium":"Medel","level.high":"H\xF6g","convection.off":"Av","convection.on":"P\xE5","convection.super":"Super","convection_summary.off":"Ingen konvektion","convection_summary.on":"Konvektion","convection_summary.super":"Superkonvektion","accessory.roasting_pan":"l\xE5ngpanna","accessory.broil_rack":"grillgaller i l\xE5ngpannan","accessory.air_fry_basket":"airfryerkorg","accessory.pizza_pan":"pizzapl\xE5t","accessory.wire_rack":"ugnsgaller","accessory.pot":"gryta med lock","food.croissants":"croissanter","food.casserole":"en grat\xE4ng","food.chicken":"en hel kyckling","food.steak":"en biff","food.fries":"pommes frites","food.pizza":"en pizza","food.cookies":"sm\xE5kakor","food.plate":"en tallrik rester","food.dough":"en sk\xE5l deg","food.covered_dish":"en \xF6vert\xE4ckt form","food.fruit":"fruktskivor","food.bread":"br\xF6dskivor","food.bagel":"bagelhalvor","food.pizza_slice":"en pizzabit","describe.sous_vide":"{product} fastkl\xE4md i en beh\xE5llare med vatten.","describe.water":"Vattnet h\xE5ller {now}.","describe.water_target":"Vattnet h\xE5ller {now}, m\xE5l {target}.","describe.time_left":"{time} kvar.","describe.time_paused":"Pausad med {time} kvar.","describe.food_bag":"En p\xE5se med mat ligger i vattnet.","describe.tipped":"Den har v\xE4lt.","describe.low_water":"Vattenniv\xE5n \xE4r f\xF6r l\xE5g.","describe.oven_brushed_stainless":"{product} i borstat rostfritt st\xE5l.","describe.oven_black_stainless":"{product} i svart rostfritt st\xE5l.","describe.mode":"{mode}.","describe.oven_temperature":"I ugnen \xE4r det {temp}.","describe.rack":"Gallret p\xE5 niv\xE5 {n}: {accessory}.","describe.rack_food":"Gallret p\xE5 niv\xE5 {n}: {accessory} med {food}.","describe.door_open":"Luckan \xE4r \xF6ppen.","describe.fan_on":"Fl\xE4kten \xE4r p\xE5.","describe.fan_super":"Fl\xE4kten g\xE5r f\xF6r fullt.","announce.ready":"{name} \xE4r redo f\xF6r maten.","announce.preheated":"{name} \xE4r f\xF6rv\xE4rmd och tillagningen p\xE5g\xE5r.","announce.done":"{name} \xE4r klar.","announce.door_open":"{name}: luckan \xE4r \xF6ppen.","announce.press_start":"{name}: tryck p\xE5 Start p\xE5 apparaten.","announce.error":"{name}: {error}.","announce.offline":"{name} \xE4r offline.","presets.builtin":"Inbyggda","presets.custom":"Sparade","presets.none":"Inga sparade f\xF6rinst\xE4llningar \xE4n. En administrat\xF6r kan spara n\xE5gra.","presets.none_admin":"Inga sparade f\xF6rinst\xE4llningar \xE4n. St\xE4ll in en tillagning och spara den h\xE4r.","presets.disabled_cooking":"F\xF6rinst\xE4llningar fyller i n\xE4sta tillagning. Stoppa eller avsluta den h\xE4r f\xF6rst.","presets.applied":"Ifyllt fr\xE5n {name}. Tryck p\xE5 Starta n\xE4r du \xE4r redo.","presets.saved":"{name} har sparats.","presets.renamed":"Namnet har \xE4ndrats till {name}.","presets.updated":"{name} har uppdaterats med de aktuella inst\xE4llningarna.","presets.deleted":"{name} har tagits bort.","presets.save_current":"Spara de aktuella inst\xE4llningarna som f\xF6rinst\xE4llning","presets.save_hint":"Sparade f\xF6rinst\xE4llningar delas med alla som anv\xE4nder Home Assistant.","presets.name":"Namn p\xE5 f\xF6rinst\xE4llningen","presets.save":"Spara","presets.cancel":"Avbryt","presets.update":"Uppdatera","presets.delete":"Ta bort","presets.rename_named":"Byt namn p\xE5 {name}","presets.update_named":"Uppdatera {name} med de aktuella inst\xE4llningarna","presets.delete_named":"Ta bort {name}","presets.delete_confirm":"Ta bort {name} f\xF6r alla?","presets.update_confirm":"Ers\xE4tt inst\xE4llningarna f\xF6r {name} med de aktuella?","presets.frozen":"Fryst","presets.note.raw_safe_fish":"Anv\xE4nd fisk som g\xE5r att \xE4ta r\xE5.","presets.disclaimer":"F\xF6rinst\xE4llningar \xE4r en utg\xE5ngspunkt. F\xF6lj en p\xE5litlig tillagningsguide och kontrollera att maten \xE4r s\xE4kert tillagad.","presets.error.cook_running":"Stoppa tillagningen f\xF6rst: f\xF6rinst\xE4llningar fyller i n\xE4sta.","presets.error.unknown_appliance":"Den h\xE4r apparaten finns inte l\xE4ngre i panelen.","presets.error.unknown_preset":"Den f\xF6rinst\xE4llningen finns inte l\xE4ngre.","presets.error.invalid_preset":"Den f\xF6rinst\xE4llningen passar inte den h\xE4r apparaten.","presets.error.too_many_presets":"Det f\xE5r finnas h\xF6gst 50 sparade f\xF6rinst\xE4llningar. Ta bort en f\xF6rst.","presets.error.unavailable":"Apparaten \xE4r inte tillg\xE4nglig just nu.","presets.error.unauthorized":"Endast administrat\xF6rer kan \xE4ndra sparade f\xF6rinst\xE4llningar.","preset.steak_rare":"Biff, blodig","preset.steak_medium_rare":"Biff, rosa","preset.steak_medium":"Biff, medium","preset.steak_well_done":"Biff, genomstekt","preset.beef_roast":"Rostbiff","preset.short_ribs":"N\xF6trevben","preset.pork_chop":"Fl\xE4skkotlett","preset.pulled_pork":"Rivet fl\xE4sk","preset.chicken_breast":"Kycklingfil\xE9","preset.chicken_thighs":"Kycklingl\xE5r","preset.salmon":"Lax","preset.white_fish":"Vit fisk","preset.shrimp":"R\xE4kor","preset.soft_eggs":"L\xF6skokta \xE4gg","preset.vegetables":"Gr\xF6nsaker","preset.frozen_fries":"Frysta pommes frites","preset.chicken_wings":"Kycklingvingar","preset.frozen_pizza":"Fryst pizza","preset.fresh_pizza":"F\xE4rsk pizza","preset.roast_vegetables":"Ugnsrostade gr\xF6nsaker","preset.roast_chicken":"Helstekt kyckling","preset.cookies":"Sm\xE5kakor","preset.cake":"Mjuk kaka","preset.leftovers":"Rester","preset.salmon_fillets":"Laxfil\xE9er","preset.dried_fruit":"Torkad frukt","preset.bread_dough":"Br\xF6ddeg","preset.pot_roast":"Grytstek","chart.loading":"L\xE4ser in tillagningens temperaturer\u2026","chart.failed":"Det gick inte att l\xE4sa temperaturhistoriken. Ett nytt f\xF6rs\xF6k g\xF6rs om en minut.","chart.none":"Ingen tillagning de senaste dagarna. Diagrammet visar den p\xE5g\xE5ende tillagningen, eller den senaste.","chart.summary_now":"Nu {now}.","chart.summary_now_target":"Nu {now}, m\xE5l {target}.","chart.summary_last":"Den slutade p\xE5 {now}.","chart.summary_last_target":"Den slutade p\xE5 {now}, m\xE5l {target}.","chart.last_cook":"Senaste tillagningen, {start} till {end}.","chart.at_temperature_since":"Uppe i temperatur sedan {time}.","chart.sensor_summary":"Ugnen h\xE5ller sin sensor p\xE5 {temp}.","chart.sensor_caption":"Den streckade linjen visar var ugnen h\xE5ller sin egen sensor: avsiktligt under den inst\xE4llda temperaturen, s\xE5 skillnaden \xE4r inget fel.","chart.last_day":"Visar det senaste dygnet.","chart.temperature":"Temperatur","chart.target":"M\xE5l","chart.sensor_target":"Sensorm\xE5l","chart.time":"Tid","chart.show_table":"Visa som tabell","chart.hide_table":"D\xF6lj tabellen","chart.table_caption":"Temperaturer under tillagningen"};var Jo={"panel.title":"Breville+","panel.menu":"\u6253\u5F00\u4FA7\u8FB9\u680F","panel.back":"\u8FD4\u56DE","overview.no_area":"\u65E0\u533A\u57DF","overview.loading":"\u6B63\u5728\u52A0\u8F7D\u8BBE\u5907\u2026","overview.error_title":"\u65E0\u6CD5\u52A0\u8F7D\u8BBE\u5907","overview.retry":"\u91CD\u8BD5","overview.empty_title":"\u6682\u65E0\u8BBE\u5907","overview.empty_text":"Breville+ Cooking \u96C6\u6210\u6DFB\u52A0\u8BBE\u5907\u540E\uFF0C\u8BBE\u5907\u4F1A\u663E\u793A\u5728\u8FD9\u91CC\u3002\u8BF7\u6DFB\u52A0\u8D26\u6237\uFF0C\u6216\u5728\u96C6\u6210\u9009\u9879\u4E2D\u5F00\u542F\u4FA7\u8FB9\u680F\u9762\u677F\u3002","overview.empty_text_user":"\u7BA1\u7406\u5458\u5C06\u8BBE\u5907\u6DFB\u52A0\u5230 Breville+ Cooking \u96C6\u6210\u540E\uFF0C\u8BBE\u5907\u4F1A\u663E\u793A\u5728\u8FD9\u91CC\u3002","overview.empty_link":"\u6253\u5F00 Breville+ Cooking \u8BBE\u7F6E","overview.not_found_title":"\u672A\u627E\u5230\u8BBE\u5907","overview.not_found_text":"\u6B64\u8BBE\u5907\u5DF2\u4E0D\u5728 Breville+ Cooking \u96C6\u6210\u4E2D\uFF0C\u6216\u8005\u94FE\u63A5\u6709\u8BEF\u3002","overview.back":"\u8FD4\u56DE\u6240\u6709\u8BBE\u5907","card.open_hint":"\u663E\u793A\u6240\u6709\u63A7\u4EF6","status.offline":"\u79BB\u7EBF","status.error":"\u9519\u8BEF","status.updating":"\u66F4\u65B0\u4E2D","status.door_open":"\u7089\u95E8\u6253\u5F00","status.press_start_oven":"\u8BF7\u6309\u4E0B\u70E4\u7BB1\u4E0A\u7684 Start \u952E","status.press_button_joule":"\u8BF7\u6309\u4E0B Joule \u4E0A\u7684\u6309\u94AE","status.preheating":"\u9884\u70ED\u4E2D","status.preheating_pct":"\u9884\u70ED\u4E2D {n}%","status.ready":"\u53EF\u653E\u5165\u98DF\u6750","status.cooking":"\u70F9\u996A\u4E2D","status.done":"\u5DF2\u5B8C\u6210","status.keeping_warm":"\u4FDD\u6E29\u4E2D","status.idle":"\u7A7A\u95F2","display.ready":"\u5C31\u7EEA","display.end":"\u5B8C\u6210","display.press_start":"\u8BF7\u6309 Start \u952E","display.error":"\u9519\u8BEF","display.off":"\u5173\u95ED","info.water":"\u6C34\u6E29","info.now_of_target":"{now}\uFF08\u76EE\u6807 {target}\uFF09","info.time_left":"\u5269\u4F59\u65F6\u95F4","info.time":"\u65F6\u95F4","info.ends":"{time} \u7ED3\u675F","info.paused":"\u5DF2\u6682\u505C","info.cook_time":"\u70F9\u996A\u65F6\u95F4","info.next":"\u4E0B\u4E00\u6B65","info.add_food":"\u653E\u5165\u98DF\u6750\uFF0C\u7136\u540E\u6309\u201C\u7EE7\u7EED\u201D","info.remove_food":"\u53D6\u51FA\u98DF\u6750","info.oven_finished":"\u53D6\u51FA\u98DF\u6750\uFF0C\u7136\u540E\u6309\u201C\u5B8C\u6210\u201D","info.next_cook":"\u4E0B\u6B21\u70F9\u996A","info.problem":"\u95EE\u9898","info.mode":"\u6A21\u5F0F","info.oven":"\u70E4\u7BB1","info.rack":"\u70E4\u67B6","info.rack_value":"\u7B2C {n} \u5C42 \xB7 {accessory}","section.cook":"\u70F9\u996A","section.next_cook":"\u4E0B\u6B21\u70F9\u996A","section.this_cook":"\u672C\u6B21\u70F9\u996A","section.presets":"\u9884\u8BBE","section.chart":"\u6E29\u5EA6","section.details":"\u8BE6\u7EC6\u4FE1\u606F","control.cook":"\u70F9\u996A","control.food_in":"\u98DF\u6750\u5DF2\u653E\u5165","control.food_out":"\u98DF\u6750\u5DF2\u53D6\u51FA","control.water_temperature":"\u6C34\u6E29","control.oven_temperature":"\u70E4\u7BB1\u6E29\u5EA6","control.target":"\u76EE\u6807","control.target_temperature":"\u76EE\u6807\u6E29\u5EA6","control.temperature":"\u6E29\u5EA6","control.time_left":"\u5269\u4F59\u65F6\u95F4","control.cook_time":"\u70F9\u996A\u65F6\u95F4","control.auto_start_timer":"\u81EA\u52A8\u5F00\u59CB\u8BA1\u65F6","control.mode":"\u6A21\u5F0F","control.level_broil":"\u7099\u70E4\u6863\u4F4D","control.level_slow_cook":"\u6162\u7096\u6863\u4F4D","control.convection":"\u5BF9\u6D41","control.frozen":"\u51B7\u51BB\u98DF\u54C1","control.keep_warm":"\u4FDD\u6E29","control.door":"\u7089\u95E8","control.rack":"\u70E4\u67B6","control.model":"\u578B\u53F7","control.finish":"\u5916\u89C2","control.firmware":"\u56FA\u4EF6","control.error":"\u9519\u8BEF","control.tested":"\u63A7\u5236","action.start":"\u5F00\u59CB","action.stop":"\u505C\u6B62","action.finish":"\u5B8C\u6210","action.food_in":"\u5F00\u59CB\u8BA1\u65F6","action.food_out":"\u5B8C\u6210","confirm.start_sous_vide":"\u4EE5 {temp} \u542F\u52A8 {name}\uFF0C\u6301\u7EED {time}\uFF1F","confirm.start_sous_vide_hold":"\u4EE5 {temp} \u542F\u52A8 {name}\uFF0C\u76F4\u5230\u505C\u6B62\uFF1F","confirm.start_oven":"\u542F\u52A8\u70E4\u7BB1\uFF1A{mode}\uFF0C{time}\uFF1F","confirm.stop":"\u8981\u505C\u6B62\u70F9\u996A\u5417\uFF1F","hint.start":"\u4F7F\u7528\u4E0B\u65B9\u7684\u8BBE\u7F6E\u5F00\u59CB\u70F9\u996A\u3002","hint.finish":"\u70F9\u996A\u5DF2\u7ED3\u675F\u3002\u6309\u201C\u5B8C\u6210\u201D\u5373\u53EF\u5173\u95ED\u3002","hint.food_in":"\u653E\u5165\u98DF\u6750\uFF0C\u7136\u540E\u5F00\u59CB\u8BA1\u65F6\u3002","hint.food_out":"\u53D6\u51FA\u98DF\u6750\u5373\u53EF\u5B8C\u6210\u3002","hint.paused":"\u5DF2\u6682\u505C","hint.changes_cook":"\u66F4\u6539\u6B63\u5728\u8FDB\u884C\u7684\u70F9\u996A\u3002","hint.changes_time_left":"\u8BBE\u7F6E\u6B63\u5728\u8FDB\u884C\u7684\u70F9\u996A\u7684\u5269\u4F59\u65F6\u95F4\u3002","hint.auto_start_timer":"\u6C34\u6E29\u8FBE\u5230\u540E\u7ACB\u5373\u5F00\u59CB\u8BA1\u65F6\uFF0C\u65E0\u9700\u7B49\u5F85\u653E\u5165\u98DF\u6750\u3002","hint.auto_start_timer_oven":"\u70E4\u7BB1\u9884\u70ED\u5B8C\u6210\u540E\u7ACB\u5373\u5F00\u59CB\u8BA1\u65F6\uFF0C\u65E0\u9700\u7B49\u5F85\u653E\u5165\u98DF\u6750\u3002","hint.sensor_target":"\u70E4\u7BB1\u5C06\u81EA\u8EAB\u4F20\u611F\u5668\u4FDD\u6301\u5728 {temp}\uFF0C\u4F4E\u4E8E\u8BBE\u5B9A\u6E29\u5EA6\u3002","hint.frozen":"\u4E3A\u51B7\u51BB\u98DF\u54C1\u7A0D\u5FAE\u5EF6\u957F\u70F9\u996A\u65F6\u95F4\u3002","hint.keep_warm":"\u70F9\u996A\u7ED3\u675F\u540E\u4E3A\u98DF\u7269\u4FDD\u6E29\u3002","hint.untested":"\u8FD8\u6CA1\u6709\u4EBA\u7528 Home Assistant \u6D4B\u8BD5\u8FC7\u6B64\u578B\u53F7\u3002","reason.offline":"\u8BBE\u5907\u5DF2\u79BB\u7EBF\u3002","reason.unavailable":"\u5F53\u524D\u4E0D\u53EF\u7528\u3002","reason.untested":"{product} \u7684\u63A7\u5236\u529F\u80FD\u5C1A\u672A\u7ECF\u8FC7\u6D4B\u8BD5\uFF0C\u56E0\u6B64 Home Assistant \u53EA\u4F1A\u76D1\u63A7\u5B83\u3002","reason.open_options":"\u5728\u96C6\u6210\u9009\u9879\u4E2D\u5141\u8BB8\u63A7\u5236","reason.oven_running":"\u6B63\u5728\u8FDB\u884C\u7684\u70E4\u7BB1\u70F9\u996A\u65E0\u6CD5\u66F4\u6539\u3002\u8BF7\u5148\u505C\u6B62\u70F9\u996A\uFF0C\u518D\u66F4\u6539\u8BBE\u7F6E\u3002","value.until_stopped":"\u76F4\u5230\u505C\u6B62","value.open":"\u6253\u5F00","value.closed":"\u5173\u95ED","value.no_error":"\u65E0","value.untested":"\u5C1A\u672A\u6D4B\u8BD5","value.now":"\u5F53\u524D\uFF1A{value}","full.appliance":"\u8BBE\u5907","full.failed":"\u64CD\u4F5C\u5931\u8D25\u3002","full.preheat":"\u9884\u70ED","full.preheat_value":"\u767E\u5206\u4E4B {n}","ctl.saving":"\u6B63\u5728\u4FDD\u5B58\u2026","ctl.decrease":"\u8C03\u4F4E","ctl.increase":"\u8C03\u9AD8","ctl.off":"\u5173\u95ED","ctl.custom":"\u81EA\u5B9A\u4E49","ctl.hours":"\u5C0F\u65F6","ctl.minutes":"\u5206\u949F","ctl.h":"\u5C0F\u65F6","ctl.min":"\u5206\u949F","ctl.set":"\u8BBE\u5B9A","ctl.not_now":"\u6682\u4E0D","ctl.out_of_range":"\u8BF7\u9009\u62E9 {min} \u5230 {max} \u4E4B\u95F4\u7684\u65F6\u957F\u3002","unit.minutes":"{n} \u5206\u949F","unit.hours":"{n} \u5C0F\u65F6","unit.hours_minutes":"{h} \u5C0F\u65F6 {m} \u5206\u949F","unit.days":"{n} \u5929","unit.days_hours":"{d} \u5929 {h} \u5C0F\u65F6","finish.white_polished":"\u767D\u8272\u914D\u629B\u5149\u4E0D\u9508\u94A2","finish.brushed_stainless":"\u62C9\u4E1D\u4E0D\u9508\u94A2","finish.black_stainless":"\u9ED1\u8272\u4E0D\u9508\u94A2","mode.bake":"\u70D8\u7119","mode.air_fry":"\u7A7A\u6C14\u70B8","mode.roast":"\u70E4\u5236","mode.broil":"\u7099\u70E4","mode.pizza":"\u62AB\u8428","mode.cookies":"\u66F2\u5947","mode.reheat":"\u590D\u70ED","mode.slow_cook":"\u6162\u7096","mode.proof":"\u53D1\u9175","mode.warm":"\u4FDD\u6E29","mode.dehydrate":"\u70D8\u5E72","mode.bottom_bake":"\u4E0B\u706B\u70D8\u7119","mode.gentle_broil":"\u66F4\u9165\u8106\u7A7A\u6C14\u70B8","mode.bottom_broil":"\u4E0B\u706B\u7099\u70E4","mode.outer_top_broil":"\u5916\u5708\u7099\u70E4","mode.middle_top_broil":"\u4E2D\u95F4\u4E0A\u706B\u7099\u70E4","mode.windy_broil":"\u70ED\u98CE\u7099\u70E4","mode.toast":"\u5410\u53F8","mode.bagel":"\u8D1D\u679C","mode.keep_warm":"\u4FDD\u6E29","mode.crispy_reheat":"\u9165\u8106\u590D\u70ED","level.low":"\u4F4E","level.medium":"\u4E2D","level.high":"\u9AD8","convection.off":"\u5173\u95ED","convection.on":"\u5F00\u542F","convection.super":"\u8D85\u5F3A","convection_summary.off":"\u65E0\u5BF9\u6D41","convection_summary.on":"\u5BF9\u6D41","convection_summary.super":"\u8D85\u5F3A\u5BF9\u6D41","accessory.roasting_pan":"\u70E4\u76D8","accessory.broil_rack":"\u70E4\u76D8\u4E2D\u7684\u7099\u70E4\u67B6","accessory.air_fry_basket":"\u7A7A\u6C14\u70B8\u7BEE","accessory.pizza_pan":"\u62AB\u8428\u76D8","accessory.wire_rack":"\u70E4\u7F51","accessory.pot":"\u5E26\u76D6\u7684\u9505","food.croissants":"\u7F8A\u89D2\u9762\u5305","food.casserole":"\u4E00\u76D8\u7117\u70E4\u83DC","food.chicken":"\u4E00\u6574\u53EA\u9E21","food.steak":"\u4E00\u5757\u725B\u6392","food.fries":"\u85AF\u6761","food.pizza":"\u4E00\u5F20\u62AB\u8428","food.cookies":"\u66F2\u5947","food.plate":"\u4E00\u76D8\u5269\u83DC","food.dough":"\u4E00\u7897\u9762\u56E2","food.covered_dish":"\u4E00\u4E2A\u5E26\u76D6\u7684\u83DC\u76D8","food.fruit":"\u6C34\u679C\u7247","food.bread":"\u9762\u5305\u7247","food.bagel":"\u5207\u534A\u7684\u8D1D\u679C","food.pizza_slice":"\u4E00\u5757\u62AB\u8428","describe.sous_vide":"{product} \u5939\u5728\u76DB\u6C34\u7684\u5BB9\u5668\u4E0A\u3002","describe.water":"\u6C34\u6E29 {now}\u3002","describe.water_target":"\u6C34\u6E29 {now}\uFF0C\u76EE\u6807 {target}\u3002","describe.time_left":"\u5269\u4F59 {time}\u3002","describe.time_paused":"\u5DF2\u6682\u505C\uFF0C\u5269\u4F59 {time}\u3002","describe.food_bag":"\u6C34\u4E2D\u6709\u4E00\u888B\u98DF\u6750\u3002","describe.tipped":"\u8BBE\u5907\u5DF2\u503E\u5012\u3002","describe.low_water":"\u6C34\u4F4D\u8FC7\u4F4E\u3002","describe.oven_brushed_stainless":"\u62C9\u4E1D\u4E0D\u9508\u94A2\u6B3E {product}\u3002","describe.oven_black_stainless":"\u9ED1\u8272\u4E0D\u9508\u94A2\u6B3E {product}\u3002","describe.mode":"{mode}\u3002","describe.oven_temperature":"\u7089\u5185 {temp}\u3002","describe.rack":"\u7B2C {n} \u5C42\u653E\u7740{accessory}\u3002","describe.rack_food":"\u7B2C {n} \u5C42\u653E\u7740{accessory}\u548C{food}\u3002","describe.door_open":"\u7089\u95E8\u5DF2\u6253\u5F00\u3002","describe.fan_on":"\u98CE\u6247\u5DF2\u5F00\u542F\u3002","describe.fan_super":"\u98CE\u6247\u6B63\u5728\u9AD8\u901F\u8FD0\u8F6C\u3002","announce.ready":"{name} \u5DF2\u53EF\u653E\u5165\u98DF\u6750\u3002","announce.preheated":"{name} \u5DF2\u9884\u70ED\u5B8C\u6BD5\uFF0C\u6B63\u5728\u70F9\u996A\u3002","announce.done":"{name} \u5DF2\u5B8C\u6210\u70F9\u996A\u3002","announce.door_open":"{name}\uFF1A\u7089\u95E8\u5DF2\u6253\u5F00\u3002","announce.press_start":"{name}\uFF1A\u8BF7\u6309\u4E0B\u8BBE\u5907\u4E0A\u7684 Start \u952E\u3002","announce.error":"{name}\uFF1A{error}\u3002","announce.offline":"{name} \u5DF2\u79BB\u7EBF\u3002","presets.builtin":"\u5185\u7F6E","presets.custom":"\u5DF2\u4FDD\u5B58","presets.none":"\u6682\u65E0\u5DF2\u4FDD\u5B58\u7684\u9884\u8BBE\u3002\u7BA1\u7406\u5458\u53EF\u4EE5\u6DFB\u52A0\u3002","presets.none_admin":"\u6682\u65E0\u5DF2\u4FDD\u5B58\u7684\u9884\u8BBE\u3002\u5148\u8BBE\u7F6E\u597D\u4E00\u6B21\u70F9\u996A\uFF0C\u518D\u5728\u8FD9\u91CC\u4FDD\u5B58\u3002","presets.disabled_cooking":"\u9884\u8BBE\u7528\u4E8E\u8BBE\u7F6E\u4E0B\u4E00\u6B21\u70F9\u996A\u3002\u8BF7\u5148\u505C\u6B62\u6216\u5B8C\u6210\u672C\u6B21\u70F9\u996A\u3002","presets.applied":"\u5DF2\u586B\u5165\u201C{name}\u201D\u7684\u8BBE\u7F6E\u3002\u51C6\u5907\u597D\u540E\u8BF7\u6309\u201C\u5F00\u59CB\u201D\u3002","presets.saved":"\u5DF2\u4FDD\u5B58\u201C{name}\u201D\u3002","presets.renamed":"\u5DF2\u91CD\u547D\u540D\u4E3A\u201C{name}\u201D\u3002","presets.updated":"\u5DF2\u7528\u5F53\u524D\u8BBE\u7F6E\u66F4\u65B0\u201C{name}\u201D\u3002","presets.deleted":"\u5DF2\u5220\u9664\u201C{name}\u201D\u3002","presets.save_current":"\u5C06\u5F53\u524D\u8BBE\u7F6E\u4FDD\u5B58\u4E3A\u9884\u8BBE","presets.save_hint":"\u4FDD\u5B58\u7684\u9884\u8BBE\u4F1A\u4E0E\u6240\u6709\u4F7F\u7528 Home Assistant \u7684\u4EBA\u5171\u4EAB\u3002","presets.name":"\u9884\u8BBE\u540D\u79F0","presets.save":"\u4FDD\u5B58","presets.cancel":"\u53D6\u6D88","presets.update":"\u66F4\u65B0","presets.delete":"\u5220\u9664","presets.rename_named":"\u91CD\u547D\u540D\u201C{name}\u201D","presets.update_named":"\u7528\u5F53\u524D\u8BBE\u7F6E\u66F4\u65B0\u201C{name}\u201D","presets.delete_named":"\u5220\u9664\u201C{name}\u201D","presets.delete_confirm":"\u8981\u4E3A\u6240\u6709\u4EBA\u5220\u9664\u201C{name}\u201D\u5417\uFF1F","presets.update_confirm":"\u8981\u7528\u5F53\u524D\u8BBE\u7F6E\u66FF\u6362\u201C{name}\u201D\u7684\u8BBE\u7F6E\u5417\uFF1F","presets.frozen":"\u51B7\u51BB","presets.note.raw_safe_fish":"\u8BF7\u4F7F\u7528\u53EF\u4EE5\u751F\u5403\u7684\u9C7C\u3002","presets.disclaimer":"\u9884\u8BBE\u4EC5\u4F9B\u53C2\u8003\u3002\u8BF7\u9075\u5FAA\u53EF\u9760\u7684\u70F9\u996A\u6307\u5357\uFF0C\u5E76\u786E\u4FDD\u98DF\u7269\u5DF2\u5B89\u5168\u70F9\u719F\u3002","presets.error.cook_running":"\u8BF7\u5148\u505C\u6B62\u70F9\u996A\uFF1A\u9884\u8BBE\u7528\u4E8E\u8BBE\u7F6E\u4E0B\u4E00\u6B21\u70F9\u996A\u3002","presets.error.unknown_appliance":"\u6B64\u8BBE\u5907\u5DF2\u4E0D\u5728\u9762\u677F\u4E2D\u3002","presets.error.unknown_preset":"\u8BE5\u9884\u8BBE\u5DF2\u4E0D\u5B58\u5728\u3002","presets.error.invalid_preset":"\u8BE5\u9884\u8BBE\u4E0D\u9002\u7528\u4E8E\u6B64\u8BBE\u5907\u3002","presets.error.too_many_presets":"\u6700\u591A\u53EA\u80FD\u4FDD\u5B58 50 \u4E2A\u9884\u8BBE\u3002\u8BF7\u5148\u5220\u9664\u4E00\u4E2A\u3002","presets.error.unavailable":"\u8BBE\u5907\u5F53\u524D\u4E0D\u53EF\u7528\u3002","presets.error.unauthorized":"\u53EA\u6709\u7BA1\u7406\u5458\u624D\u80FD\u66F4\u6539\u4FDD\u5B58\u7684\u9884\u8BBE\u3002","preset.steak_rare":"\u4E00\u5206\u719F\u725B\u6392","preset.steak_medium_rare":"\u4E09\u5206\u719F\u725B\u6392","preset.steak_medium":"\u4E94\u5206\u719F\u725B\u6392","preset.steak_well_done":"\u5168\u719F\u725B\u6392","preset.beef_roast":"\u70E4\u725B\u8089","preset.short_ribs":"\u725B\u5C0F\u6392","preset.pork_chop":"\u732A\u6392","preset.pulled_pork":"\u624B\u6495\u732A\u80A9\u8089","preset.chicken_breast":"\u9E21\u80F8\u8089","preset.chicken_thighs":"\u9E21\u817F\u8089","preset.salmon":"\u4E09\u6587\u9C7C","preset.white_fish":"\u767D\u8089\u9C7C","preset.shrimp":"\u9C9C\u867E","preset.soft_eggs":"\u6E8F\u5FC3\u86CB","preset.vegetables":"\u852C\u83DC","preset.frozen_fries":"\u51B7\u51BB\u85AF\u6761","preset.chicken_wings":"\u9E21\u7FC5","preset.frozen_pizza":"\u51B7\u51BB\u62AB\u8428","preset.fresh_pizza":"\u65B0\u9C9C\u62AB\u8428","preset.roast_vegetables":"\u70E4\u852C\u83DC","preset.roast_chicken":"\u70E4\u9E21","preset.cookies":"\u66F2\u5947","preset.cake":"\u86CB\u7CD5","preset.leftovers":"\u5269\u83DC","preset.salmon_fillets":"\u4E09\u6587\u9C7C\u67F3","preset.dried_fruit":"\u679C\u5E72","preset.bread_dough":"\u9762\u5305\u9762\u56E2","preset.pot_roast":"\u7096\u725B\u8089","chart.loading":"\u6B63\u5728\u52A0\u8F7D\u672C\u6B21\u70F9\u996A\u7684\u6E29\u5EA6\u2026","chart.failed":"\u65E0\u6CD5\u8BFB\u53D6\u6E29\u5EA6\u5386\u53F2\u8BB0\u5F55\uFF0C\u5C06\u5728\u4E00\u5206\u949F\u540E\u91CD\u8BD5\u3002","chart.none":"\u6700\u8FD1\u51E0\u5929\u6CA1\u6709\u70F9\u996A\u3002\u56FE\u8868\u4F1A\u663E\u793A\u5F53\u524D\u70F9\u996A\u6216\u4E0A\u4E00\u6B21\u70F9\u996A\u3002","chart.summary_now":"\u5F53\u524D {now}\u3002","chart.summary_now_target":"\u5F53\u524D {now}\uFF0C\u76EE\u6807 {target}\u3002","chart.summary_last":"\u7ED3\u675F\u65F6\u6E29\u5EA6\u4E3A {now}\u3002","chart.summary_last_target":"\u7ED3\u675F\u65F6\u6E29\u5EA6\u4E3A {now}\uFF0C\u76EE\u6807 {target}\u3002","chart.last_cook":"\u4E0A\u6B21\u70F9\u996A\uFF1A{start} \u81F3 {end}\u3002","chart.at_temperature_since":"\u81EA {time} \u8D77\u5DF2\u8FBE\u5230\u76EE\u6807\u6E29\u5EA6\u3002","chart.sensor_summary":"\u70E4\u7BB1\u5C06\u81EA\u8EAB\u4F20\u611F\u5668\u4FDD\u6301\u5728 {temp}\u3002","chart.sensor_caption":"\u865A\u7EBF\u8868\u793A\u70E4\u7BB1\u81EA\u8EAB\u4F20\u611F\u5668\u4FDD\u6301\u7684\u6E29\u5EA6\uFF1A\u6309\u8BBE\u8BA1\u4F1A\u4F4E\u4E8E\u8BBE\u5B9A\u6E29\u5EA6\uFF0C\u56E0\u6B64\u8FD9\u4E00\u5DEE\u503C\u5E76\u975E\u6545\u969C\u3002","chart.last_day":"\u663E\u793A\u6700\u8FD1\u4E00\u5929\u3002","chart.temperature":"\u6E29\u5EA6","chart.target":"\u76EE\u6807","chart.sensor_target":"\u4F20\u611F\u5668\u76EE\u6807","chart.time":"\u65F6\u95F4","chart.show_table":"\u4EE5\u8868\u683C\u663E\u793A","chart.hide_table":"\u9690\u85CF\u8868\u683C","chart.table_caption":"\u70F9\u996A\u671F\u95F4\u7684\u6E29\u5EA6"};var Yo=["en","de","es","fr","it","nl","pl","sv","zh-Hans"],Xo={en:Fo,de:Io,es:Uo,fr:Ko,it:Wo,nl:qo,pl:Zo,sv:Qo,"zh-Hans":Jo};function Xa(t){if(!t)return"en";if(Yo.includes(t))return t;let e=t.split(/[-_]/)[0].toLowerCase();return e==="zh"?"zh-Hans":Yo.includes(e)?e:"en"}function qt(t){let e=Xa(t),r={...Xo.en,...Xo[e]};return(o,n)=>{let a=r[o]??o;return n?a.replace(/\{(\w+)\}/g,(i,s)=>String(n[s]??i)):a}}function Kr(t){return t?.locale?.language||t?.language||"en"}var en=new Map;function K(t){let e=Kr(t),r=en.get(e);return r||(r=qt(e),en.set(e,r)),r}var tn=new Map;function rn(t){let e=tn.get(t);if(!e){try{e=new Intl.Collator(t,{numeric:!0,sensitivity:"base"})}catch{e=new Intl.Collator(void 0,{numeric:!0,sensitivity:"base"})}tn.set(t,e)}return e}async function Zt(t,e){let{translation_domain:r,translation_key:o,translation_placeholders:n}=e&&typeof e=="object"?e:{};if(r&&o&&typeof t?.loadBackendTranslation=="function")try{let i=(await t.loadBackendTranslation("exceptions",r))(`component.${r}.exceptions.${o}.message`,n??{});if(i)return i}catch{}return Wr(e)}function Wr(t){if(t&&typeof t=="object"&&"message"in t){let e=t.message;if(typeof e=="string"&&e)return e}return typeof t=="string"&&t?t:String(t??"")}function at(t,e){let r=e?.devices?.[t.device_id];return r?.name_by_user||r?.name||t.name}var on={oven:0,sous_vide:1};function ei(t){let e=Object.values(t??{}),r=new Map;for(let n of e)n.floor_id&&!r.has(n.floor_id)&&r.set(n.floor_id,r.size);let o=e.map((n,a)=>({id:n.area_id,floor:r.get(n.floor_id??"")??r.size,index:a}));return o.sort((n,a)=>n.floor-a.floor||n.index-a.index),new Map(o.map((n,a)=>[n.id,a]))}function nn(t,e){let r=rn(Kr(e)),o=new Map;for(let a of t){let i=e?.devices?.[a.device_id]?.area_id??null,s=i?e?.areas?.[i]:void 0,l=s?i:null,c=o.get(l);c||(c={areaId:l,name:s?.name??null,appliances:[]},o.set(l,c)),c.appliances.push({appliance:a,name:at(a,e)})}for(let a of o.values())a.appliances.sort((i,s)=>(on[i.appliance.kind]??2)-(on[s.appliance.kind]??2)||r.compare(i.name,s.name)||i.appliance.device_id.localeCompare(s.appliance.device_id));let n=ei(e?.areas);return[...o.values()].sort((a,i)=>a.areaId===null||i.areaId===null?a.areaId===null?1:-1:(n.get(a.areaId)??0)-(n.get(i.areaId)??0))}function Qt(t,e,r){if(!t||t.language!==e.language||t.locale!==e.locale||t.themes!==e.themes||t.config!==e.config||t.user!==e.user||t.devices?.[r.device_id]!==e.devices?.[r.device_id])return!0;for(let o of Object.values(r.entities))for(let n of Object.values(o))if(n&&t.states[n]!==e.states[n])return!0;return!1}var ti="/bruh-cooking";function Jt(t){let[e]=(t??"").split(/[?#]/)[0].split("/").filter(Boolean);if(!e)return{view:"overview"};let r=e;try{r=decodeURIComponent(e)}catch{}return{view:"appliance",deviceId:r}}function qr(t,e){let r=(t||ti).replace(/\/+$/,"");return e.view==="overview"?r:`${r}/${encodeURIComponent(e.deviceId)}`}function Yt(t,e={}){let r=e.replace===!0;r?history.replaceState(history.state,"",t):history.pushState(null,"",t),window.dispatchEvent(new CustomEvent("location-changed",{detail:{replace:r}}))}function Xt(t){if(t.defaultPrevented||t.button!==0||t.metaKey||t.ctrlKey||t.shiftKey||t.altKey)return;let e=t.currentTarget;e instanceof HTMLAnchorElement&&(t.preventDefault(),Yt(e.getAttribute("href")??"/"))}var er=class{constructor(e,r){this.onMessage=e;this.onError=r}connect(e){if(e===this.connection||(this.disconnect(),!e))return;this.connection=e;let r;try{r=e.subscribeMessage(o=>{this.connection===e&&this.onMessage(o)},{type:"bruh_cooking/panel/subscribe"})}catch(o){r=Promise.reject(o)}this.unsubscribe=r.catch(o=>{this.connection===e&&this.onError(o)})}disconnect(){let e=this.unsubscribe;this.connection=void 0,this.unsubscribe=void 0,e?.then(r=>r?.()).catch(()=>{})}retry(){let e=this.connection;this.disconnect(),this.connect(e)}};function Ce(t){let e=t?.state;return e===void 0||e===""||e==="unavailable"||e==="unknown"?null:e}function O(t,e,...r){if(!r.length)return Ce(t.state(e));for(let o of r){let n=Ce(t.state(e,o));if(n!==null)return n}return null}function oe(t,e,...r){let o=O(t,e,...r.length?r:["binary_sensor","switch"]);return o==="on"?!0:o==="off"?!1:null}function fe(t){if(typeof t=="number")return Number.isFinite(t)?t:null;if(typeof t!="string"||t.trim()==="")return null;let e=Number(t);return Number.isFinite(e)?e:null}function Q(t,e,...r){return fe(O(t,e,...r))}function ri(t){return O(t,"status","sensor")}function I(t){let e=ri(t);if(!t.appliance.available||e===null||e==="offline")return"offline";if(e==="error"||oe(t,"problem","binary_sensor")===!0)return"error";if(e==="updating")return"updating";if(oe(t,"cook","switch")===!0&&oe(t,"door","binary_sensor")===!0)return"door_open";switch(e){case"waiting_for_button":return"press_start";case"preheating":case"ready":case"cooking":case"done":case"keeping_warm":return e;default:return"idle"}}function we(t){return oe(t,"cook","switch")===!0}function Me(t){return oe(t,"cooking","binary_sensor")===!0}function xe(t){return t.config?.unit_system?.temperature||"\xB0C"}function me(t){return xe(t).includes("C")}function St(t,e){return me(t)?e:e*9/5+32}function Qr(t,e){let r=e?.attributes?.unit_of_measurement;return typeof r=="string"&&r?r:xe(t)}function rr(t){return t.locale?.language||t.language||"en"}var an={comma_decimal:["en-US","en"],decimal_comma:["de","es","it"],space_comma:["fr","sv","cs"],system:void 0},sn=new Map;function Pe(t,e,r=0,o=0){let n=t.locale?.number_format,a=n==="none"?"en-US":n&&n in an?an[n]:rr(t),i=`${n}|${String(a)}|${o}|${r}`,s=sn.get(i);if(!s){let l={minimumFractionDigits:o,maximumFractionDigits:r,...n==="none"?{useGrouping:!1}:{}};try{s=new Intl.NumberFormat(a,l)}catch{s=new Intl.NumberFormat(void 0,l)}sn.set(i,s)}return s.format(e)}function ne(t,e,r=0){if(e===null)return"\u2014";let o=Pe(t,e,r);return`${o==="-0"?"0":o}\xB0`}function D(t,e,r,o=0){if(e===null)return"\u2014";let n=Pe(t,e,o);return`${n==="-0"?"0":n} ${r}`}function dn(t){return t.locale?.time_zone==="server"&&t.config?.time_zone||void 0}function oi(){try{return new Intl.DateTimeFormat(void 0,{hour:"numeric"}).resolvedOptions().hour12}catch{return}}function un(t){let e=t.locale?.time_format,r=dn(t),o=e==="12"?!0:e==="24"?!1:e==="system"?oi():void 0;return{hour:"numeric",minute:"2-digit",...o===void 0?{}:{hour12:o},...r?{timeZone:r}:{}}}function Jr(t,e,r){try{return new Intl.DateTimeFormat(rr(t),e).format(r)}catch{return new Intl.DateTimeFormat("en",{...e,timeZone:void 0}).format(r)}}function he(t,e){return Jr(t,un(t),e)}function ln(t,e){return Jr(t,{year:"numeric",month:"2-digit",day:"2-digit",timeZone:dn(t)},e)}function or(t,e,r){return ln(t,e)===ln(t,r)?he(t,e):Jr(t,{weekday:"short",...un(t)},e)}var Zr=t=>String(t).padStart(2,"0");function Ye(t){let e=Math.max(0,Math.ceil(t/1e3)),r=Math.floor(e/3600),o=Math.floor(e%3600/60),n=e%60;return r?`${r}:${Zr(o)}:${Zr(n)}`:`${o}:${Zr(n)}`}function ge(t,e){let r=Math.max(0,Math.round(e/60));if(r<60)return t("unit.minutes",{n:r});let o=Math.floor(r/60),n=r%60;if(o<48)return n?t("unit.hours_minutes",{h:o,m:n}):t("unit.hours",{n:o});let a=Math.floor(o/24),i=o%24;return i?t("unit.days_hours",{d:a,h:i}):t("unit.days",{n:a})}var tr=new Map;function cn(t,e){let r=`${rr(t)}|${e}`;if(!tr.has(r))try{tr.set(r,new Intl.NumberFormat(rr(t),{style:"unit",unit:e,unitDisplay:"long"}))}catch{tr.set(r,null)}return tr.get(r)??null}function nr(t,e,r){let o=Math.max(0,Math.round(r/60)),n=Math.floor(o/60),a=o%60,i=cn(t,"hour"),s=cn(t,"minute");return!i||!s?ge(e,r):[n?i.format(n):null,a||!n?s.format(a):null].filter(Boolean).join(", ")}var pn={ms:.001,s:1,min:60,h:3600,d:86400};function ni(t){let e=fe(Ce(t));if(e===null)return null;let r=t?.attributes?.unit_of_measurement;return e*(typeof r=="string"&&r in pn?pn[r]:1)}function Re(t,e){let r=Q(t,e,"number");return r===null?null:r*60}function be(t){let e=t.state("time_remaining","sensor"),r=ni(e);if(r===null||!e)return null;let o=O(t,"cook_end","sensor")!==null,n=Date.parse(e.last_updated);return{seconds:r,end:o&&Number.isFinite(n)?n+r*1e3:null}}function Ee(t,e){return t.end===null?t.seconds:Math.max(0,(t.end-e)/1e3)}function fn(t,e){let r=Ce(e);if(r===null||!e)return"\u2014";if(t.formatEntityState)try{return t.formatEntityState(e)}catch{}let o=fe(r),n=e.attributes?.unit_of_measurement,a=o===null?r:Pe(t,o,1);return typeof n=="string"&&n?`${a} ${n}`:a}function ee(t,e=" \xB7 "){let r=t.filter(o=>typeof o=="string"&&o!=="");return r.length?r.join(e):null}function Le(t,e,r){let o=`${e}.${r}`,n=t(o);return n===o?r.replace(/_/g," "):n}function ai(t,e,r){if(!t.appliance.available)return{disabled:!0,reason:t.t("reason.offline")};for(let o of r.reasons??[])if(o)return{disabled:!0,reason:o};return!e||e.state==="unavailable"?{disabled:!0,reason:t.t("reason.unavailable")}:{disabled:!1,reason:null}}function Xe(t,e,r){let o=t.entityId(e,r);return o?{entityId:o,entity:t.hass.states[o]}:null}function He(t,e,r,o,n={}){let a=ai(t,o,n);return{id:n.id??e,label:r,hint:n.hint??null,...a,link:a.disabled?n.link??null:null}}function ar(t,e,r,o={}){let n=Xe(t,e,"number");if(!n)return null;let a=n.entity?.attributes??{};return{kind:"setpoint",...He(t,e,r,n.entity,o),action:{type:"number",entity_id:n.entityId},value:fe(Ce(n.entity)),min:fe(a.min)??0,max:fe(a.max)??100,step:o.step??fe(a.step)??1,unit:Qr(t.hass,n.entity)}}function ir(t,e,r,o,n={}){let a=Xe(t,e,"number");if(!a)return null;let i=a.entity?.attributes??{},s=fe(Ce(a.entity));return{kind:"duration",...He(t,e,r,a.entity,n),action:{type:"number",entity_id:a.entityId},value:s===null?null:Math.round(s),min:fe(i.min)??0,max:fe(i.max)??5760,presets:o,zero:n.zero??null}}function sr(t,e,r,o,n={}){let a=Xe(t,e,"select");if(!a)return null;let i=a.entity?.attributes?.options,s=Array.isArray(i)?i.filter(l=>typeof l=="string"):[];return{kind:"select",...He(t,e,r,a.entity,n),action:{type:"select",entity_id:a.entityId},value:Ce(a.entity)??n.fallback??null,options:s.map(l=>({value:l,label:Le(t.t,o,l)})),...n.tiles?{tiles:!0}:{}}}function it(t,e,r,o={}){let n=Xe(t,e,"switch");if(!n)return null;let a=Ce(n.entity);return{kind:"toggle",...He(t,e,r,n.entity,o),action:{type:"switch",entity_id:n.entityId},value:a==="on"?!0:a==="off"?!1:null}}function W(t,e,r,o={}){return{kind:"reading",id:t,label:e,value:r??"\u2014",hint:o.hint??null,...o.tone?{tone:o.tone}:{}}}function De(t,e,r,o={}){let n=r.filter(a=>!!a);return n.length?{id:t,title:e,controls:n,...o.note?{note:o.note}:{},...o.collapsed?{collapsed:!0}:{}}:null}function lr(t){return t.filter(e=>e!=null&&e!==!1)}function cr(t){return t.hass.user?.is_admin!==!0?null:{text:t.t("reason.open_options"),href:"/config/integrations/integration/bruh_cooking"}}function pr(t){return t.appliance.control_allowed?null:t.t("reason.untested",{product:t.appliance.product})}function ze(t){let e=t.state("error","sensor"),r=O(t,"error","sensor");return!e||r===null||r==="none"?t.t("status.error"):fn(t.hass,e)}function st(t,e,r){let o=t.t;switch(e){case"offline":return{text:o("status.offline"),tone:"gray"};case"error":return{text:ze(t),tone:"red"};case"updating":return{text:o("status.updating"),tone:"gray"};case"door_open":return{text:o("status.door_open"),tone:"amber"};case"press_start":return{text:o(r),tone:"amber"};case"preheating":{let n=Q(t,"preheat","sensor");return{text:n===null?o("status.preheating"):o("status.preheating_pct",{n:Math.round(n)}),tone:"warm"}}case"ready":return{text:o("status.ready"),tone:"green"};case"cooking":return{text:o("status.cooking"),tone:"warm"};case"done":return{text:o("status.done"),tone:"green"};case"keeping_warm":return{text:o("status.keeping_warm"),tone:"warm"};default:return{text:o("status.idle"),tone:"neutral"}}}function Yr(t){return we(t)&&!Me(t)&&O(t,"status","sensor")==="done"}function dr(t,e){let r=t.t,o=Xe(t,"cook","switch"),n=[],a=pr(t),i=a?cr(t):null;if(o)if(!we(t))n.push({kind:"action",...He(t,"start",r("control.cook"),o.entity,{reasons:[a],link:i,hint:r("hint.start")}),action:{type:"switch_on",entity_id:o.entityId},confirm:e,button:r("action.start"),tone:"primary"});else{let l=Yr(t);n.push({kind:"action",...He(t,"stop",r("control.cook"),o.entity,{hint:l?r("hint.finish"):null}),action:{type:"switch_off",entity_id:o.entityId},confirm:l?null:r("confirm.stop"),button:r(l?"action.finish":"action.stop"),tone:l?"primary":"danger"})}let s=Xe(t,"continue","button");if(s&&s.entity&&s.entity.state!=="unavailable"){let l=O(t,"status","sensor")==="done";n.push({kind:"action",...He(t,"continue",r(l?"control.food_out":"control.food_in"),s.entity,{reasons:[a],link:i,hint:r(l?"hint.food_out":"hint.food_in")}),action:{type:"button",entity_id:s.entityId},confirm:null,button:r(l?"action.food_out":"action.food_in"),tone:"primary"})}return n}function ur(t){let e=t.t,r=t.appliance,o=t.hass.devices?.[r.device_id],n=oe(t,"problem","binary_sensor")===!0;return De("details",e("section.details"),[W("model",e("control.model"),`${r.product} (${r.model})`),W("finish",e("control.finish"),e(`finish.${r.finish}`)),o?.sw_version?W("firmware",e("control.firmware"),o.sw_version):null,t.state("error","sensor")?W("error",e("control.error"),n?ze(t):e("value.no_error"),{tone:n?"alert":"normal"}):null,r.tested?null:W("tested",e("control.tested"),e("value.untested"),{hint:e("hint.untested")})],{collapsed:!n})}var ii={id:"bake",remote:!0,type:"temp",rack:6,accessory:"roasting_pan",food:"croissants",elements:"top_bottom"},mn=[5,10,15,20,30,45,60,90,120,240,480],si=new Set(["preheating","ready","cooking","keeping_warm"]),li=new Set(["preheating","ready","cooking","keeping_warm","door_open"]),ci={low:"Lo",medium:"MEd",high:"HI"},pi=new Set(["cooking","done","keeping_warm"]);function gn(t){if(we(t)){let e=O(t,"active_mode","sensor");if(e)return e}return O(t,"oven_mode","select")}function et(t){let e=gn(t);return e&&t.modes.get(e)||t.modes.get("bake")||ii}function di(t,e){if(e==="keeping_warm"){let r=O(t,"oven_mode","select"),o=r?t.modes.get(r):void 0;if(o)return o}return et(t)}function lt(t){return Le(t.t,"mode",gn(t)??et(t).id)}function fr(t){return Q(t,"target_temperature","number")}function At(t,e){if(e.type==="broil"||e.type==="slow_cook"){let o=O(t,"level","select");return o?Le(t.t,"level",o):null}let r=fr(t);return r===null?null:ne(t.hass,r)}function hn(t,e){let r=O(t,"convection","select");return!r||(e.convection?.length??0)<=1?null:Le(t.t,"convection_summary",r)}function ui(t){let e=t.appliance.sensor_target_c;return e==null?null:St(t.hass,e)}function fi(t,e){let r=t.t,o=lt(t),n=Q(t,"current_temperature","sensor"),a=At(t,et(t));switch(e){case"offline":return null;case"preheating":return{main:ne(t.hass,n),caption:ee([o,a]),dim:!1};case"ready":return{main:ne(t.hass,n??fr(t)),caption:r("display.ready"),dim:!1};case"cooking":case"keeping_warm":case"door_open":{let i=be(t);return i?{main:Ye(Ee(i,t.now)*1e3),caption:ee([o,a]),dim:!1}:{main:ne(t.hass,n),caption:ee([o,a]),dim:!1}}case"done":return{main:r("display.end"),caption:o,dim:!0};case"press_start":return{main:a??o,caption:r("display.press_start"),dim:!0};case"error":return{main:r("display.error"),caption:ze(t),dim:!1};default:return{main:r("display.off"),caption:null,dim:!0}}}function mi(t){let e=Math.max(0,Math.ceil(t)),r=n=>String(n).padStart(2,"0");if(e<3600)return{text:`${Math.floor(e/60)}:${r(e%60)}`,units:"min_sec"};let o=Math.floor(e/60);return{text:`${Math.floor(o/60)}:${r(o%60)}`,units:"hr_min"}}function hi(t,e){if(e==="offline"||e==="idle"||e==="updating")return null;let r=et(t),o=e==="error",n=e==="keeping_warm",a=r.temperature_c?St(t.hass,r.temperature_c.min):null,i=fr(t),s=i!==null&&a!==null&&i<a-1?null:i,l=O(t,"level","select"),c=o?"Err":n?null:r.type==="temp"?s===null?null:String(Math.round(s)):l?ci[l]??null:null,d=be(t),b=e==="cooking"||e==="door_open"||n?d?Ee(d,t.now):null:Re(t,"cook_time"),$=e==="done"?{text:"donE",units:null}:o||b===null?{text:null,units:null}:mi(b),v=O(t,"convection","select");return{lit:li.has(e),mode:n?"keep_warm":r.id,temp:c,unit:r.type==="temp"&&!o&&!n?me(t.hass)?"C":"F":null,time:$.text,timeUnits:$.units,convection:v==="on"||v==="super"?v:"off",rack:e==="press_start"||e==="preheating"?r.rack:null,prompt:e==="press_start"?"press_start":e==="preheating"?"preheating":null,frozen:r.frozen!==null&&r.frozen!==void 0&&oe(t,"frozen","switch")===!0}}function Xr(t,e){return t.t(`accessory.${e.accessory}`)}var eo={phase:I,drawingState(t){let e=I(t),r=di(t,e),o=oe(t,"door","binary_sensor")===!0,n=si.has(e)&&!o,a=O(t,"convection","select");return{kind:"oven",available:t.appliance.available,mode:r.id,rack:r.rack,accessory:r.accessory,food:pi.has(e)||e==="door_open"&&Me(t)?r.food:null,frozen:r.frozen!==null&&r.frozen!==void 0&&oe(t,"frozen","switch")===!0,elements:n?e==="keeping_warm"?"low":r.elements:null,fan:n&&(a==="on"||a==="super")?a:"off",door_open:o,light:o||n||e==="cooking",lcd:hi(t,e),start_prompt:e==="press_start",error:e==="error"}},status:t=>st(t,I(t),"status.press_start_oven"),infoRows(t){let e=t.t,r=I(t),o=et(t),n=ee([lt(t),At(t,o),hn(t,o)])??"\u2014",a=e("info.rack_value",{n:o.rack,accessory:Xr(t,o)}),i=[];if(r==="idle"||r==="offline"||r==="error"||r==="updating"){let c=Re(t,"cook_time");return i.push({label:e("info.next_cook"),value:ee([n,c?ge(e,c):null])??"\u2014"}),i.push({label:e("info.rack"),value:a}),r==="error"&&i.push({label:e("info.problem"),value:ze(t)}),i}i.push({label:e("info.mode"),value:n});let s=Q(t,"current_temperature","sensor");if(r==="preheating"||r==="ready"||r==="press_start")return s!==null&&i.push({label:e("info.oven"),value:ne(t.hass,s)}),i.push({label:e("info.rack"),value:a}),i;let l=be(t);if(l&&r!=="done"){let c=l.end===null?e("info.paused"):e("info.ends",{time:he(t.hass,l.end)});i.push({label:e("info.time_left"),value:ee([Ye(Ee(l,t.now)*1e3),c])??"\u2014"})}return r==="done"?i.push({label:e("info.next"),value:e(Yr(t)?"info.oven_finished":"info.remove_food")}):s!==null&&i.length<3&&i.push({label:e("info.oven"),value:ne(t.hass,s)}),i},display(t){let e=fi(t,I(t));return e?{text:e.main,caption:e.caption,dim:e.dim}:null},sections(t){let e=t.t,r=I(t),o=et(t),n=xe(t.hass),a=Me(t),i=we(t),s=Q(t,"current_temperature","sensor"),l=ui(t),c=be(t),d=Re(t,"cook_time"),m=ee([lt(t),o.type==="temp"?D(t.hass,fr(t),n):At(t,o)]," "),b=e("confirm.start_oven",{mode:m??lt(t),time:d?ge(e,d):"\u2014"}),$=oe(t,"door","binary_sensor"),v=[i||s!==null?W("current_temperature",e("control.oven_temperature"),D(t.hass,s,n),{hint:l!==null?e("hint.sensor_target",{temp:D(t.hass,l,n)}):null}):null,i?W("mode",e("control.mode"),ee([lt(t),At(t,o),hn(t,o)])):null,i&&c&&r!=="done"?{kind:"countdown",id:"time_left",label:e("control.time_left"),end:c.end,seconds:c.seconds,hint:c.end===null?e("hint.paused"):e("info.ends",{time:he(t.hass,c.end)})}:null,$===null?null:W("door",e("control.door"),e($?"value.open":"value.closed"),{tone:$&&i?"warning":"normal"}),r==="idle"||r==="preheating"||r==="ready"?W("rack",e("control.rack"),e("info.rack_value",{n:o.rack,accessory:Xr(t,o)})):null],z=a?e("reason.oven_running"):null,T=[z],G=sr(t,"oven_mode",e("control.mode"),"mode",{tiles:!0,reasons:T}),X=o.type==="temp"?ar(t,"target_temperature",e("control.temperature"),{reasons:T}):null,R=o.type==="broil"||o.type==="slow_cook"?sr(t,"level",e(`control.level_${o.type}`),"level",{reasons:T}):null,U=ir(t,"cook_time",e("control.cook_time"),mn,{reasons:T}),V=U&&U.kind==="duration"?{...U,presets:mn.filter(vt=>vt>=U.min&&vt<=U.max)}:U,ye=(o.convection?.length??0)>1?sr(t,"convection",e("control.convection"),"convection",{reasons:T}):null,Hr=[G,X,R,V,ye,o.frozen!==null&&o.frozen!==void 0?it(t,"frozen",e("control.frozen"),{reasons:T,hint:e("hint.frozen")}):null,o.keep_warm?it(t,"keep_warm",e("control.keep_warm"),{reasons:T,hint:e("hint.keep_warm")}):null,o.preheat?it(t,"auto_start_timer",e("control.auto_start_timer"),{reasons:T,hint:e("hint.auto_start_timer_oven")}):null];return lr([De("cook",e("section.cook"),[...v,...dr(t,b)]),De("settings",e(a?"section.this_cook":"section.next_cook"),Hr,{note:z}),ur(t)])},describe(t){let e=t.t,r=eo.drawingState(t),o=I(t),n=et(t),a=[e(`describe.oven_${t.appliance.finish}`,{product:t.appliance.product})];if(a.push(`${st(t,o,"status.press_start_oven").text}.`),o!=="idle"&&o!=="offline"){let c=ee([lt(t),At(t,n)],", ");c&&a.push(e("describe.mode",{mode:c}))}let i=Q(t,"current_temperature","sensor");i!==null&&a.push(e("describe.oven_temperature",{temp:D(t.hass,i,xe(t.hass))}));let s=be(t);s&&(o==="cooking"||o==="door_open")&&a.push(e(s.end===null?"describe.time_paused":"describe.time_left",{time:nr(t.hass,e,Ee(s,t.now))}));let l=Xr(t,n);return a.push(r.food?e("describe.rack_food",{n:r.rack,accessory:l,food:e(`food.${r.food}`)}):e("describe.rack",{n:r.rack,accessory:l})),r.door_open&&a.push(e("describe.door_open")),r.fan!=="off"&&a.push(e(`describe.fan_${r.fan}`)),a.join(" ")}};var gi=[0,30,60,90,120,240];function mr(t){let e=Qr(t.hass,t.state("current_temperature","sensor"));return{current:Q(t,"current_temperature","sensor"),target:Q(t,"target_temperature","number"),unit:e}}function bi(t,e){return e===null?null:me(t.hass)?e:(e-32)*5/9}function $i(t){if(I(t)!=="error")return null;let e=O(t,"error","sensor");return e==="low_water_level"?"low_water":e==="tipped_over"?"tipped":"other"}function to(t,e){return e?ge(t.t,e):t.t("value.until_stopped")}var ro={phase:I,drawingState(t){let e=I(t),{current:r,target:o}=mr(t),n=["preheating","ready","cooking","done","keeping_warm","press_start"].includes(e);return{kind:"sous_vide",available:t.appliance.available,running:n||Me(t),heating:e==="preheating",food:e==="cooking"||e==="done",waterC:bi(t,r),readout:r===null?null:ne(t.hass,r,1),targetReadout:e==="preheating"&&o!==null?ne(t.hass,o,1):null,error:$i(t)}},status:t=>st(t,I(t),"status.press_button_joule"),infoRows(t){let e=t.t,r=I(t),{current:o,target:n}=mr(t),a=[],i=ne(t.hass,o,1),s=ne(t.hass,n,1);if(we(t)||r==="preheating"||r==="ready"||r==="cooking"||r==="done"){a.push({label:e("info.water"),value:e("info.now_of_target",{now:i,target:s})});let l=be(t);if(r==="cooking"&&l){let c=Ee(l,t.now),d=l.end===null?null:e("info.ends",{time:he(t.hass,l.end)});a.push({label:e("info.time_left"),value:ee([Ye(c*1e3),d])??"\u2014"})}else r==="cooking"?a.push({label:e("info.time"),value:e("value.until_stopped")}):(r==="preheating"||r==="ready")&&a.push({label:e("info.cook_time"),value:to(t,Re(t,"cook_time"))});return r==="ready"&&a.push({label:e("info.next"),value:e("info.add_food")}),r==="done"&&a.push({label:e("info.next"),value:e("info.remove_food")}),a}return a.push({label:e("info.water"),value:i}),a.push({label:e("info.next_cook"),value:ee([s,to(t,Re(t,"cook_time"))])??"\u2014"}),r==="error"&&a.push({label:e("info.problem"),value:ze(t)}),a},display:()=>null,sections(t){let e=t.t,{current:r,target:o,unit:n}=mr(t),a=Me(t),i=we(t),s=Re(t,"cook_time"),l=D(t.hass,o,n,1),c=t.appliance.product,d=s?e("confirm.start_sous_vide",{name:c,temp:l,time:to(t,s)}):e("confirm.start_sous_vide_hold",{name:c,temp:l}),m=be(t),b=[W("current_temperature",e("control.water_temperature"),r===null?null:D(t.hass,r,n,1)),i?W("target",e("control.target"),D(t.hass,o,n,1)):null,i&&I(t)==="cooking"?m?{kind:"countdown",id:"time_left",label:e("control.time_left"),end:m.end,seconds:m.seconds,hint:m.end===null?e("hint.paused"):e("info.ends",{time:he(t.hass,m.end)})}:W("time_left",e("control.time_left"),e("value.until_stopped")):null],$=a?pr(t):null,v=$?cr(t):null,z=[ar(t,"target_temperature",e("control.target_temperature"),{step:.5,reasons:[$],link:v,hint:a?e("hint.changes_cook"):null}),ir(t,"cook_time",e("control.cook_time"),gi,{reasons:[$],link:v,zero:e("value.until_stopped"),hint:a?e("hint.changes_time_left"):null}),it(t,"auto_start_timer",e("control.auto_start_timer"),{hint:e("hint.auto_start_timer")})];return lr([De("cook",e("section.cook"),[...b,...dr(t,d)]),De("settings",e(a?"section.this_cook":"section.next_cook"),z),ur(t)])},describe(t){let e=t.t,r=ro.drawingState(t),{current:o,target:n,unit:a}=mr(t),i=I(t),s=[e("describe.sous_vide",{product:t.appliance.product})];r.error==="tipped"&&s.push(e("describe.tipped")),r.error==="low_water"&&s.push(e("describe.low_water")),o!==null&&s.push(r.running?e("describe.water_target",{now:D(t.hass,o,a,1),target:D(t.hass,n,a,1)}):e("describe.water",{now:D(t.hass,o,a,1)})),s.push(`${st(t,i,"status.press_button_joule").text}.`);let l=be(t);return i==="cooking"&&l&&s.push(e("describe.time_left",{time:nr(t.hass,e,Ee(l,t.now))})),r.food&&s.push(e("describe.food_bag")),s.join(" ")}};function ct(t){return t.kind==="oven"?eo:ro}var tt={modes:new Map,presets:[]};function oo(t,e){return{modes:new Map((t??[]).map(r=>[r.id,r])),presets:e??[]}}function pt(t,e,r,o,n=tt){let a=(i,...s)=>{let l=t.entities?.[i];if(l){if(!s.length)return Object.values(l)[0];for(let c of s)if(l[c])return l[c]}};return{appliance:t,hass:e,t:r,now:o,modes:n.modes,presets:n.presets,entityId:a,state(i,...s){let l=a(i,...s);return l?e.states[l]:void 0}}}var ae=P`
  :host {
    --bc-text: var(--primary-text-color, #1f2328);
    --bc-muted: var(--secondary-text-color, #6b7178);
    /* Secondary text on an inset or a control's fill, where the plain muted color falls a little
       short of 4.5:1: a quarter of the way to the text color. */
    --bc-muted-inset: color-mix(in srgb, var(--bc-muted) 75%, var(--bc-text));
    --bc-card-bg: var(--ha-card-background, var(--card-background-color, #ffffff));
    --bc-page-bg: var(--primary-background-color, #f4f5f6);
    --bc-radius: var(--ha-card-border-radius, 12px);
    --bc-border-width: var(--ha-card-border-width, 1px);
    --bc-border: var(--ha-card-border-color, var(--divider-color, rgba(0, 0, 0, 0.12)));
    --bc-divider: var(--divider-color, rgba(0, 0, 0, 0.12));
    --bc-accent: var(--primary-color, #03a9f4);
    --bc-on-accent: var(--text-primary-color, #ffffff);
    --bc-error: var(--error-color, #db4437);
    /* Tone text is the tone mixed toward the ink: darker on light themes, lighter on dark ones,
       so a status reads clearly on its tinted pill either way. */
    --bc-ink: #000000;
    --bc-tone-strength: 66%;
    --bc-tone-neutral: var(--primary-text-color, #1f2328);
    --bc-tone-accent: var(--primary-color, #03a9f4);
    --bc-tone-warm: #e8590c;
    --bc-tone-amber: #e69500;
    --bc-tone-green: var(--success-color, #43a047);
    --bc-tone-red: var(--error-color, #db4437);
    --bc-tone-gray: var(--secondary-text-color, #6b7178);
    /* Warning and error text, mixed toward the ink like the tones so it reaches 4.5:1 on the card;
       borders and fills keep the raw colors. */
    --bc-warning-text: color-mix(in srgb, var(--bc-tone-amber) var(--bc-tone-strength), var(--bc-ink));
    --bc-error-text: color-mix(in srgb, var(--bc-error) 80%, var(--bc-ink));
    /* Insets such as the info panel, and the fill of buttons and segmented controls. */
    --bc-inset-bg: rgba(0, 0, 0, 0.04);
    --bc-inset-edge: rgba(0, 0, 0, 0.08);
    --bc-control-bg: rgba(0, 0, 0, 0.06);
    --bc-control-hover: rgba(0, 0, 0, 0.1);
    --bc-lift: 0 8px 24px rgba(0, 0, 0, 0.12);
    /* A switch's off track, at 3:1 against the card so an off switch still reads as one. */
    --bc-switch-off: color-mix(in srgb, var(--bc-text) 50%, transparent);
    /* Fills behind white text (chosen segments, primary and danger buttons), darkened from the
       theme's colors so the text reaches 4.5:1. */
    --bc-accent-fill: color-mix(in srgb, var(--bc-accent) 68%, #000000);
    --bc-danger-fill: color-mix(in srgb, var(--bc-error) 88%, #000000);
  }
  :host([dark]) {
    --bc-ink: #ffffff;
    --bc-tone-strength: 76%;
    --bc-tone-warm: #ff8a4c;
    --bc-tone-amber: #ffb83d;
    --bc-inset-bg: rgba(8, 10, 12, 0.5);
    --bc-inset-edge: rgba(255, 255, 255, 0.08);
    --bc-control-bg: rgba(255, 255, 255, 0.09);
    --bc-control-hover: rgba(255, 255, 255, 0.14);
    --bc-lift: 0 8px 28px rgba(0, 0, 0, 0.45);
    --bc-switch-off: color-mix(in srgb, var(--bc-text) 40%, transparent);
  }
`,hr=P`
  [data-tone="neutral"] {
    --tone: var(--bc-tone-neutral);
  }
  [data-tone="accent"] {
    --tone: var(--bc-tone-accent);
  }
  [data-tone="warm"] {
    --tone: var(--bc-tone-warm);
  }
  [data-tone="amber"] {
    --tone: var(--bc-tone-amber);
  }
  /* Amber is so light that its text needs more ink on a light theme to reach 4.5:1. */
  :host(:not([dark])) [data-tone="amber"] {
    --bc-tone-strength: 60%;
  }
  [data-tone="green"] {
    --tone: var(--bc-tone-green);
  }
  [data-tone="red"] {
    --tone: var(--bc-tone-red);
  }
  [data-tone="gray"] {
    --tone: var(--bc-tone-gray);
  }
`,ie=P`
  .bc-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    min-height: 40px;
    padding: 8px 16px;
    border: none;
    border-radius: 999px;
    background: var(--bc-control-bg);
    color: var(--bc-text);
    font: inherit;
    font-size: 14px;
    font-weight: 600;
    line-height: 1.2;
    text-decoration: none;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
    transition: background-color 0.15s, opacity 0.15s;
  }
  .bc-button:hover {
    background: var(--bc-control-hover);
  }
  .bc-button.primary {
    background: var(--bc-accent-fill, var(--bc-accent));
    color: var(--bc-on-accent);
  }
  .bc-button.danger {
    background: var(--bc-danger-fill, var(--bc-error));
    color: #ffffff;
  }
  .bc-button:is(.primary, .danger):hover:not(:disabled, [aria-disabled="true"]) {
    opacity: 0.9;
  }
  .bc-button:disabled,
  .bc-button[aria-disabled="true"] {
    opacity: 0.45;
    cursor: default;
  }
  /* A button that can't be pressed doesn't answer the pointer. */
  .bc-button:not(.primary, .danger):is(:disabled, [aria-disabled="true"]):hover {
    background: var(--bc-control-bg);
  }
  .bc-button:focus-visible {
    outline: 2px solid var(--bc-accent);
    outline-offset: 2px;
  }
  /* Touch laptops report a mouse as their main pointer, so any finger gets the bigger target. */
  @media (any-pointer: coarse) {
    .bc-button {
      min-height: 44px;
    }
  }
`;function se(t,e){t.toggleAttribute("dark",e?.themes?.darkMode===!0)}var gr={ATTRIBUTE:1,CHILD:2,PROPERTY:3,BOOLEAN_ATTRIBUTE:4,EVENT:5,ELEMENT:6},ut=t=>(...e)=>({_$litDirective$:t,values:e}),dt=class{constructor(e){}get _$AU(){return this._$AM._$AU}_$AT(e,r,o){this._$Ct=e,this._$AM=r,this._$Ci=o}_$AS(e,r){return this.update(e,r)}update(e,r){return this.render(...r)}};var{I:vi}=No,bn=t=>t;var $n=()=>document.createComment(""),ft=(t,e,r)=>{let o=t._$AA.parentNode,n=e===void 0?t._$AB:e._$AA;if(r===void 0){let a=o.insertBefore($n(),n),i=o.insertBefore($n(),n);r=new vi(a,i,t,t.options)}else{let a=r._$AB.nextSibling,i=r._$AM,s=i!==t;if(s){let l;r._$AQ?.(t),r._$AM=t,r._$AP!==void 0&&(l=t._$AU)!==i._$AU&&r._$AP(l)}if(a!==n||s){let l=r._$AA;for(;l!==a;){let c=bn(l).nextSibling;bn(o).insertBefore(l,n),l=c}}}return r},Oe=(t,e,r=t)=>(t._$AI(e,r),t),yi={},vn=(t,e=yi)=>t._$AH=e,yn=t=>t._$AH,br=t=>{t._$AR(),t._$AA.remove()};var _n=(t,e,r)=>{let o=new Map;for(let n=e;n<=r;n++)o.set(t[n],n);return o},Be=ut(class extends dt{constructor(t){if(super(t),t.type!==gr.CHILD)throw Error("repeat() can only be used in text expressions")}dt(t,e,r){let o;r===void 0?r=e:e!==void 0&&(o=e);let n=[],a=[],i=0;for(let s of t)n[i]=o?o(s,i):i,a[i]=r(s,i),i++;return{values:a,keys:n}}render(t,e,r){return this.dt(t,e,r).values}update(t,[e,r,o]){let n=yn(t),{values:a,keys:i}=this.dt(e,r,o);if(!Array.isArray(n))return this.ut=i,a;let s=this.ut??=[],l=[],c,d,m=0,b=n.length-1,$=0,v=a.length-1;for(;m<=b&&$<=v;)if(n[m]===null)m++;else if(n[b]===null)b--;else if(s[m]===i[$])l[$]=Oe(n[m],a[$]),m++,$++;else if(s[b]===i[v])l[v]=Oe(n[b],a[v]),b--,v--;else if(s[m]===i[v])l[v]=Oe(n[m],a[v]),ft(t,l[v+1],n[m]),m++,v--;else if(s[b]===i[$])l[$]=Oe(n[b],a[$]),ft(t,n[m],n[b]),b--,$++;else if(c===void 0&&(c=_n(i,$,v),d=_n(s,m,b)),c.has(s[m]))if(c.has(s[b])){let z=d.get(i[$]),T=z!==void 0?n[z]:null;if(T===null){let G=ft(t,n[m]);Oe(G,a[$]),l[$]=G}else l[$]=Oe(T,a[$]),ft(t,n[m],T),n[z]=null;$++}else br(n[b]),b--;else br(n[m]),m++;for(;$<=v;){let z=ft(t,l[v+1]);Oe(z,a[$]),l[$++]=z}for(;m<=b;){let z=n[m++];z!==null&&br(z)}return this.ut=i,vn(t,l),pe}});async function kn(t,e,r){let o={entity_id:e.entity_id};switch(e.type){case"number":await t.callService("number","set_value",{value:Number(r)},o);return;case"select":await t.callService("select","select_option",{option:String(r)},o);return;case"switch":await t.callService("switch",r?"turn_on":"turn_off",{},o);return;case"switch_on":await t.callService("switch","turn_on",{},o);return;case"switch_off":await t.callService("switch","turn_off",{},o);return;case"button":await t.callService("button","press",{},o);return}}var mt=class{constructor(e,r){this.host=e;this.selector=r;this.observed=null;e.addController(this)}hostConnected(){this.hostUpdated()}hostUpdated(){let e=this.host.renderRoot?.querySelector(this.selector)??null;e!==this.observed&&(this.observer?.disconnect(),this.observed=e,!(!e||typeof ResizeObserver!="function")&&(this.observer??=new ResizeObserver(r=>this.measured(r)),this.observer.observe(e)))}hostDisconnected(){this.observer?.disconnect(),this.observed=null}measured(e){let r=Math.round(e[e.length-1]?.contentRect.height??0);r<=0||r===this.height||(this.height=r,this.host.requestUpdate())}};function $r(t){return t?.text?h`<span class="pill" data-tone=${t.tone}>${t.text}</span>`:f}function vr(t,e=!1){return t?.text?h`<div class="lcd ${e?"dim":""}">
    <span class="digits">${t.text}</span>
    ${t.caption?h`<span class="caption">${t.caption}</span>`:f}
  </div>`:f}function wn(t){return t.length?h`<dl class="info">
    ${t.map(e=>h`<div class="row"><dt>${e.label}</dt><dd>${e.value}</dd></div>`)}
  </dl>`:f}function Tt(t){let e=t.tone??"primary";return h`<div class="confirm ${e}" role="group" aria-label=${t.text}>
    <span class="question">${t.text}</span>
    <span class="actions">
      <button type="button" class="bc-button" ?disabled=${t.busy} @click=${t.onCancel}>
        ${t.cancel}
      </button>
      <button type="button" class="bc-button ${e}" ?disabled=${t.busy} @click=${t.onConfirm}>
        ${t.confirm}
      </button>
    </span>
  </div>`}var je=P`
  .pill {
    flex: none;
    max-width: 60%;
    overflow: hidden;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    line-height: 18px;
    white-space: nowrap;
    text-overflow: ellipsis;
    /* Fallbacks for browsers without color-mix. */
    color: var(--tone);
    background: rgba(127, 127, 127, 0.14);
    color: color-mix(in srgb, var(--tone) var(--bc-tone-strength), var(--bc-ink));
    background: color-mix(in srgb, var(--tone) 15%, transparent);
  }
  .pill[data-tone="neutral"] {
    color: var(--bc-text);
    background: color-mix(in srgb, var(--bc-text) 8%, transparent);
  }
  .pill[data-tone="gray"] {
    color: var(--bc-muted);
    background: color-mix(in srgb, var(--bc-muted) 14%, transparent);
  }

  /* The display is a physical part of the appliance, so it looks the same in both themes. */
  .lcd {
    display: inline-flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-width: 7.5em;
    padding: 6px 14px 5px;
    box-sizing: border-box;
    border-radius: 8px;
    /* Dark glass with a faint glare across its upper half. */
    background:
      linear-gradient(168deg, rgba(255, 255, 255, 0.07) 0%, rgba(255, 255, 255, 0.015) 45%, transparent 46%),
      linear-gradient(180deg, #15171b 0%, #0a0b0d 100%);
    box-shadow:
      inset 0 0 0 1px rgba(255, 255, 255, 0.07),
      inset 0 2px 6px rgba(0, 0, 0, 0.8),
      0 1px 2px rgba(0, 0, 0, 0.25);
    line-height: 1;
  }
  /* The theme's sans with even-width digits: a monospace font's slashed zero reads as code. */
  .lcd .digits {
    font-family: inherit;
    font-size: 26px;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.03em;
    color: #ffa53a;
    text-shadow: 0 0 10px rgba(255, 140, 30, 0.45);
    white-space: nowrap;
  }
  .lcd.dim .digits {
    color: #6b6e73;
    text-shadow: none;
  }
  .lcd .caption {
    margin-top: 4px;
    font-size: 11px;
    color: #9a9da2;
    white-space: nowrap;
  }

  .info {
    display: grid;
    gap: 3px;
    margin: 0;
    padding: 7px 12px;
    border-radius: 12px;
    background: var(--bc-inset-bg);
    box-shadow: inset 0 0 0 1px var(--bc-inset-edge);
    font-size: 13.5px;
    line-height: 1.35;
  }
  .info .row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
    min-width: 0;
  }
  .info dt {
    flex: none;
    max-width: 50%;
    overflow: hidden;
    color: var(--bc-muted-inset, var(--bc-muted));
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  /* A long value (setpoints in German, say) wraps rather than losing its end. */
  .info dd {
    margin: 0;
    min-width: 0;
    font-weight: 500;
    text-align: end;
    overflow-wrap: anywhere;
    text-wrap: balance;
  }

  .confirm {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    padding: 8px 10px 8px 14px;
    border-radius: 12px;
    border: 1px solid var(--bc-accent);
    background: var(--bc-inset-bg);
  }
  .confirm.danger {
    border-color: var(--bc-error);
  }
  .confirm .question {
    flex: 1 1 14em;
    font-size: 14px;
  }
  .confirm .actions {
    display: flex;
    gap: 8px;
    margin-inline-start: auto;
  }
  /* On the bar's inset the neutral fill all but disappears in the dark theme; an edge keeps the
     safe choice looking like the button it is. */
  .confirm .bc-button:not(.primary, .danger) {
    background: var(--bc-control-hover);
    box-shadow: inset 0 0 0 1px var(--bc-inset-edge);
  }

  /* A drawing stands at the bottom of its stage and fits it: tall refrigerators fill the
     height, wide ranges the width. The drawing's svg has a viewBox in true proportions. */
  .stage {
    position: relative;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    box-sizing: border-box;
  }
  .stage .drawing {
    display: flex;
    align-items: flex-end;
    justify-content: center;
    width: 100%;
    height: 100%;
  }
  .stage .drawing > svg {
    display: block;
    width: 100%;
    height: auto;
    max-height: 100%;
  }
`;var rt=class extends dt{constructor(e){if(super(e),this.it=f,e.type!==gr.CHILD)throw Error(this.constructor.directiveName+"() can only be used in child bindings")}render(e){if(e===f||e==null)return this._t=void 0,this.it=e;if(e===pe)return e;if(typeof e!="string")throw Error(this.constructor.directiveName+"() called with a non-string value");if(e===this.it)return this._t;this.it=e;let r=[e];return r.raw=r,this._t={_$litType$:this.constructor.resultType,strings:r,values:[]}}};rt.directiveName="unsafeHTML",rt.resultType=1;var kc=ut(rt);var Ct=class extends rt{};Ct.directiveName="unsafeSVG",Ct.resultType=2;var yr=ut(Ct);function zn(t){return t.map(([e,r,o])=>p`<stop offset=${e} stop-color=${r} stop-opacity=${o===void 0?1:o}></stop>`)}function _(t,e,r=[0,0],o=[1,0],n="objectBoundingBox"){return p`<linearGradient id=${t} x1=${r[0]} y1=${r[1]} x2=${o[0]} y2=${o[1]} gradientUnits=${n}>${zn(e)}</linearGradient>`}function le(t,e,r=[.5,.5],o=.5,n=null,a="objectBoundingBox"){let[i,s]=n??r;return p`<radialGradient id=${t} cx=${r[0]} cy=${r[1]} r=${o} fx=${i} fy=${s} gradientUnits=${a}>${zn(e)}</radialGradient>`}function de(t,e,r=[0,0],o=[1,0],n=1,a="objectBoundingBox"){return _(t,e.map(([i,s])=>[i,n===1?s:kr(s,n)]),r,o,a)}function Sn(t,e,r="0.0025 0.33"){let o=(.12*e).toFixed(3),n=(.5-.06*e).toFixed(3);return p`<filter id=${t} x="0" y="0" width="1" height="1" color-interpolation-filters="sRGB">
    <feTurbulence type="fractalNoise" baseFrequency=${r} numOctaves="2" seed="11" result="noise"></feTurbulence>
    <feColorMatrix in="noise" type="matrix" values="0.5 0.5 0 0 0  0.5 0.5 0 0 0  0.5 0.5 0 0 0  0 0 0 0 1" result="gray"></feColorMatrix>
    <feComponentTransfer in="gray" result="grain">
      <feFuncR type="linear" slope=${o} intercept=${n}></feFuncR>
      <feFuncG type="linear" slope=${o} intercept=${n}></feFuncG>
      <feFuncB type="linear" slope=${o} intercept=${n}></feFuncB>
    </feComponentTransfer>
    <feBlend in="grain" in2="SourceGraphic" mode="overlay" result="brushed"></feBlend>
    <feComposite in="brushed" in2="SourceAlpha" operator="in"></feComposite>
  </filter>`}function An(t,e){return p`<filter id=${t} primitiveUnits="objectBoundingBox" x="-5%" y="-5%" width="110%" height="110%">
    <feGaussianBlur stdDeviation=${e}></feGaussianBlur>
  </filter>`}function _i(t,e){let r=(e%360+360)%360/360*t.length,o=Math.floor(r);return $e(t[o%t.length],t[(o+1)%t.length],r-o)}function xn(t,e,r,o){let n=o*Math.PI/180;return`${u(t+r*Math.cos(n))},${u(e-r*Math.sin(n))}`}function Tn(t,e,r,o,n=72){let a=360/n;return Array.from({length:n},(i,s)=>{let l=s*a-.8,c=(s+1)*a;return p`<path d=${`M${u(t)},${u(e)}L${xn(t,e,r,l)}A${r},${r} 0 0 0 ${xn(t,e,r,c)}Z`}
      fill=${_i(o,(s+.5)*a)}></path>`})}function _r(t,e,r,o,n,a){let i=a==="dark"?.55:.28;return p`
    ${le(`${t}-floor`,[[0,"#000000",i],[.6,"#000000",i*.35],[1,"#000000",0]])}
    <ellipse cx=${e} cy=${r} rx=${o} ry=${n} fill=${`url(#${t}-floor)`}></ellipse>
  `}function ht(t,e){return p`<filter id=${t} x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation=${e}></feGaussianBlur></filter>`}function kr(t,e){return e<=1?$e("#000000",t,Math.max(0,e)):$e(t,"#ffffff",Math.min(1,e-1))}function u(t){return Math.round(t*100)/100}function $e(t,e,r){let o=m=>[1,3,5].map(b=>Number.parseInt(m.slice(b,b+2),16)),[n,a,i]=o(t),[s,l,c]=o(e),d=(m,b)=>Math.round(m+(b-m)*r).toString(16).padStart(2,"0");return`#${d(n,s)}${d(a,l)}${d(i,c)}`}function w(t,e,r,o,n){let a=Math.min(n,r/2,o/2);return`M${t+a},${e}H${t+r-a}A${a},${a} 0 0 1 ${t+r},${e+a}V${e+o-a}A${a},${a} 0 0 1 ${t+r-a},${e+o}H${t+a}A${a},${a} 0 0 1 ${t},${e+o-a}V${e+a}A${a},${a} 0 0 1 ${t+a},${e}Z`}function Cn(t,e,r=12,o=.045){return e?r*t/e:t*o}var M={width:544,top:8.3,topCorner:20,bottomCorner:10,doorBottom:270,baseTop:272,bottom:297.5,floor:317,gap:{left:450.5,right:453.5}},q={x:53,y:57.5,width:354.8,height:174.6},Ge={x:40.8,y:49,width:377.2,height:193.5},j={bar:{x:24.5,y:2,width:408.5,height:18},brackets:[{x:26.6,width:22.7},{x:408.6,width:22.7}],bracketTop:0,bracketBottom:50},Mn={x:147,width:162,top:285.5,bottom:298.5},Pn=[{x:9,width:92},{x:443,width:95}],ve={x:453.5,lcd:{x:463,y:25,width:65,height:78},confirm:{cx:477.3,cy:133,r:11.5},start:{cx:516,cy:133,r:14},temp:{cx:496.1,cy:184.7,r:25},time:{cx:496.1,cy:254,r:25},buttons:[{cy:159.6,icon:"light"},{cy:203.4,icon:"fan"},{cy:219,icon:"more"},{cy:233,icon:"frozen"},{cy:276.5,icon:"favorite"}],buttonX:525.3,buttonR:4.7},Ne=[.221,.29,.454,.519,.687,.746,.901,.966],Rn=[[0,.58],[.003,.74],[.009,.86],[.013,.84],[.03,.815],[.18,.81],[.37,.83],[.55,.875],[.64,.895],[.735,.955],[.77,.98],[.81,1],[.828,1],[.834,1.04],[.837,.95],[.9,.98],[.96,1.02],[.988,1],[.995,.86],[1,.6]],En={brushed_stainless:{bright:"#e9ebeb",rise:[[0,.8],[.2,.8],[.35,.835],[.54,.89],[.73,.935],[.885,.975],[.94,.995],[1,1]],handle:[[0,"#4d4d4d"],[.08,"#656565"],[.14,"#3b3b3b"],[.2,"#646464"],[.27,"#d8d8d8"],[.36,"#f8f8f8"],[.45,"#fcfcfc"],[.55,"#e2e2e2"],[.63,"#a9a9a9"],[.7,"#727272"],[.76,"#505050"],[.82,"#777777"],[.88,"#bfbfbf"],[.94,"#e6e6e6"],[1,"#8a8a8a"]],bracket:[[0,"#8d8d8d"],[.03,"#545454"],[.1,"#4f4f4f"],[.6,"#4c4c4c"],[.88,"#464646"],[.93,"#757575"],[.96,"#898989"],[1,"#747474"]],bevelTop:[[0,"#c7c7c7"],[.14,"#747474"],[.24,"#4f4f4f"],[.86,"#535353"],[.93,"#2a2a2a"],[1,"#161616"]],bevelLeft:[[0,"#a7a7a7"],[.1,"#a7a7a7"],[.14,"#595959"],[.22,"#434343"],[.35,"#373737"],[.76,"#383838"],[.84,"#2f2f2f"],[.88,"#151315"],[1,"#151315"]],bevelRight:[[0,"#c8c8c8"],[.14,"#c9c9c9"],[.26,"#979797"],[.33,"#8d8d8d"],[.9,"#8d8d8d"],[1,"#3a3a3a"]],bevelBottom:[[0,"#dcdcdb"],[.08,"#f3f3f3"],[.2,"#eaeaea"],[.8,"#e7e7e7"],[.88,"#797979"],[.93,"#060607"],[1,"#060607"]],trayLip:"#585d61",tray:["#3b3e41","#484c50"],feet:[[0,"#292929"],[.15,"#242628"],[.35,"#3a3c3e"],[.8,"#3e4145"],[.92,"#2a2c2e"],[1,"#1e1e1e"]],dialCap:["#abaaad","#9c9c9c","#999898","#5f5f61","#6f7075","#b3b3ba","#e1e0e3","#f5f5f5","#f9f9f9","#faf9f9","#efeff0","#c2c1c5","#a1a0a3","#767779","#8e8e8c","#81817f","#939394","#bebdc1","#e1e0e3","#ececec","#f5f4f4","#f2f2f2","#dddbdd","#bab9bd"],dialRim:["#d8d6d7","#e4e3e3","#f4f4f4","#ffffff","#f6f6f6","#a2a2a5","#b6b4b9","#d1d0d4","#dcdade","#d0cdd2","#9e9ca0","#76777c","#727376","#9c9c9a","#d8d9d8","#fafafa","#f0f0f0","#cac9ca","#9e9c9a","#6b6b6a","#474747","#b6b5b4","#c6c4c4","#d0cece"],dialGroove:["#979797","#bdbdbd","#c2c2c2","#c2c2c2","#c3c3c3","#868686","#383838","#606060","#828282","#7b7a7a","#393939","#0c0d0d","#222121","#363636","#5d5d5d","#858686","#737373","#636363","#464646","#444444","#494949","#5f5f5f","#5f5f5f","#6c6c6c"],ink:"#38393a",button:["#f6f6f6","#9a9a9a"],grain:1},black_stainless:{bright:"#7d7d78",rise:[[0,.75],[.2,.73],[.35,.76],[.54,.83],[.73,.89],[.885,.95],[.94,.98],[1,1]],handle:[[0,"#3e3e3d"],[.08,"#363635"],[.14,"#131411"],[.2,"#4d4c4c"],[.27,"#adabac"],[.36,"#e0dfe1"],[.45,"#fdfdfd"],[.55,"#f0f0f0"],[.63,"#ababad"],[.7,"#7d7c7d"],[.76,"#4f4d4c"],[.82,"#252422"],[.88,"#13130a"],[.94,"#373836"],[1,"#525050"]],bracket:[[0,"#474445"],[.03,"#2a2829"],[.1,"#242223"],[.6,"#242222"],[.88,"#211f20"],[.93,"#353434"],[.96,"#444142"],[1,"#3a3839"]],bevelTop:[[0,"#787675"],[.14,"#373536"],[.24,"#2c2a2b"],[.86,"#2d2b2c"],[.93,"#1c1b1b"],[1,"#121212"]],bevelLeft:[[0,"#4f4d4e"],[.1,"#4f4d4e"],[.14,"#2f2d2e"],[.22,"#292728"],[.35,"#252324"],[.76,"#262324"],[.84,"#242122"],[.88,"#141214"],[1,"#141214"]],bevelRight:[[0,"#666462"],[.14,"#7c7a78"],[.26,"#585655"],[.33,"#3f3d3e"],[.9,"#3f3d3e"],[1,"#1f1e1e"]],bevelBottom:[[0,"#848480"],[.08,"#aaa7a5"],[.2,"#8f8d89"],[.8,"#8e8d88"],[.88,"#413f3f"],[.93,"#070707"],[1,"#070707"]],trayLip:"#c84a27",tray:["#892613","#963a1c"],feet:[[0,"#201f1f"],[.15,"#242628"],[.35,"#3a3c3e"],[.8,"#3e4145"],[.92,"#2a2c2e"],[1,"#1e1e1e"]],dialCap:["#555253","#484647","#454443","#21211c","#2d2c2b","#5f5d5e","#918e8f","#a9a7a9","#acacae","#aeacae","#a2a0a2","#6d6a6b","#4c4a4b","#2f2f2d","#3f3d3b","#353532","#40403f","#686566","#908d8f","#9f9d9e","#a7a6a8","#a4a2a3","#8b8788","#646161"],dialRim:["#848080","#989596","#c4c4c8","#f8f8fa","#e2e1e5","#545454","#605d5e","#7e7a7b","#8b8688","#7d787a","#484848","#303030","#2e2d2c","#474645","#848080","#adacae","#a09e9f","#726e6e","#484646","#272724","#111006","#5d5a59","#6e6a69","#7a7575"],dialGroove:["#413e3f","#565553","#5a5857","#5a5957","#5c5a59","#413f40","#272526","#383536","#3b3939","#393637","#272526","#191718","#1d1b1b","#232021","#302e2d","#3a3738","#353334","#2f2c2d","#262425","#262324","#282525","#312f30","#2d2b2c","#312f30"],ink:"#d9d9d6",button:["#9a9995","#3a3938"],grain:.7}},Ln=[[0,.42],[.15,.5],[.35,.47],[.42,.3],[.55,.36],[.72,.28],[.84,.08],[1,0]],no="#d24929";var A={x:9,y:13,width:440,height:234},ue={face:{top:247,bottom:270},edge:{top:270,bottom:291},scale:1.075,center:A.x+A.width/2,bracketBottom:341,bar:{top:324,bottom:341}},L=t=>u(ue.center+(t-ue.center)*ue.scale);function Hn(){let{width:t,top:e,bottom:r,topCorner:o,bottomCorner:n}=M;return`M0,${e+o}A${o},${o} 0 0 1 ${o},${e}H${t-o}A${o},${o} 0 0 1 ${t},${e+o}V${r-n}A${n},${n} 0 0 1 ${t-n},${r}H${n}A${n},${n} 0 0 1 0,${r-n}Z`}function Dn(t,e){let{width:r,top:o,doorBottom:n}=M,a=Ge;return p`
    <linearGradient id=${`${t}-metal`} gradientUnits="userSpaceOnUse" x1="0" y1="0" x2=${r} y2="0">
      ${Rn.map(([i,s])=>p`<stop offset=${i} stop-color=${kr(e.bright,s)}></stop>`)}
    </linearGradient>
    <linearGradient id=${`${t}-rise`} gradientUnits="userSpaceOnUse" x1="0" y1=${o} x2="0" y2=${n}>
      ${e.rise.map(([i,s])=>p`<stop offset=${i} stop-color="#000000" stop-opacity=${u(1-s)}></stop>`)}
    </linearGradient>
    <linearGradient id=${`${t}-handle-shadow`} gradientUnits="userSpaceOnUse" x1="0" y1="20" x2="0" y2="44">
      ${Ln.map(([i,s])=>p`<stop offset=${i} stop-color="#000000" stop-opacity=${s}></stop>`)}
    </linearGradient>
    ${Sn(`${t}-grain`,e.grain)}
    ${de(`${t}-bar`,e.handle,[0,0],[0,1])}
    ${de(`${t}-bracket`,e.bracket)}
    ${_(`${t}-bracket-v`,[[0,"#ffffff",.18],[.4,"#ffffff",0],[.85,"#000000",0],[1,"#000000",.25]],[0,0],[0,1])}
    ${_(`${t}-bar-end`,[[0,"#000000",.35],[.35,"#000000",0],[.65,"#000000",0],[1,"#000000",.35]])}
    ${de(`${t}-bevel-t`,e.bevelTop,[0,a.y],[0,q.y],1,"userSpaceOnUse")}
    ${de(`${t}-bevel-b`,e.bevelBottom,[0,a.y+a.height],[0,q.y+q.height],1,"userSpaceOnUse")}
    ${de(`${t}-bevel-l`,e.bevelLeft,[a.x,0],[q.x,0],1,"userSpaceOnUse")}
    ${de(`${t}-bevel-r`,e.bevelRight,[a.x+a.width,0],[q.x+q.width,0],1,"userSpaceOnUse")}
    ${_(`${t}-base-edge`,[[0,"#000000",0],[.25,"#000000",.05],[.55,"#000000",.32],[1,"#000000",.62]],[0,0],[0,1])}
    ${_(`${t}-tray`,[[0,e.trayLip],[.22,e.trayLip],[.27,kr(e.tray[0],.85)],[.4,e.tray[0]],[1,e.tray[1]]],[0,0],[0,1])}
    ${_(`${t}-tray-ends`,[[0,"#000000",.45],[.04,"#000000",.1],[.1,"#000000",0],[.9,"#000000",0],[.96,"#000000",.1],[1,"#000000",.4]])}
    ${de(`${t}-foot`,e.feet,[0,0],[0,1])}
    ${_(`${t}-foot-x`,[[0,"#000000",.3],[.08,"#000000",.05],[.7,"#ffffff",.03],[.86,"#000000",.1],[1,"#000000",.45]])}
    ${_(`${t}-door-face`,[[0,"#000000",.55],[.5,"#000000",.2],[1,"#000000",0]],[0,0],[0,1])}
    <clipPath id=${`${t}-shell`}><path d=${Hn()}></path></clipPath>
    <filter id=${`${t}-shadow-soft`} x="-5%" y="-40%" width="110%" height="180%">
      <feGaussianBlur stdDeviation="1.4"></feGaussianBlur>
    </filter>
  `}function On(t){let{width:e,top:r,doorBottom:o,bottom:n}=M;return p`
    <path d=${Hn()} fill=${`url(#${t}-metal)`} filter=${`url(#${t}-grain)`}></path>
    <g clip-path=${`url(#${t}-shell)`}>
      <rect x="0" y=${r} width=${e} height=${o-r} fill=${`url(#${t}-rise)`}></rect>
      <rect x="0" y=${n-3.5} width=${e} height="3.5" fill=${`url(#${t}-base-edge)`}></rect>
      <path d=${`M2,${r+M.topCorner} A${M.topCorner-2},${M.topCorner-2} 0 0 1 ${M.topCorner},${r+2}H${e-M.topCorner}`}
        fill="none" stroke="#ffffff" stroke-opacity="0.45" stroke-width="1.6"></path>
    </g>
  `}function Bn(){let{top:t,doorBottom:e,baseTop:r,bottom:o,gap:n}=M;return p`
    <rect x=${n.left} y=${t+.6} width=${n.right-n.left} height=${o-t-1.2} fill="#070707"></rect>
    <line x1=${n.left-.3} x2=${n.left-.3} y1=${t+2} y2=${e} stroke="#ffffff" stroke-opacity="0.35" stroke-width="0.5"></line>
    <line x1=${n.right+.3} x2=${n.right+.3} y1=${t+2} y2=${o-1} stroke="#ffffff" stroke-opacity="0.45" stroke-width="0.5"></line>
    <line x1=${n.right+1.1} x2=${n.right+1.1} y1=${t+2} y2=${o-1} stroke="#000000" stroke-opacity="0.1" stroke-width="0.9"></line>
    <rect x="0.4" y=${e} width=${n.left-.4} height=${r-e} fill="#0b0b0b"></rect>
    <line x1="1" x2=${n.left} y1=${e-.3} y2=${e-.3} stroke="#ffffff" stroke-opacity="0.25" stroke-width="0.5"></line>
    <line x1="1" x2=${n.left} y1=${r+.7} y2=${r+.7} stroke="#ffffff" stroke-opacity="0.5" stroke-width="0.8"></line>
  `}function jn(t){let e={x1:Ge.x,y1:Ge.y,x2:Ge.x+Ge.width,y2:Ge.y+Ge.height},r={x1:q.x,y1:q.y,x2:q.x+q.width,y2:q.y+q.height};return p`
    <clipPath id=${`${t}-frame`}><path d=${w(e.x1,e.y1,e.x2-e.x1,e.y2-e.y1,9)}></path></clipPath>
    <g clip-path=${`url(#${t}-frame)`}>
      <path d=${`M${e.x1},${e.y1}H${e.x2}L${r.x2},${r.y1}H${r.x1}Z`} fill=${`url(#${t}-bevel-t)`}></path>
      <path d=${`M${e.x1},${e.y2}H${e.x2}L${r.x2},${r.y2}H${r.x1}Z`} fill=${`url(#${t}-bevel-b)`}></path>
      <path d=${`M${e.x1},${e.y1}L${r.x1},${r.y1}V${r.y2}L${e.x1},${e.y2}Z`} fill=${`url(#${t}-bevel-l)`}></path>
      <path d=${`M${e.x2},${e.y1}L${r.x2},${r.y1}V${r.y2}L${e.x2},${e.y2}Z`} fill=${`url(#${t}-bevel-r)`}></path>
    </g>
  `}function Gn(t){let e=j.bar,r=e.height/2;return p`
    <path d=${w(e.x+3,20,e.width-6,24,6)} fill=${`url(#${t}-handle-shadow)`} filter=${`url(#${t}-shadow-soft)`}></path>
    ${j.brackets.map(({x:o,width:n})=>p`
        <path d=${`M${o},${j.bracketTop+3} Q${o},${j.bracketTop} ${o+3},${j.bracketTop} H${o+n-3} Q${o+n},${j.bracketTop} ${o+n},${j.bracketTop+3}
            V${j.bracketBottom-5} Q${o+n},${j.bracketBottom} ${o+n-5},${j.bracketBottom} H${o+5} Q${o},${j.bracketBottom} ${o},${j.bracketBottom-5} Z`}
          fill=${`url(#${t}-bracket)`}></path>
        <path d=${w(o,j.bracketTop,n,j.bracketBottom-j.bracketTop,4)} fill=${`url(#${t}-bracket-v)`}></path>
        <path d=${`M${o+3},${j.bracketBottom-.4} H${o+n-3}`} stroke="#000000" stroke-opacity="0.3" stroke-width="0.8"></path>
      `)}
    <path d=${w(e.x,e.y,e.width,e.height,r)} fill=${`url(#${t}-bar)`}></path>
    <path d=${w(e.x,e.y,e.width,e.height,r)} fill=${`url(#${t}-bar-end)`} opacity="0.6"></path>
    <path d=${w(e.x,e.y,e.width,e.height,r)} fill="none" stroke="#000000" stroke-opacity="0.22" stroke-width="0.5"></path>
  `}function Nn(t){let{x:e,width:r,top:o,bottom:n}=Mn;return p`
    <path d=${`M${e},${o+1.5} Q${e},${o} ${e+1.5},${o} H${e+r-1.5} Q${e+r},${o} ${e+r},${o+1.5}
        V${n-2} Q${e+r},${n} ${e+r-2},${n} H${e+2} Q${e},${n} ${e},${n-2} Z`}
      fill=${`url(#${t}-tray)`}></path>
    <rect x=${e} y=${o} width=${r} height=${n-o} rx="2" fill=${`url(#${t}-tray-ends)`}></rect>
    <line x1=${e+2} x2=${e+r-2} y1=${o+.4} y2=${o+.4} stroke="#ffffff" stroke-opacity="0.22" stroke-width="0.5"></line>
  `}function Vn(t){let e=M.bottom-3,r=M.floor;return p`${Pn.map(({x:o,width:n})=>{let a=`M${o},${e} H${o+n} L${o+n-3},${r-3} Q${o+n-3.4},${r} ${o+n-6.5},${r}
      H${o+6.5} Q${o+3.4},${r} ${o+3},${r-3} Z`;return p`<path d=${a} fill=${`url(#${t}-foot)`}></path><path d=${a} fill=${`url(#${t}-foot-x)`}></path>`})}`}function In(t){let e=A.x,r=A.x+A.width,{face:o,edge:n,bar:a}=ue,i=9,s=j.brackets.map(({x:l,width:c})=>({x:L(l),width:c*ue.scale}));return p`
    <g class="open-door">
      <path d=${`M${e-3},${o.top} H${r+3} L${L(M.gap.left)+2},${o.bottom} H${L(0)-2} Z`} fill=${`url(#${t}-metal)`}></path>
      <path d=${`M${e-3},${o.top} H${r+3} L${L(M.gap.left)+2},${o.bottom} H${L(0)-2} Z`} fill="#000000" opacity="0.18"></path>
      <path d=${`M${e+i},${o.top+2.2} H${r-i} L${L(M.gap.left)-i*1.5},${o.bottom-3.4} H${L(0)+i*1.5} Z`}
        fill="#17191b"></path>
      <path d=${`M${e+i},${o.top+2.2} H${r-i} L${L(M.gap.left)-i*1.5},${o.bottom-3.4} H${L(0)+i*1.5} Z`}
        fill=${`url(#${t}-door-face)`}></path>
      <path d=${`M${e+70},${o.top+4} H${e+190} L${e+170},${o.bottom-5} H${e+40} Z`} fill="#ffffff" opacity="0.05"></path>
      <g fill="#d24929" opacity="0.8">
        ${[0,1,2,3].map(l=>p`<rect x=${r-46+l*6.5} y=${o.top+9+l%2*.6} width="2.2" height="1.2" rx="0.4"></rect>`)}
      </g>
      <path d=${`M${L(0)-2},${n.top} H${L(M.gap.left)+2} V${n.bottom-3} Q${L(M.gap.left)+2},${n.bottom} ${L(M.gap.left)-1},${n.bottom}
          H${L(0)+1} Q${L(0)-2},${n.bottom} ${L(0)-2},${n.bottom-3} Z`}
        fill=${`url(#${t}-metal)`} filter=${`url(#${t}-grain)`}></path>
      <line x1=${L(0)} x2=${L(M.gap.left)} y1=${n.top+.6} y2=${n.top+.6} stroke="#ffffff" stroke-opacity="0.7" stroke-width="1.1"></line>
      <rect x=${L(0)-2} y=${n.bottom-4} width=${L(M.gap.left)-L(0)+4} height="4" fill="#000000" opacity="0.18"></rect>
      ${s.map(({x:l,width:c})=>p`
          <path d=${`M${l},${n.bottom} H${l+c} V${ue.bracketBottom-5} Q${l+c},${ue.bracketBottom} ${l+c-5},${ue.bracketBottom}
              H${l+5} Q${l},${ue.bracketBottom} ${l},${ue.bracketBottom-5} Z`} fill=${`url(#${t}-metal)`}></path>
          <path d=${w(l,n.bottom,c,ue.bracketBottom-n.bottom,5)} fill=${`url(#${t}-bracket)`} opacity="0.35"></path>
          <rect x=${l} y=${n.bottom} width=${c} height="5" fill="#000000" opacity="0.3"></rect>
        `)}
      <path d=${w(s[0].x-2,a.top,s[1].x+s[1].width-s[0].x+4,a.bottom-a.top,(a.bottom-a.top)/2)}
        fill=${`url(#${t}-bar)`}></path>
      <path d=${w(s[0].x-2,a.top,s[1].x+s[1].width-s[0].x+4,a.bottom-a.top,(a.bottom-a.top)/2)}
        fill="none" stroke="#000000" stroke-opacity="0.22" stroke-width="0.5"></path>
    </g>
  `}function Fn(){return p`
    <path d=${w(A.x,A.y,A.width,A.height,6)} fill="none" stroke="#000000" stroke-opacity="0.55" stroke-width="1.2"></path>
    <path d=${w(A.x-1.2,A.y-1.2,A.width+2.4,A.height+2.4,7)} fill="none" stroke="#ffffff" stroke-opacity="0.4" stroke-width="0.6"></path>
  `}var x=q,Se={x:272,y:150},ki=.282;function bt(t){return 1/(1+ki*t)}function k(t,e,r){let o=bt(r);return[u(Se.x+(t-Se.x)*o),u(Se.y+(e-Se.y)*o)]}var gt=t=>t.map(([e,r])=>`${e},${r}`).join(" "),y={x1:A.x,y1:A.y,x2:A.x+A.width,y2:A.y+A.height},S=(()=>{let[t,e]=k(y.x1,y.y1,1),[r,o]=k(y.x2,y.y2,1);return{x1:t,y1:e,x2:r,y2:o}})(),F=(y.x1+y.x2)/2;function ao(t){let e=Math.max(1,Math.min(8,Math.round(t)))-1;return x.y+Ne[e]*x.height}function wr(t){switch(t){case"top":return{top:[0,1,2],bottom:[],heat:1};case"bottom":return{top:[],bottom:[0,1,2],heat:1};case"outer_top":return{top:[0,2],bottom:[],heat:1};case"middle_top":return{top:[1],bottom:[],heat:1};case"top_bottom":return{top:[0,1,2],bottom:[0,1,2],heat:1};case"bottom_low":return{top:[],bottom:[0,1,2],heat:.45};case"low":return{top:[0,1,2],bottom:[0,1,2],heat:.4};default:return{top:[],bottom:[],heat:0}}}function io(t){let e=wr(t.elements);return e.top.length||e.bottom.length?"heat":t.light?"lamp":"off"}var wi={off:{back:[[0,"#1b1c1e"],[.5,"#151617"],[1,"#131415"]],left:["#232527","#17181a"],right:["#111213","#18191b"],ceiling:["#1c1d1f","#161718"],floor:["#26282a","#1a1b1d"]},lamp:{back:[[0,"#4a3f39"],[.12,"#3a302a"],[.3,"#2a221e"],[.55,"#1d1815"],[1,"#141110"]],left:["#6a5a50","#2e2620"],right:["#141110","#1e1915"],ceiling:["#332a24","#211b17"],floor:["#3e322a","#211b16"]},heat:{back:[[0,"#998c8a"],[.08,"#928380"],[.17,"#79625b"],[.25,"#604640"],[.33,"#4d332d"],[.42,"#412721"],[.5,"#442821"],[.58,"#3a2119"],[.67,"#2e1a15"],[.75,"#291611"],[1,"#271308"]],left:["#b4a6a2","#8a7670"],right:["#2a150c","#3b1d12"],ceiling:["#6a3e2c","#43231a"],floor:["#9a4f32","#5e3022"]}};function Un(t,e){let r=wi[io(e)],o=wr(e.elements);return p`
    <linearGradient id=${`${t}-cav-back`} gradientUnits="userSpaceOnUse" x1=${S.x1} y1="0" x2=${S.x2} y2="0">
      ${r.back.map(([n,a])=>p`<stop offset=${n} stop-color=${a}></stop>`)}
    </linearGradient>
    ${_(`${t}-cav-left`,[[0,r.left[0]],[1,r.left[1]]])}
    ${_(`${t}-cav-right`,[[0,r.right[1]],[1,r.right[0]]])}
    ${_(`${t}-cav-ceiling`,[[0,r.ceiling[0]],[1,r.ceiling[1]]],[0,0],[0,1])}
    ${_(`${t}-cav-floor`,[[0,r.floor[1]],[1,r.floor[0]]],[0,0],[0,1])}
    <linearGradient id=${`${t}-cav-low`} gradientUnits="userSpaceOnUse" x1="0" y1="100" x2="0" y2=${S.y2}>
      <stop offset="0" stop-color="#4a2219" stop-opacity="0"></stop>
      <stop offset="0.55" stop-color="#4f281f" stop-opacity="0.55"></stop>
      <stop offset="1" stop-color="#5a2c22" stop-opacity="0.75"></stop>
    </linearGradient>
    <linearGradient id=${`${t}-heat-top`} gradientUnits="userSpaceOnUse" x1="0" y1=${y.y1} x2="0" y2=${y.y1+95}>
      <stop offset="0" stop-color="#ff8a3d" stop-opacity=${u(.7*o.heat)}></stop>
      <stop offset="0.35" stop-color="#ff6a2a" stop-opacity=${u(.2*o.heat)}></stop>
      <stop offset="0.5" stop-color="#e2541f" stop-opacity=${u(.08*o.heat)}></stop>
      <stop offset="0.65" stop-color="#e2541f" stop-opacity="0"></stop>
    </linearGradient>
    <linearGradient id=${`${t}-heat-bottom`} gradientUnits="userSpaceOnUse" x1="0" y1=${y.y2} x2="0" y2=${y.y2-70}>
      <stop offset="0" stop-color="#ff9a5a" stop-opacity=${u(.95*o.heat)}></stop>
      <stop offset="0.12" stop-color="#e5763f" stop-opacity=${u(.8*o.heat)}></stop>
      <stop offset="0.35" stop-color="#b8502c" stop-opacity=${u(.42*o.heat)}></stop>
      <stop offset="1" stop-color="#8a3a22" stop-opacity="0"></stop>
    </linearGradient>
    <radialGradient id=${`${t}-lamp-light`} gradientUnits="userSpaceOnUse" cx=${y.x1+10} cy=${y.y1+40} r="240">
      <stop offset="0" stop-color="#fff1dc" stop-opacity="0.5"></stop>
      <stop offset="0.35" stop-color="#ffd9a8" stop-opacity="0.16"></stop>
      <stop offset="1" stop-color="#ffd9a8" stop-opacity="0"></stop>
    </radialGradient>
    ${_(`${t}-tube`,[[0,"#5d6266"],[.3,"#c9cdd0"],[.45,"#f1f2f3"],[.65,"#9ca1a5"],[1,"#43474b"]],[0,0],[0,1])}
    ${_(`${t}-tube-hot`,[[0,"#ff5a14"],[.35,"#ffc27a"],[.5,"#fff1d6"],[.65,"#ffb35a"],[1,"#ff4a10"]],[0,0],[0,1])}
    ${_(`${t}-wire`,[[0,"#9da1a4"],[.35,"#f4f1ea"],[.6,"#c8c3ba"],[1,"#55585b"]],[0,0],[0,1])}
    ${ht(`${t}-halo`,2.4)}
    ${ht(`${t}-haze`,6)}
    <clipPath id=${`${t}-window`}><rect x=${x.x} y=${x.y} width=${x.width} height=${x.height} rx="4"></rect></clipPath>
    <clipPath id=${`${t}-opening`}><rect x=${A.x} y=${A.y} width=${A.width} height=${A.height} rx="6"></rect></clipPath>
  `}function xi(t,e,r,o){let[n,a]=k(330,128,1),i=34,s=r==="off"?"#0f1011":r==="lamp"?"#1a1411":"#2a1610",l=e.fan==="super"?.5:1.8,c=[0,60,120,180,240,300].map(d=>p`<path d=${`M${n},${a} q 5,-12 2,-${i-6} q -9,5 -8,${i-7} z`} fill=${$e(s,"#000000",.25)}
      opacity="0.45" transform=${`rotate(${d} ${n} ${a})`}></path>`);return p`
    <g opacity=${r==="off"?.5:.3}>
      <circle cx=${n} cy=${a} r=${i} fill=${s}></circle>
      ${e.fan!=="off"&&o?p`<g class=${`${t}-spin`} style=${`--${t}-spin:${l}s; transform-origin:${n}px ${a}px`}>${c}</g>`:p`<g>${c}</g>`}
      <g fill="none" stroke="#ffffff" stroke-opacity="0.08" stroke-width="0.8">
        ${[i-3,i-10,i-17,i-24].map(d=>p`<circle cx=${n} cy=${a} r=${d}></circle>`)}
      </g>
    </g>
  `}function zi(t,e,r,o){return p`
    <rect x=${S.x1} y=${S.y1} width=${u(S.x2-S.x1)} height=${u(S.y2-S.y1)} fill=${`url(#${t}-cav-back)`}></rect>
    ${r==="heat"?p`<rect x=${S.x1} y=${S.y1} width=${u(S.x2-S.x1)} height=${u(S.y2-S.y1)} fill=${`url(#${t}-cav-low)`}></rect>`:f}
    ${xi(t,e,r,o)}
    <polygon points=${gt([[y.x1,y.y1],[S.x1,S.y1],[S.x1,S.y2],[y.x1,y.y2]])} fill=${`url(#${t}-cav-left)`}></polygon>
    <polygon points=${gt([[y.x2,y.y1],[S.x2,S.y1],[S.x2,S.y2],[y.x2,y.y2]])} fill=${`url(#${t}-cav-right)`}></polygon>
    <polygon points=${gt([[y.x1,y.y1],[y.x2,y.y1],[S.x2,S.y1],[S.x1,S.y1]])} fill=${`url(#${t}-cav-ceiling)`}></polygon>
    <polygon points=${gt([[y.x1,y.y2],[y.x2,y.y2],[S.x2,S.y2],[S.x1,S.y2]])} fill=${`url(#${t}-cav-floor)`}></polygon>
    ${Si(r)}
  `}function Si(t){let e=t==="off"?"#2c2e30":t==="lamp"?"#5a4c43":"#9a847c",r=t==="off"?"#0b0c0d":"#140a06";return p`<g stroke-linecap="round">
    ${[0,2,4,6].map(o=>{let n=x.y+(Ne[o]+Ne[o+1])/2*x.height,[a,i]=k(y.x1,n,.06),[s,l]=k(y.x1,n,.92),[c,d]=k(y.x2,n,.06),[m,b]=k(y.x2,n,.92);return p`
        <line x1=${a} y1=${i+1.2} x2=${s} y2=${l+1} stroke=${r} stroke-opacity="0.45" stroke-width="2.2"></line>
        <line x1=${a} y1=${i} x2=${s} y2=${l} stroke=${e} stroke-opacity="0.3" stroke-width="1"></line>
        <line x1=${c} y1=${d+1.2} x2=${m} y2=${b+1} stroke=${r} stroke-opacity="0.45" stroke-width="2.2"></line>
        <line x1=${c} y1=${d} x2=${m} y2=${b} stroke=${e} stroke-opacity="0.2" stroke-width="1"></line>
      `})}
  </g>`}function Ai(t,e){let[r,o]=k(y.x1,y.y1+24,.14),[n,a]=k(y.x1,y.y1+40,.24),i=e!=="off";return p`
    ${i?p`<rect x=${y.x1} y=${y.y1} width=${A.width} height=${A.height} fill=${`url(#${t}-lamp-light)`}></rect>`:f}
    <polygon points=${gt([[r+2,o],[n+1,a-2],[n+1,a+9],[r+2,o+18]])}
      fill=${i?"#ffeccc":"#2b2c2e"} stroke=${i?"#c9a77a":"#3a3b3d"} stroke-width="0.6"></polygon>
    ${i?p`<polygon points=${gt([[r+2,o],[n+1,a-2],[n+1,a+9],[r+2,o+18]])} fill="#ffd9a0"
          filter=${`url(#${t}-halo)`} opacity="0.7"></polygon>`:f}
  `}function Ti(t,e){let r=wr(e.elements),o=(a,i,s)=>{let[l,c]=k(y.x1+14,a,i),[d]=k(y.x2-14,a,i),m=u(5*bt(i));return p`
      ${s?p`<rect x=${l} y=${u(c-m*1.8)} width=${u(d-l)} height=${u(m*3.6)} rx=${m}
            fill="#ff7a24" opacity=${u(.75*r.heat)} filter=${`url(#${t}-halo)`}></rect>`:f}
      <rect x=${l} y=${u(c-m/2)} width=${u(d-l)} height=${m} rx=${u(m/2)}
        fill=${`url(#${t}-tube${s?"-hot":""})`} opacity=${s?u(.6+r.heat*.4):.8}></rect>
    `},n=[.18,.5,.82];return p`
    ${n.map((a,i)=>o(y.y1+9,a,r.top.includes(i)))}
    ${n.map((a,i)=>o(y.y2-7,a,r.bottom.includes(i)))}
  `}function Ci(t,e){let r=wr(e.elements);return!r.top.length&&!r.bottom.length?f:p`
    ${r.top.length?p`<rect x=${y.x1} y=${y.y1} width=${A.width} height="95" fill=${`url(#${t}-heat-top)`}
          opacity=${r.top.length===3?1:.7}></rect>`:f}
    ${r.bottom.length?p`<rect x=${y.x1} y=${y.y2-70} width=${A.width} height="70" fill=${`url(#${t}-heat-bottom)`}></rect>`:f}
  `}function Mi(t,e,r){let o=ao(e),n=y.x1+14,a=y.x2-14,[i,s]=k(n,o,.04),[l]=k(a,o,.04),[c,d]=k(n,o,.94),[m]=k(a,o,.94),b=21;return p`<g class="rack" stroke-linecap="round" opacity=${r==="off"?.32:r==="lamp"?.75:.9}>
    ${Array.from({length:b},(v,z)=>{let T=(z+.5)/b,G=u(i+T*(l-i)),X=u(c+T*(m-c));return p`<line x1=${G} y1=${s} x2=${X} y2=${d} stroke="#8d8f91" stroke-width="0.8"></line>`})}
    <line x1=${c} y1=${d} x2=${m} y2=${d} stroke="#a7a9ab" stroke-width="1.1"></line>
    <line x1=${i} y1=${s} x2=${c} y2=${d} stroke="#c9c6c0" stroke-width="1.4"></line>
    <line x1=${l} y1=${s} x2=${m} y2=${d} stroke="#c9c6c0" stroke-width="1.4"></line>
    <line x1=${i-4} y1=${s} x2=${l+4} y2=${s} stroke=${`url(#${t}-wire)`} stroke-width="2.4"></line>
    <line x1=${i} y1=${s+1.5} x2=${l} y2=${s+1.5} stroke="#000000" stroke-opacity="0.3" stroke-width="0.8"></line>
    ${Array.from({length:b},(v,z)=>{let T=(z+.5)/b;return p`<circle cx=${u(i+T*(l-i))} cy=${s-.2} r="0.75" fill="#fffaf0" opacity="0.85"></circle>`})}
  </g>`}function Kn(t,e,r){let o=io(e);return p`
    ${zi(t,e,o,r)}
    ${Ai(t,o)}
    ${Ti(t,e)}
    ${Ci(t,e)}
    ${Mi(t,e.rack,o)}
  `}function so(t){return io(t)}function Wn(t,e){let r=x.x+x.width-10,o=Ne.map((n,a)=>{let i=x.y+n*x.height,s=a%2===0;return p`<text x=${r} y=${u(i+2.2)} font-size="6.2" font-weight="600" text-anchor="end">${a+1}</text>
      ${s?p`<path d=${`M${r+1.6},${u(i-.4)} h2 v${u((Ne[a+1]-n)*x.height*.5)} h1.4 M${r+3.6},${u(i-.4+(Ne[a+1]-n)*x.height*.5)} v${u((Ne[a+1]-n)*x.height*.5)} h-2`}
            fill="none" stroke=${no} stroke-width="0.6"></path>`:f}`});return p`
    <rect x=${x.x} y=${x.y} width=${x.width} height=${x.height} fill="#140d09" opacity=${e==="off"?.3:.18}></rect>
    <g clip-path=${`url(#${t}-window)`}>
      <path d=${`M${x.x+30},${x.y} H${x.x+120} L${x.x+50},${x.y+x.height} H${x.x-40} Z`}
        fill="#ffffff" opacity=${e==="off"?.045:.03}></path>
      <path d=${`M${x.x+150},${x.y} H${x.x+168} L${x.x+98},${x.y+x.height} H${x.x+80} Z`}
        fill="#ffffff" opacity=${e==="off"?.03:.02}></path>
      <rect x=${x.x} y=${x.y} width=${x.width} height="5" fill="#000000" opacity="0.35" filter=${`url(#${t}-halo)`}></rect>
    </g>
    <g fill=${no} font-family="'Arial Narrow', 'Roboto Condensed', Arial, sans-serif" opacity="0.92">${o}</g>
  `}function Qn(t){return p`
    ${_(`${t}-enamel`,[[0,"#4c4744"],[.15,"#2f2c2a"],[.6,"#1f1d1c"],[1,"#151413"]],[0,0],[0,1])}
    ${_(`${t}-enamel-in`,[[0,"#121111"],[1,"#2a2726"]],[0,0],[0,1])}
    ${_(`${t}-chrome-bar`,[[0,"#f6f4f0"],[.35,"#c9c6c0"],[.7,"#7c7a77"],[1,"#4c4b49"]],[0,0],[0,1])}
    ${_(`${t}-mesh-rim`,[[0,"#e9eaeb"],[.4,"#a9acaf"],[1,"#5b5e61"]],[0,0],[0,1])}
    ${_(`${t}-pizza-pan`,[[0,"#3a3b3d"],[.5,"#232426"],[1,"#151617"]],[0,0],[0,1])}
    ${le(`${t}-roll`,[[0,"#f9cb84"],[.28,"#e49b48"],[.58,"#c26b2a"],[.84,"#8f4416"],[1,"#5c240a"]],[.42,.36],.7,[.3,.22])}
    ${_(`${t}-roll-base`,[[0,"#2a0e03",0],[1,"#2a0e03",.45]],[0,0],[0,1])}
    <clipPath id=${`${t}-on-tray`}><rect x="-90" y="-70" width="180" height="71"></rect></clipPath>
    ${le(`${t}-skin`,[[0,"#f3c27c"],[.4,"#d38b44"],[.75,"#a35a24"],[1,"#5d2e10"]],[.42,.3],.72)}
    ${le(`${t}-seared`,[[0,"#6b3420"],[.6,"#4a2112"],[1,"#2a120a"]],[.45,.4],.7)}
    ${_(`${t}-meat-side`,[[0,"#7a3424"],[.45,"#b0544a"],[1,"#6a2a1c"]],[0,0],[0,1])}
    ${_(`${t}-fry`,[[0,"#f6d58a"],[.35,"#ecbd62"],[.7,"#d99a3f"],[1,"#a8691f"]],[0,0],[0,1])}
    ${le(`${t}-cheese`,[[0,"#f7d77a"],[.6,"#eab650"],[1,"#c98a2e"]],[.45,.4],.7)}
    ${_(`${t}-pizza-crust`,[[0,"#e7b36a"],[.5,"#c47f37"],[1,"#8a4c1c"]],[0,0],[0,1])}
    ${le(`${t}-cookie`,[[0,"#e8b56b"],[.55,"#c98a42"],[.85,"#a66325"],[1,"#7a4316"]],[.45,.35],.7)}
    ${_(`${t}-ceramic`,[[0,"#ffffff"],[.55,"#ecebe7"],[1,"#bcb9b2"]],[0,0],[0,1])}
    ${_(`${t}-dome`,[[0,"#6d7175"],[.18,"#d9dcde"],[.3,"#ffffff"],[.45,"#b9bdc0"],[.7,"#7b8085"],[.85,"#c2c6c9"],[1,"#5d6165"]])}
    ${_(`${t}-castiron`,[[0,"#6a1612"],[.2,"#c23a2e"],[.32,"#e86a55"],[.45,"#b8322a"],[.8,"#7c1a15"],[1,"#4a0d0a"]])}
    ${le(`${t}-dough`,[[0,"#fff4de"],[.6,"#f1dcb4"],[1,"#d9bd8e"]],[.45,.3],.7)}
    ${le(`${t}-toast`,[[0,"#e9b264"],[.6,"#c98a3e"],[1,"#9a5a22"]],[.5,.4],.7)}
    <pattern id=${`${t}-mesh`} width="3.4" height="3.4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <path d="M0,0 H3.4 M0,0 V3.4" stroke="#b8bbbe" stroke-width="0.6"></path>
    </pattern>
    <filter id=${`${t}-crust`} x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="sRGB">
      <feTurbulence type="fractalNoise" baseFrequency="0.22" numOctaves="3" seed="4" result="noise"></feTurbulence>
      <feDiffuseLighting in="noise" surfaceScale="1.1" diffuseConstant="1" lighting-color="#ffffff" result="light">
        <feDistantLight azimuth="235" elevation="58"></feDistantLight>
      </feDiffuseLighting>
      <feComposite in="light" in2="SourceGraphic" operator="arithmetic" k1="1.18" k2="0" k3="0" k4="0" result="lit"></feComposite>
      <feComposite in="lit" in2="SourceAlpha" operator="in"></feComposite>
    </filter>
    <filter id=${`${t}-fine`} x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="sRGB">
      <feTurbulence type="fractalNoise" baseFrequency="0.7" numOctaves="2" seed="9" result="noise"></feTurbulence>
      <feDiffuseLighting in="noise" surfaceScale="1.2" diffuseConstant="1" lighting-color="#ffffff" result="light">
        <feDistantLight azimuth="235" elevation="58"></feDistantLight>
      </feDiffuseLighting>
      <feComposite in="light" in2="SourceGraphic" operator="arithmetic" k1="1.2" k2="0" k3="0" k4="0" result="lit"></feComposite>
      <feComposite in="lit" in2="SourceAlpha" operator="in"></feComposite>
    </filter>
    <filter id=${`${t}-glaze`} x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="sRGB">
      <feTurbulence type="fractalNoise" baseFrequency="0.35 0.6" numOctaves="2" seed="21" result="noise"></feTurbulence>
      <feDiffuseLighting in="noise" surfaceScale="0.5" diffuseConstant="1" lighting-color="#ffffff" result="light">
        <feDistantLight azimuth="235" elevation="62"></feDistantLight>
      </feDiffuseLighting>
      <feComposite in="light" in2="SourceGraphic" operator="arithmetic" k1="1.1" k2="0" k3="0" k4="0" result="lit"></feComposite>
      <feComposite in="lit" in2="SourceAlpha" operator="in"></feComposite>
    </filter>
    <filter id=${`${t}-crease`} x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="0.7"></feGaussianBlur></filter>
    <filter id=${`${t}-gloss`} x="-30%" y="-60%" width="160%" height="220%"><feGaussianBlur stdDeviation="0.9"></feGaussianBlur></filter>
    <filter id=${`${t}-soft-shadow`} x="-20%" y="-100%" width="140%" height="300%"><feGaussianBlur stdDeviation="2"></feGaussianBlur></filter>
  `}var Ve=t=>t.map(([e,r])=>`${e},${r}`).join(" ");function xr(t,e,r,o,n){return Ve([k(t,r,o),k(e,r,o),k(e,r,n),k(t,r,n)])}var co=11;function qn(t,e){let r=F-150,o=F+150,n=e-co,a=.12,i=.78,[s,l]=k(r+5,e,a),[c]=k(o-5,e,a),[d,m]=k(r,n,a),[b]=k(o,n,a),$=n>Se.y;return{place:{x:F,y:e-3,depth:.45,half:140},back:p`
      <ellipse cx=${F} cy=${u(l+1)} rx="160" ry="4" fill="#000000" opacity="0.35" filter=${`url(#${t}-soft-shadow)`}></ellipse>
      ${$?p`<polygon points=${xr(r,o,n,a,i)} fill=${`url(#${t}-enamel-in)`}></polygon>
            <polygon points=${xr(r+7,o-7,n+1,a+.04,i-.04)} fill="#0e0d0d" opacity="0.6"></polygon>`:f}
      <polyline points=${Ve([k(r,n,i),k(o,n,i)])} stroke="#6a625d" stroke-width="1.1" fill="none"></polyline>
    `,front:p`
      <polygon points=${Ve([[d,m],[b,m],[c,l],[s,l]])} fill=${`url(#${t}-enamel)`}></polygon>
      <line x1=${d-1} y1=${m} x2=${b+1} y2=${m} stroke="#9a928c" stroke-width="1.6" stroke-linecap="round"></line>
      <line x1=${d+4} y1=${u(m+2.2)} x2=${b-4} y2=${u(m+2.2)} stroke="#ffffff" stroke-opacity="0.12" stroke-width="1.4"></line>
      <path d=${`M${d+30},${u(m+4)} L${d+120},${u(m+4)} L${d+112},${u(l-2)} L${d+26},${u(l-2)} Z`}
        fill="#ffffff" opacity="0.05"></path>
    `}}function Pi(t,e){let r=e-co,o=F-146,n=F+146,a=.14,i=.76,s=16,l=xr(o,n,r,a,i);return p`
    <polygon points=${l} fill=${`url(#${t}-chrome-bar)`}></polygon>
    ${Array.from({length:s},(c,d)=>{let m=(d+.5)/s,b=o+10+m*(n-o-20),[$,v]=k(b-3,r,a+.05),[z,T]=k(b+3,r,a+.05),[G,X]=k(b+3,r,i-.05),[R,U]=k(b-3,r,i-.05);return p`<polygon points=${Ve([[$,v],[z,T],[G,X],[R,U]])} fill="#1b1a19"></polygon>`})}
    <polyline points=${Ve([k(o,r,a),k(n,r,a)])} stroke="#ffffff" stroke-opacity="0.6" stroke-width="1"></polyline>
  `}function Ri(t,e){let r=F-142,o=F+142,n=e-26,a=.1,i=.8,[s,l]=k(r+6,e,a),[c]=k(o-6,e,a),[d,m]=k(r,n,a),[b]=k(o,n,a);return{place:{x:F,y:e-3,depth:.45,half:130},back:p`
      <ellipse cx=${F} cy=${u(l+1)} rx="150" ry="4" fill="#000000" opacity="0.3" filter=${`url(#${t}-soft-shadow)`}></ellipse>
      ${n>Se.y?p`<polygon points=${xr(r,o,n,a,i)} fill=${`url(#${t}-mesh)`}></polygon>`:f}
      <polyline points=${Ve([k(r,n,i),k(o,n,i)])} stroke="#9fa2a5" stroke-width="1.4" fill="none"></polyline>
    `,front:p`
      <polygon points=${Ve([[d,m],[b,m],[c,l],[s,l]])} fill="#000000" opacity="0.28"></polygon>
      <polygon points=${Ve([[d,m],[b,m],[c,l],[s,l]])} fill=${`url(#${t}-mesh)`}></polygon>
      <line x1=${d-1} y1=${m} x2=${b+1} y2=${m} stroke=${`url(#${t}-mesh-rim)`} stroke-width="2.6" stroke-linecap="round"></line>
      <line x1=${s} y1=${l} x2=${c} y2=${l} stroke="#9fa2a5" stroke-width="1.2"></line>
    `}}function Ei(t,e){let[o,n]=k(F,e-3,.45),a=bt(.45),i=Math.max(.035,Math.min(.2,(e-Se.y)/300)),s=u(165*a),l=u(165*a*i);return{place:{x:F,y:e-4,depth:.45,half:150},front:f,back:p`
      <ellipse cx=${o} cy=${u(n+4)} rx=${s+6} ry=${l+3} fill="#000000" opacity="0.3" filter=${`url(#${t}-soft-shadow)`}></ellipse>
      <path d=${`M${o-s},${n} A${s},${l} 0 0 0 ${o+s},${n} V${u(n+3)} A${s},${l} 0 0 1 ${o-s},${u(n+3)} Z`} fill="#1a1b1c"></path>
      <ellipse cx=${o} cy=${n} rx=${s} ry=${l} fill=${`url(#${t}-pizza-pan)`} stroke="#6a6c6e" stroke-width="1"></ellipse>
    `}}function Li(t,e){let[r,o]=k(F,e,.45),n=bt(.45),a=98*n,i=72*n;return{place:{x:F,y:e-70,depth:.45,half:90},front:f,back:p`
      <ellipse cx=${r} cy=${u(o+1)} rx=${u(a+10)} ry="4" fill="#000000" opacity="0.4" filter=${`url(#${t}-soft-shadow)`}></ellipse>
      <path d=${`M${u(r-a)},${u(o-i)} H${u(r+a)} V${u(o-10*n)} Q${u(r+a)},${o} ${u(r+a-12*n)},${o}
          H${u(r-a+12*n)} Q${u(r-a)},${o} ${u(r-a)},${u(o-10*n)} Z`} fill=${`url(#${t}-castiron)`}></path>
      <path d=${`M${u(r-a-12*n)},${u(o-i+10*n)} h${u(12*n)} v${u(14*n)} h${u(-12*n)} a${u(4*n)},${u(4*n)} 0 0 1 0,${u(-14*n)} z
          M${u(r+a+12*n)},${u(o-i+10*n)} h${u(-12*n)} v${u(14*n)} h${u(12*n)} a${u(4*n)},${u(4*n)} 0 0 0 0,${u(-14*n)} z`}
        fill="#8a1d16"></path>
      <path d=${`M${u(r-a-3*n)},${u(o-i)} Q${r},${u(o-i-34*n)} ${u(r+a+3*n)},${u(o-i)} Z`} fill=${`url(#${t}-castiron)`}></path>
      <line x1=${u(r-a-3*n)} y1=${u(o-i)} x2=${u(r+a+3*n)} y2=${u(o-i)} stroke="#3a0907" stroke-width="1.4"></line>
      <path d=${`M${u(r-13*n)},${u(o-i-24*n)} h${u(26*n)} v${u(-6*n)} a3,3 0 0 0 -3,-3 h${u(-20*n)} a3,3 0 0 0 -3,3 z`} fill="#2b2c2e"></path>
      <path d=${`M${u(r-a*.72)},${u(o-i-10*n)} Q${u(r-a*.2)},${u(o-i-27*n)} ${u(r+a*.35)},${u(o-i-22*n)}`}
        fill="none" stroke="#ffffff" stroke-opacity="0.4" stroke-width=${u(3*n)} stroke-linecap="round" filter=${`url(#${t}-gloss)`}></path>
      <rect x=${u(r-a*.55)} y=${u(o-i+8*n)} width=${u(a*.16)} height=${u(i*.75)} rx="3" fill="#ffffff" opacity="0.2" filter=${`url(#${t}-gloss)`}></rect>
    `}}function Jn(t,e,r){switch(e){case"roasting_pan":return qn(t,r);case"broil_rack":{let o=qn(t,r);return{place:{...o.place,y:r-co-1},back:p`${o.back}${Pi(t,r)}`,front:o.front}}case"air_fry_basket":return Ri(t,r);case"pizza_pan":return Ei(t,r);case"pot":return Li(t,r);default:return{place:{x:F,y:r-1,depth:.45,half:170},back:f,front:f}}}function B(t,e,r,o=t.depth){let[n,a]=k(t.x+e,t.y,o);return p`<g transform=${`translate(${n} ${a}) scale(${u(bt(o))})`}>${r}</g>`}var Hi=[[-58,1,30,16,-30],[59,1,29,16,28],[-41,-2,38,22,-46],[42,-2,37,22,44],[-21,-7,46,26,-60],[22,-7,45,26,58],[0,-13,52,30,-80]];function lo(t,e,r,o,n){let a=n*Math.PI/180,i=r*Math.cos(a),s=r*Math.sin(a),l=`${u(t-i)},${u(e-s)}`,c=`${u(t+i)},${u(e+s)}`;return`M${l}A${r},${o} ${n} 1 0 ${c}A${r},${o} ${n} 1 0 ${l}Z`}function Zn(t,e){let r=Hi.map(([o,n,a,i,s],l)=>{let c=o+e*(l%2?-1:1),d=$=>[c+Math.cos(s*Math.PI/180)*a*$,n+Math.sin(s*Math.PI/180)*a*$],[m,b]=d(-.08);return p`
      ${l>1?p`<path d=${lo(c,n,a/2+1.5,i/2+1.4,s)} fill="#2e0f03" opacity="0.5" filter=${`url(#${t}-crease)`}></path>`:f}
      <path d=${lo(c,n,a/2,i/2,s)} fill=${`url(#${t}-roll)`}></path>
      <path d=${lo(u(m-i*.14),u(b-i*.12),u(a*.3),u(i*.16),s)}
        fill="#fff0c8" opacity="0.62" filter=${`url(#${t}-gloss)`}></path>
    `});return p`
    <ellipse cx="0" cy="2.5" rx="72" ry="4.5" fill="#000000" opacity="0.5" filter=${`url(#${t}-soft-shadow)`}></ellipse>
    <g clip-path=${`url(#${t}-on-tray)`}>
      <g filter=${`url(#${t}-glaze)`}>${r}</g>
      <rect x="-80" y="-14" width="160" height="15" fill=${`url(#${t}-roll-base)`}></rect>
    </g>
  `}function Di(t,e){return p`${B(e,-74,Zn(t,0))}${B(e,74,Zn(t,2))}`}function Oi(t,e){let r=e.half-4;return B(e,0,p`<g filter=${`url(#${t}-crust)`}>
      <path d=${`M${-r},2 C${-r+4},-22 ${-r*.4},-27 0,-27 C${r*.4},-27 ${r-4},-22 ${r},2 Z`} fill=${`url(#${t}-cheese)`}></path>
      ${[[-100,-12,16],[-55,-20,12],[-12,-23,18],[36,-21,13],[82,-15,15],[118,-6,9],[-128,-4,9]].map(([o,n,a])=>p`<ellipse cx=${o} cy=${n} rx=${a} ry=${a*.32} fill="#8a4316" opacity="0.6"></ellipse>`)}
    </g>`)}function Bi(t,e){return B(e,0,p`
      <ellipse cx="0" cy="2" rx="78" ry="5" fill="#000000" opacity="0.45" filter=${`url(#${t}-soft-shadow)`}></ellipse>
      <g filter=${`url(#${t}-crust)`}>
        <path d="M-74,-4 C-80,-30 -54,-58 -4,-60 C46,-60 78,-34 72,-6 C40,4 -40,4 -74,-4 Z" fill=${`url(#${t}-skin)`}></path>
        <path d="M-62,-6 C-94,-6 -100,-30 -78,-38 C-62,-36 -54,-22 -48,-10 Z" fill=${`url(#${t}-skin)`}></path>
        <path d="M60,-6 C92,-6 98,-30 76,-38 C60,-36 52,-22 46,-10 Z" fill=${`url(#${t}-skin)`}></path>
        <path d="M-86,-30 c-6,-4 -10,-2 -10,3 c2,4 6,4 10,1 z M84,-30 c6,-4 10,-2 10,3 c-2,4 -6,4 -10,1 z" fill="#efe2c8"></path>
      </g>
      <path d="M-2,-58 C-6,-40 -4,-20 2,-4" fill="none" stroke="#6e3412" stroke-opacity="0.35" stroke-width="2"></path>
      <path d="M-40,-46 C-20,-56 18,-56 36,-46" fill="none" stroke="#fff1d0" stroke-opacity="0.45" stroke-width="5" stroke-linecap="round" filter=${`url(#${t}-gloss)`}></path>
      <ellipse cx="-30" cy="-30" rx="10" ry="4" fill="#fff1d0" opacity="0.35" filter=${`url(#${t}-gloss)`}></ellipse>
    `)}function ji(t,e){let r=p`
    <ellipse cx="0" cy="3" rx="56" ry="5" fill="#000000" opacity="0.45" filter=${`url(#${t}-soft-shadow)`}></ellipse>
    <path d="M-54,-2 C-56,-10 -40,-15 -6,-15 C34,-15 56,-11 54,-3 C52,4 -50,5 -54,-2 Z" fill=${`url(#${t}-meat-side)`}></path>
    <path d="M-54,-8 C-56,-17 -40,-24 -6,-24 C34,-24 56,-19 54,-10 C50,-3 -48,-1 -54,-8 Z" fill=${`url(#${t}-seared)`} filter=${`url(#${t}-fine)`}></path>
    ${[-30,-12,6,24].map(o=>p`<path d=${`M${o-7},-6 L${o+9},-21`} stroke="#160a05" stroke-width="3" stroke-linecap="round" opacity="0.8"></path>`)}
    <ellipse cx="-14" cy="-19" rx="18" ry="2.2" fill="#ffffff" opacity="0.18" filter=${`url(#${t}-gloss)`}></ellipse>
  `;return p`${B(e,-64,r)}${B(e,64,r)}`}function Gi(t,e){let r=[];for(let o=0;o<70;o++){let n=-118+o*53%236,a=22*Math.sqrt(Math.max(0,1-(n/125)**2)),s=-2-o*29%100/100*a,l=o*47%70-35,c=34+o*17%20,d=.85+o*13%30/100;r.push(p`<g transform=${`translate(${n} ${u(s)}) rotate(${l})`} opacity=${u(Math.min(1,d))}>
      <rect x=${-c/2} y="-2.6" width=${c} height="5.2" rx="1.6" fill=${`url(#${t}-fry)`}></rect>
      <rect x=${-c/2} y="-2.6" width="4" height="5.2" rx="1.6" fill="#8a4a14" opacity="0.55"></rect>
      <rect x=${c/2-4} y="-2.6" width="4" height="5.2" rx="1.6" fill="#8a4a14" opacity="0.45"></rect>
    </g>`)}return B(e,0,p`
      <ellipse cx="0" cy="2" rx="128" ry="6" fill="#000000" opacity="0.35" filter=${`url(#${t}-soft-shadow)`}></ellipse>
      <g filter=${`url(#${t}-fine)`}>${r}</g>
    `)}function Ni(t,e,r){let o=Math.max(.035,Math.min(.2,(e.y-Se.y)/300)),n=150,a=n*o;return B(e,0,p`
      <path d=${`M${-n},0 A${n},${a} 0 0 0 ${n},0 V-5 A${n},${a} 0 0 1 ${-n},-5 Z`} fill="#b06a2c"></path>
      <ellipse cx="0" cy="-5" rx=${n} ry=${a} fill=${`url(#${t}-pizza-crust)`} filter=${`url(#${t}-crust)`}></ellipse>
      <ellipse cx="0" cy="-5.5" rx=${n-12} ry=${a*.86} fill=${`url(#${t}-cheese)`} filter=${`url(#${t}-fine)`}></ellipse>
      ${[[-100,0],[-58,-.4],[-18,.3],[24,-.3],[64,.2],[104,-.1],[-80,.55],[40,.55],[-40,-.6],[80,-.55]].map(([i,s])=>p`<ellipse cx=${i} cy=${u(-5.5+s*a*.7)} rx="10" ry=${u(Math.max(1.6,a*.2))} fill="#9e2a1c"></ellipse>
          <ellipse cx=${i-2} cy=${u(-6+s*a*.7)} rx="4" ry=${u(Math.max(.6,a*.07))} fill="#ffffff" opacity="0.25"></ellipse>`)}
      ${r?p`<ellipse cx="0" cy="-5.5" rx=${n} ry=${a} fill="#eef6fb" opacity="0.55" filter=${`url(#${t}-fine)`}></ellipse>`:f}
    `)}function Vi(t,e){let r=o=>p`
    <ellipse cx="0" cy="1" rx=${o} ry=${o*.22} fill="#000000" opacity="0.4" filter=${`url(#${t}-soft-shadow)`}></ellipse>
    <path d=${`M${-o},0 C${-o},${-o*.62} ${o},${-o*.62} ${o},0 C${o*.6},${o*.14} ${-o*.6},${o*.14} ${-o},0 Z`} fill=${`url(#${t}-cookie)`}
      filter=${`url(#${t}-crust)`}></path>
    ${[[-.4,-.12],[.1,-.22],[.45,-.08],[-.1,-.04]].map(([n,a])=>p`<ellipse cx=${n*o} cy=${a*o} rx=${o*.11} ry=${o*.06} fill="#3a1d0e"></ellipse>`)}
  `;return p`
    ${[-96,-32,32,96].map(o=>B(e,o,r(23),.66))}
    ${[-128,-64,0,64,128].map(o=>B(e,o,r(25),.4))}
  `}function Ii(t,e){return B(e,0,p`
      <ellipse cx="0" cy="1" rx="80" ry="7" fill="#000000" opacity="0.35" filter=${`url(#${t}-soft-shadow)`}></ellipse>
      <ellipse cx="0" cy="-1" rx="76" ry="9" fill="#a9a59e"></ellipse>
      <ellipse cx="0" cy="-3" rx="76" ry="8.5" fill=${`url(#${t}-ceramic)`}></ellipse>
      <g filter=${`url(#${t}-crust)`}>
        <path d="M-50,-4 C-46,-26 -6,-30 14,-22 C24,-30 46,-26 50,-6 Z" fill=${`url(#${t}-skin)`}></path>
      </g>
      <ellipse cx="34" cy="-8" rx="13" ry="5" fill="#4f7a2e" filter=${`url(#${t}-fine)`}></ellipse>
    `)}function Fi(t,e){return B(e,0,p`
      <ellipse cx="0" cy="1" rx="76" ry="6" fill="#000000" opacity="0.35" filter=${`url(#${t}-soft-shadow)`}></ellipse>
      <ellipse cx="0" cy="-58" rx="62" ry="24" fill=${`url(#${t}-dough)`} filter=${`url(#${t}-fine)`}></ellipse>
      <path d="M-74,-56 Q-68,0 -34,0 H34 Q68,0 74,-56 Z" fill=${`url(#${t}-ceramic)`}></path>
      <ellipse cx="0" cy="-56" rx="74" ry="7" fill="none" stroke="#d6d2ca" stroke-width="2.4"></ellipse>
      <rect x="-56" y="-46" width="10" height="38" rx="5" fill="#ffffff" opacity="0.5" filter=${`url(#${t}-gloss)`}></rect>
    `)}function Ui(t,e){return B(e,0,p`
      <ellipse cx="0" cy="1" rx="92" ry="6" fill="#000000" opacity="0.35" filter=${`url(#${t}-soft-shadow)`}></ellipse>
      <ellipse cx="0" cy="-2" rx="88" ry="8" fill="#cfccc6"></ellipse>
      <path d="M-80,-4 Q-78,-50 0,-52 Q78,-50 80,-4 Z" fill=${`url(#${t}-dome)`}></path>
      <rect x="-10" y="-60" width="20" height="8" rx="3.5" fill="#8c9195"></rect>
    `)}function Ki(t,e){let r=o=>p`
    <ellipse cx="0" cy="0" rx="17" ry="5" fill=${o?"#e98a22":"#f1e2b4"} filter=${`url(#${t}-fine)`}></ellipse>
    <ellipse cx="0" cy="0" rx="12.5" ry="3.4" fill="none" stroke=${o?"#ffc874":"#b84a36"} stroke-width="1"></ellipse>
    ${o?p`${[0,60,120].map(n=>p`<line x1="0" y1="0" x2=${u(12*Math.cos(n*Math.PI/180))} y2=${u(3.3*Math.sin(n*Math.PI/180))} stroke="#ffd79a" stroke-width="0.6"></line>`)}`:f}
  `;return p`${[-105,-70,-35,0,35,70,105].map((o,n)=>B(e,o,p`<g transform=${`translate(0 ${-6-n%2*3})`}>${r(n%3!==1)}</g>`,n%2?.55:.35))}`}function Wi(t,e){let r=p`
    <ellipse cx="0" cy="1" rx="56" ry="4" fill="#000000" opacity="0.4" filter=${`url(#${t}-soft-shadow)`}></ellipse>
    <path d="M-54,0 q2,-12 16,-13 h76 q14,1 16,13 z" fill="#9a5a22"></path>
    <path d="M-49,-2 q2,-9 13,-10 h72 q11,1 13,10 z" fill=${`url(#${t}-toast)`} filter=${`url(#${t}-fine)`}></path>
  `;return p`${B(e,-64,r)}${B(e,64,r)}`}function qi(t,e){let r=p`
    <ellipse cx="0" cy="1" rx="46" ry="5" fill="#000000" opacity="0.4" filter=${`url(#${t}-soft-shadow)`}></ellipse>
    <ellipse cx="0" cy="-4" rx="44" ry="10" fill="#a8652a" filter=${`url(#${t}-crust)`}></ellipse>
    <ellipse cx="0" cy="-6" rx="36" ry="7" fill=${`url(#${t}-toast)`} filter=${`url(#${t}-fine)`}></ellipse>
    <ellipse cx="0" cy="-6" rx="10" ry="2.6" fill="#2b1a10"></ellipse>
  `;return p`${B(e,-60,r)}${B(e,60,r)}`}function Zi(t,e){return B(e,0,p`
      <ellipse cx="0" cy="1" rx="70" ry="4" fill="#000000" opacity="0.35" filter=${`url(#${t}-soft-shadow)`}></ellipse>
      <path d="M-70,0 L60,-4 L66,-13 L-64,-9 Z" fill=${`url(#${t}-pizza-crust)`} filter=${`url(#${t}-crust)`}></path>
      <path d="M-56,-2 L52,-5 L56,-11 L-52,-8 Z" fill=${`url(#${t}-cheese)`} filter=${`url(#${t}-fine)`}></path>
      ${[-30,0,30].map(r=>p`<ellipse cx=${r} cy="-6.5" rx="8" ry="1.6" fill="#9e2a1c"></ellipse>`)}
    `)}function Yn(t,e,r,o){switch(e){case"croissants":return Di(t,r);case"casserole":return Oi(t,r);case"chicken":return Bi(t,r);case"steak":return ji(t,r);case"fries":return Gi(t,r);case"pizza":return Ni(t,r,o);case"cookies":return Vi(t,r);case"plate":return Ii(t,r);case"dough":return Fi(t,r);case"covered_dish":return Ui(t,r);case"fruit":return Ki(t,r);case"bread":return Wi(t,r);case"bagel":return qi(t,r);case"pizza_slice":return Zi(t,r);default:return f}}var Ie=ve.lcd,ta={brushed:{lit:{bezel:"#6c6b68",screen:["#e2b56a","#d9a74f","#cf942e"],shade:"#70422f",ink:"#4e402d",ghost:.06,glow:!1},pale:{bezel:"#7d8b95",screen:["#e2f0fb","#d4e9f8","#c3dcef"],shade:"#6f8ea6",ink:"#3f515d",ghost:.07,glow:!1},off:{bezel:"#6c6b68",screen:["#a9b3b8","#9aa4a9","#8b959a"],shade:"#4c5458",ink:"#4c5458",ghost:.08,glow:!1}},black:{lit:{bezel:"#373435",screen:["#2c2c2c","#232323","#1b1b1b"],shade:"#0c0c0c",ink:"#f2622f",ghost:.07,glow:!0},pale:{bezel:"#373435",screen:["#2c2c2c","#232323","#1b1b1b"],shade:"#0c0c0c",ink:"#eef1f3",ghost:.07,glow:!0},off:{bezel:"#373435",screen:["#262626","#1e1e1e","#171717"],shade:"#0a0a0a",ink:"#6a6a6a",ghost:.05,glow:!1}}},Qi={0:"abcdef",1:"bc",2:"abdeg",3:"abcdg",4:"bcfg",5:"acdfg",6:"acdefg",7:"abc",8:"abcdefg",9:"abcdfg","-":"g"," ":"",A:"abcefg",C:"adef",E:"adefg",F:"aefg",H:"bcefg",I:"bc",L:"def",M:"abcef",P:"abefg",U:"bcdef",d:"bcdeg",n:"ceg",o:"cdeg",r:"eg"},Xn=[["TOAST",["toast"]],["BAGEL",["bagel"]],["BAKE",["bake","bottom_bake"]],["AIR FRY",["air_fry","gentle_broil"]],["BROIL",["broil","bottom_broil","outer_top_broil","middle_top_broil","windy_broil"]],["ROAST",["roast"]],["PIZZA",["pizza"]],["COOKIES",["cookies"]],["PROOF",["proof"]],["REHEAT",["reheat","crispy_reheat"]],["SLOW COOK",["slow_cook"]],["KEEP WARM",["warm","keep_warm"]],["DEHYDRATE",["dehydrate"]]],Ji="'Arial Narrow', 'Roboto Condensed', 'Helvetica Neue', Arial, sans-serif",ce={width:5.9,height:12.9,thickness:1.45,pitch:7.05},ra=Math.tan(8*Math.PI/180);function oa(t,e,r){let o=r/2,n=r*.14,a=e/2,i=l=>`M${o+n},${l}l${o},${-o}H${t-r-n}l${o},${o}l${-o},${o}H${r+n}Z`,s=(l,c,d)=>`M${l},${c+n}l${o},${o}V${d-o-n}l${-o},${o}l${-o},${-o}V${c+o+n}Z`;return{a:i(o),g:i(a),d:i(e-o),f:s(o,o,a),b:s(t-o,o,a),e:s(o,a,e-o),c:s(t-o,a,e-o)}}var Yi=oa(ce.width,ce.height,ce.thickness),Xi=oa(3.3,6.6,.85);function na(t,e,r,o,n,a){let i=Qi[n]??"";return p`<g transform=${`translate(${r+e*ra*.5} ${o}) skewX(-8)`}>
    ${Object.entries(t).map(([s,l])=>p`<path d=${l} fill=${a.ink} fill-opacity=${i.includes(s)?1:a.ghost}></path>`)}
  </g>`}function ea(t,e,r,o,n,a){let i=[...(t??"").replace(":","")].slice(-e),s=[...Array(e-i.length).fill(" "),...i],l=a?2.3:0,c=r-(e*ce.pitch-(ce.pitch-ce.width))-l,d=!!t?.includes(":"),m=b=>{let $=c+2*ce.pitch+l/2-.55+(ce.height-b+o)*ra;return p`<path d=${`M${$-.5},${b-.55}h1.1l-0.15,1.1h-1.1Z`} fill=${n.ink} fill-opacity=${d?1:n.ghost}></path>`};return p`
    ${s.map((b,$)=>na(Yi,ce.height,c+$*ce.pitch+(a&&$>=2?l:0),o,b,n))}
    ${a?p`${m(o+ce.height*.33)}${m(o+ce.height*.7)}`:f}
  `}function Z(t,e,r,o,n,a,i,s="start"){return p`<text x=${e} y=${r} font-size=${o} font-family=${Ji} font-weight="700" text-anchor=${s}
    textLength=${n} lengthAdjust="spacingAndGlyphs" fill=${i.ink} fill-opacity=${a?1:i.ghost}>${t}</text>`}function es(t,e,r,o){return p`<g fill=${o.ink} fill-opacity=${r?1:o.ghost}>
    ${[0,120,240].map(n=>p`<path d=${`M${t},${e} c0.2,-0.9 1.3,-1.5 1.6,-0.7 c0.2,0.6 -0.6,1 -1.6,0.7Z`} transform=${`rotate(${n} ${t} ${e})`}></path>`)}
    <circle cx=${t} cy=${e} r="0.35"></circle>
  </g>`}function ts(t,e,r){return p`<g fill="none" stroke=${r.ink} stroke-width="0.45" stroke-linecap="round">
    ${[.9,1.75,2.6].map(o=>p`<path d=${`M${t-o*.72},${e-o*.69} A${o},${o} 0 0 1 ${t+o*.72},${e-o*.69}`}></path>`)}
    <circle cx=${t} cy=${e} r="0.4" fill=${r.ink} stroke="none"></circle>
  </g>`}function aa(t,e,r){let o=ta[e?"black":"brushed"][r===null?"off":r.lit?"lit":"pale"];return p`
    ${_(`${t}-lcd`,[[0,o.screen[0]],[.55,o.screen[1]],[1,o.screen[2]]],[.1,0],[.75,1])}
    ${_(`${t}-lcd-shade`,[[0,o.shade,.75],[.08,o.shade,.2],[.2,o.shade,0]],[0,0],[0,1])}
    ${_(`${t}-lcd-shade-l`,[[0,o.shade,.55],[.06,o.shade,.1],[.15,o.shade,0]])}
    ${_(`${t}-lcd-glare`,[[0,"#ffffff",e?.07:.22],[.45,"#ffffff",e?.03:.08],[.46,"#ffffff",0],[1,"#ffffff",0]],[0,0],[.6,1])}
    ${o.glow?p`<filter id=${`${t}-lcd-glow`} x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="0.6" result="blur"></feGaussianBlur>
          <feMerge><feMergeNode in="blur"></feMergeNode><feMergeNode in="SourceGraphic"></feMergeNode></feMerge>
        </filter>`:f}
  `}function ia(t,e,r){let o=ta[e?"black":"brushed"][r===null?"off":r.lit?"lit":"pale"],n=r!==null,a=n?Xn.findIndex(([,b])=>b.includes(r.mode)):-1,i=1.3,s={x:i,y:i,width:Ie.width-i*2,height:Ie.height-i*2},l=b=>8.6+b*5.17,c=n&&r.convection!=="off",d=n?r.timeUnits:null,m=p`
    ${Xn.map(([b],$)=>Z(b,8,l($),4.1,[...b].length*2.42,$===a,o))}
    ${a>=0?p`<path d=${`M4.6,${l(a)-3.1}l2.4,1.5l-2.4,1.5Z`} fill=${o.ink}></path>`:f}
    ${Z("PREHEATING",61.5,10.2,2.5,15.5,n&&r.prompt==="preheating",o,"end")}
    ${ea(n?r.temp:null,3,55.4,12.9,o,!1)}
    ${Z(n&&r.unit==="C"?"\xB0C":"\xB0F",56.3,16.6,3.6,4.4,n&&r.unit!==null,o)}
    ${Z("SUPER",30.6,31,2.9,9.2,n&&r.convection==="super",o,"end")}
    ${es(34.4,29.8,c,o)}
    ${Z("CONVECTION",37,31,2.9,24.3,c,o)}
    ${ea(n?r.time:null,4,55.4,32.6,o,!0)}
    ${Z(d==="hr_min"?"HR":"MIN",56.3,37.4,2.5,4.6,d!==null,o)}
    ${Z(d==="hr_min"?"MIN":"SEC",56.3,40.6,2.5,4.6,d!==null,o)}
    ${Z("FROZEN",23.4,49.4,2.5,10.8,n&&r.frozen,o)}
    ${Z("SLICES",42,49.4,2.5,9.6,!1,o)}
    ${Z("MY JOULE",31.5,53.2,2.2,10.4,!1,o)}
    ${Z("COOK",34,55.9,2.2,6.2,!1,o)}
    ${n?ts(27.9,56,o):f}
    ${Z("RACK POSITION",33.4,66.6,2.85,22.6,n&&r.rack!==null,o)}
    <path d="M33.2,67.6v1.1h23.6v-1.1" fill="none" stroke=${o.ink} stroke-opacity=${n&&r.rack!==null?1:o.ghost}
      stroke-width="0.4"></path>
    ${na(Xi,6.6,57.3,63.4,n&&r.rack!==null?String(r.rack):" ",o)}
    ${Z("PRESS CONFIRM",5,74.6,2.9,22.5,!1,o)}
    ${Z("PRESS",36.4,74.6,2.9,10.4,n&&r.prompt==="press_start",o)}
    ${Z("START",61.5,74.6,2.9,10.6,n&&r.prompt==="press_start",o,"end")}
  `;return p`<g class="oven-lcd" transform=${`translate(${Ie.x} ${Ie.y})`}>
    <path d=${w(-.5,-.5,Ie.width+1,Ie.height+1,5)} fill="#ffffff" opacity=${e?.12:.45}></path>
    <path d=${w(0,0,Ie.width,Ie.height,4.6)} fill=${o.bezel}></path>
    <path d=${w(s.x,s.y,s.width,s.height,3.6)} fill=${`url(#${t}-lcd)`}></path>
    <g filter=${o.glow&&n?`url(#${t}-lcd-glow)`:f}>${m}</g>
    <path d=${w(s.x,s.y,s.width,s.height,3.6)} fill=${`url(#${t}-lcd-shade)`}></path>
    <path d=${w(s.x,s.y,s.width,s.height,3.6)} fill=${`url(#${t}-lcd-shade-l)`}></path>
    <path d=${w(s.x,s.y,s.width,s.height,3.6)} fill=${`url(#${t}-lcd-glare)`}></path>
  </g>`}var rs="'Arial Narrow', 'Roboto Condensed', 'Helvetica Neue', Arial, sans-serif";function la(t,e,r){return p`
    ${aa(t,e,r.lcd)}
    ${An(`${t}-spun`,.014)}
    <filter id=${`${t}-sink`} x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="0.9"></feGaussianBlur></filter>
    <filter id=${`${t}-ring-glow`} x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="1.6"></feGaussianBlur></filter>
    <radialGradient id=${`${t}-turned`} cx="0.5" cy="0.5" r="0.035" spreadMethod="repeat">
      <stop offset="0" stop-color="#ffffff" stop-opacity="0.05"></stop>
      <stop offset="0.5" stop-color="#000000" stop-opacity="0.05"></stop>
      <stop offset="1" stop-color="#ffffff" stop-opacity="0.05"></stop>
    </radialGradient>
  `}function Fe(t,e,r,o,n,a=72){return p`<g filter=${`url(#${t}-spun)`}>${Tn(e,r,o,n,a)}</g>`}function sa(t,e,r,o,n){return p`
    <circle cx=${e} cy=${r+o*.06} r=${o*.99} fill="#000000" opacity="0.32" filter=${`url(#${t}-sink)`}></circle>
    ${Fe(t,e,r,o*.965,n.dialGroove,48)}
    ${Fe(t,e,r,o*.885,n.dialRim)}
    ${Fe(t,e,r,o*.765,n.dialCap)}
    <circle cx=${e} cy=${r} r=${o*.765} fill=${`url(#${t}-turned)`}></circle>
    <circle cx=${e} cy=${r} r=${o*.765} fill="none" stroke="#000000" stroke-opacity="0.28" stroke-width=${o*.014}></circle>
    <circle cx=${e} cy=${r} r=${o*.878} fill="none" stroke="#ffffff" stroke-opacity="0.4" stroke-width=${o*.012}></circle>
    <circle cx=${e} cy=${r} r=${o*.965} fill="none" stroke="#000000" stroke-opacity="0.35" stroke-width=${o*.016}></circle>
  `}function ca(t,e,r,o,n,a,i,s){let l=a==="red"?{core:"#ff4a3f",body:"#d1242a",edge:"#7d1216",glow:"#ff2a1f"}:{core:"#ffb070",body:"#ea6a3c",edge:"#9c3b26",glow:"#ff7a3a"},c=(o+n)/2,d=n-o;return i?p`<g class=${s?`${t}-pulse`:""}>
    <circle cx=${e} cy=${r} r=${c} fill="none" stroke=${l.glow} stroke-opacity="0.55" stroke-width=${d*2.2}
      filter=${`url(#${t}-ring-glow)`}></circle>
    <circle cx=${e} cy=${r} r=${c} fill="none" stroke=${l.edge} stroke-width=${d}></circle>
    <circle cx=${e} cy=${r} r=${c} fill="none" stroke=${l.body} stroke-width=${d*.72}></circle>
    <circle cx=${e} cy=${r} r=${c-d*.08} fill="none" stroke=${l.core} stroke-width=${d*.3}></circle>
  </g>`:p`
      <circle cx=${e} cy=${r} r=${c} fill="none" stroke="#2c2a29" stroke-opacity="0.75" stroke-width=${d}></circle>
      <circle cx=${e} cy=${r} r=${o+d*.3} fill="none" stroke="#ffffff" stroke-opacity="0.18" stroke-width=${d*.25}></circle>
    `}function os(t,e,r){let{cx:o,cy:n,r:a}=ve.confirm;return p`
    <circle cx=${o} cy=${n+a*.07} r=${a} fill="#000000" opacity="0.35" filter=${`url(#${t}-sink)`}></circle>
    ${Fe(t,o,n,a*.97,e.dialGroove,36)}
    ${Fe(t,o,n,a*.88,e.dialRim,48)}
    ${ca(t,o,n,a*.62,a*.74,"orange",r,!1)}
    ${Fe(t,o,n,a*.62,e.dialCap,48)}
    <circle cx=${o} cy=${n} r=${a*.62} fill="none" stroke="#000000" stroke-opacity="0.3" stroke-width="0.25"></circle>
  `}function ns(t,e,r,o){let{cx:n,cy:a,r:i}=ve.start;return p`
    <circle cx=${n} cy=${a+i*.06} r=${i} fill="#000000" opacity="0.32" filter=${`url(#${t}-sink)`}></circle>
    ${r?f:Fe(t,n,a,i*.97,e.dialRim,48)}
    ${ca(t,n,a,i*.8,i*.97,"red",r,o)}
    ${Fe(t,n,a,i*.8,e.dialCap,48)}
    <circle cx=${n} cy=${a} r=${i*.8} fill="none" stroke="#000000" stroke-opacity="0.3" stroke-width="0.3"></circle>
    <circle cx=${n} cy=${a} r=${i*.985} fill="none" stroke="#000000" stroke-opacity="0.4" stroke-width="0.4"></circle>
  `}function as(t,e,r,o){let n={fill:"none",stroke:o,"stroke-width":.42,"stroke-linecap":"round","stroke-linejoin":"round"};switch(t){case"light":return p`<g fill=${n.fill} stroke=${o} stroke-width=${n["stroke-width"]} stroke-linecap="round">
        <path d=${`M${e-1.1},${r+.9} C${e-2.2},${r-.1} ${e-2.1},${r-2.6} ${e},${r-2.6} C${e+2.1},${r-2.6} ${e+2.2},${r-.1} ${e+1.1},${r+.9} Z`}></path>
        <path d=${`M${e-.9},${r+1.6} h1.8 M${e-.7},${r+2.3} h1.4`}></path>
      </g>`;case"fan":return p`<g fill=${o}>${[0,120,240].map(a=>p`<path d=${`M${e},${r} c0.3,-1.2 1.9,-2 2.3,-0.9 c0.3,0.9 -0.9,1.4 -2.3,0.9Z`} transform=${`rotate(${a} ${e} ${r})`}></path>`)}<circle cx=${e} cy=${r} r="0.45"></circle></g>`;case"more":return p`<g fill="none" stroke=${o} stroke-width=${n["stroke-width"]} stroke-linecap="round">
        <path d=${`M${e+1.9},${r-.6} A2.2,2.2 0 1 0 ${e+.6},${r+2}`}></path>
        <path d=${`M${e-.3},${r-1.2} v1.3 h1`}></path>
        <path d=${`M${e+1.9},${r+.6} v1.8 M${e+1},${r+1.5} h1.8`}></path>
      </g>`;case"frozen":return p`<g fill="none" stroke=${o} stroke-width=${n["stroke-width"]} stroke-linecap="round">
        ${[0,60,120].map(a=>p`<g transform=${`rotate(${a} ${e} ${r})`}>
            <path d=${`M${e},${r-2.4} v4.8 M${e-.6},${r-2} l0.6,0.6 l0.6,-0.6 M${e-.6},${r+2} l0.6,-0.6 l0.6,0.6`}></path>
          </g>`)}
      </g>`;default:return p`<path d=${`M${e},${r+1.9} L${e-1.9},${r} A1.1,1.1 0 0 1 ${e},${r-1.5} A1.1,1.1 0 0 1 ${e+1.9},${r} Z`}
        fill="none" stroke=${o} stroke-width=${n["stroke-width"]} stroke-linejoin="round"></path>`}}function is(t,e,r){let o=ve.buttonX,n=ve.buttonR;return p`
    <circle cx=${o+.15} cy=${t+.35} r=${n+.2} fill="none" stroke="#000000" stroke-opacity="0.18" stroke-width="0.6"></circle>
    <circle cx=${o} cy=${t} r=${n} fill="none" stroke=${r.button[1]} stroke-width="0.45"></circle>
    <path d=${`M${o-n*.93},${t+n*.35} A${n*.99},${n*.99} 0 0 1 ${o+n*.35},${t-n*.93}`} fill="none"
      stroke=${r.button[0]} stroke-opacity="0.85" stroke-width="0.45"></path>
    ${as(e,o,t,r.ink)}
  `}function te(t,e,r,o,n,a,i=700,s="start"){return p`<text x=${e} y=${r} font-size=${o} font-weight=${i} font-family=${rs} text-anchor=${s}
    textLength=${n} lengthAdjust="spacingAndGlyphs" fill=${a}>${t}</text>`}function pa(t,e,r,o,n){let a=r.ink,i=e.lcd!==null,s=!!e.lcd?.lit,{confirm:l,temp:c,time:d}=ve;return p`
    <g class="oven-panel">
      ${ia(t,o,e.lcd)}
      ${te("CONFIRM",l.cx,112.6,2.5,10.4,a,700,"middle")}
      ${te("Rotate Remind",l.cx,115.4,1.45,10.4,a,600,"middle")}
      ${te("START",514.6,114.4,2.5,7.6,a,700,"end")}
      <line x1="515.6" x2="515.6" y1="111.9" y2="114.6" stroke=${a} stroke-width="0.3"></line>
      ${te("STOP",516.6,114.4,2.5,6.2,a)}
      <g fill="none" stroke=${a} stroke-width="0.55" stroke-linecap="round">
        <path d=${`M${l.cx+12.6},${l.cy-8.2} A15,15 0 0 1 ${l.cx+12.6},${l.cy+8.2}`}></path>
        <path d=${`M${l.cx+10.6},${l.cy-9.6} l2,1.4 l-0.5,-2.3`} fill=${a}></path>
        <path d=${`M${l.cx+10.6},${l.cy+9.6} l2,-1.4 l-0.5,2.3`} fill=${a}></path>
        <path d=${`M${l.cx+16.2},${l.cy-1.3} h3 M${l.cx+16.2},${l.cy} h3 M${l.cx+16.2},${l.cy+1.3} h3`} stroke-width="0.45"></path>
      </g>
      ${te("TEMP",457.6,160.8,2.5,6.6,a)}
      <line x1="457.6" x2="473.2" y1="161.9" y2="161.9" stroke=${a} stroke-width="0.3"></line>
      ${te("Darkness",457.6,164.9,1.6,8.6,a,600)}
      ${te("TIME",457.6,229.6,2.5,6.4,a)}
      <line x1="457.6" x2="473.2" y1="230.7" y2="230.7" stroke=${a} stroke-width="0.3"></line>
      ${te("Slices",457.6,233.7,1.6,5.8,a,600)}
      ${te("\xB0F",516.4,157.9,1.6,2.5,a,700)}
      <line x1="516.2" x2="519.4" y1="160.4" y2="158.4" stroke=${a} stroke-width="0.25"></line>
      ${te("\xB0C",517.4,161.6,1.6,2.5,a,700)}
      ${te("A Bit",519.2,218.3,1.35,3.8,a,700,"end")}
      ${te("More",519.2,220.2,1.35,3.8,a,700,"end")}
      ${te("Favorite",ve.buttonX,284.4,1.35,6,a,700,"middle")}
      ${os(t,r,i)}
      ${ns(t,r,s||e.start_prompt,e.start_prompt&&n)}
      ${sa(t,c.cx,c.cy,c.r,r)}
      ${sa(t,d.cx,d.cy,d.r,r)}
      ${ve.buttons.map(({cy:m,icon:b})=>is(m,b,r))}
    </g>
  `}var po=M.width,ss=345;function ls(t){return p`
    <filter id=${`${t}-in-off`} color-interpolation-filters="sRGB">
      <feColorMatrix type="matrix" values="0.24 0 0 0 0.01  0 0.24 0 0 0.01  0 0 0.25 0 0.012  0 0 0 1 0"></feColorMatrix>
    </filter>
    <filter id=${`${t}-in-lamp`} color-interpolation-filters="sRGB">
      <feColorMatrix type="matrix" values="0.86 0.04 0 0 0  0.02 0.76 0 0 0  0 0 0.6 0 0  0 0 0 1 0"></feColorMatrix>
    </filter>
    <filter id=${`${t}-in-heat`} color-interpolation-filters="sRGB">
      <feColorMatrix type="matrix" values="1.02 0.06 0 0 0.01  0.02 0.8 0 0 0  0 0 0.62 0 0  0 0 0 1 0"></feColorMatrix>
    </filter>
  `}function da(t,e,r,o){let n=Jn(t,e.accessory,ao(e.rack)),a=so(e);return p`<g clip-path=${`url(#${t}-${r})`}>
    ${Kn(t,e,o)}
    <g filter=${`url(#${t}-in-${a})`}>
      ${n.back}
      ${e.food?Yn(t,e.food,n.place,e.frozen):f}
      ${n.front}
    </g>
  </g>`}function cs(t){return t.error?p`<g transform="translate(392 72)">
    <circle r="13" fill="#d93025"></circle>
    <rect x="-1.8" y="-7.5" width="3.6" height="9.5" rx="1.6" fill="#ffffff"></rect>
    <circle cy="6" r="2.1" fill="#ffffff"></circle>
  </g>`:f}function ps(t){return yr(`<style>
    .${t}-spin { animation: ${t}-spin var(--${t}-spin, 2s) linear infinite; }
    @keyframes ${t}-spin { to { transform: rotate(360deg); } }
    .${t}-pulse { animation: ${t}-pulse 1.4s ease-in-out infinite; }
    @keyframes ${t}-pulse { 50% { opacity: 0.3; } }
  </style>`)}function ua(t){let e=t.state,{uid:r,theme:o}=t,n=t.finish==="black_stainless",a=En[n?"black_stainless":"brushed_stainless"],i=!t.reducedMotion&&e.available,s=so(e);return h`<svg
    viewBox=${`-14 -4 ${po+28} ${ss+4}`}
    style=${e.available?"":"filter: grayscale(0.9) opacity(0.62)"}
    aria-hidden="true"
    focusable="false"
  >
    <defs>
      ${Dn(r,a)}
      ${Un(r,e)}
      ${Qn(r)}
      ${la(r,n,e)}
      ${ls(r)}
    </defs>
    ${i?ps(r):f}
    ${_r(r,po/2,M.floor+1,po/2+20,7,o)}
    ${Vn(r)}
    ${On(r)}
    ${Bn()}
    ${Nn(r)}
    ${e.door_open?p`${da(r,e,"opening",i)}${Fn()}${In(r)}`:p`${jn(r)}${da(r,e,"window",i)}${Wn(r,s)}${Gn(r)}`}
    ${pa(r,e,a,n,i)}
    ${cs(e)}
  </svg>`}var uo=360,fa=400,g={backTop:150,frontTop:170,backBottom:366,frontBottom:382,topLeft:20,topRight:340,bottomLeft:32,bottomRight:328},N=238,Ae=361,ot=23.5,ds={CSJ100:[[0,"#c9cacd"],[.025,"#e9e9ec"],[.08,"#f7f7f9"],[.32,"#f6f6f8"],[.5,"#dcdde1"],[.7,"#c9cace"],[.84,"#bebfc3"],[.93,"#c6c6c8"],[.975,"#d2d2d4"],[1,"#a7a8ac"]],BSV600:[[0,"#c8c8cc"],[.03,"#e3e3e7"],[.21,"#fdfdff"],[.45,"#f0f0f3"],[.71,"#dcdbe0"],[.88,"#e6e6e9"],[.96,"#fcfcfc"],[1,"#b4b4b8"]]},us=[[0,"#6f6f70"],[.05,"#979797"],[.15,"#a9a9a9"],[.25,"#c4c4c4"],[.33,"#e4e4e4"],[.4,"#f3f3f3"],[.46,"#e0e0e0"],[.53,"#a8a8a8"],[.62,"#b2b2b2"],[.72,"#8a8a8a"],[.8,"#5e5e5e"],[.87,"#4f4f4f"],[.94,"#7d7d7d"],[1,"#5a5a5a"]],fs=[[0,"#3c3c3c"],[.06,"#9a9a9a"],[.15,"#eeeeee"],[.35,"#fbfbfb"],[.5,"#d6d6d6"],[.62,"#8a8a8a"],[.72,"#3a3a3a"],[.82,"#6a6a6a"],[.92,"#d8d8d8"],[1,"#5a5a5a"]];function ms(t){return t.error==="low_water"?.12:.66}function hs(t){return!t.available||t.waterC===null?0:Math.max(0,Math.min(1,(t.waterC-42)/45))}function Sr(t,e){let r=e?g.backTop:g.frontTop,o=e?g.backBottom:g.frontBottom,n=(t-r)/(o-r),a=e?8:0;return[g.topLeft+a+n*(g.bottomLeft-g.topLeft),g.topRight-a-n*(g.topRight-g.bottomRight)]}function Mt(t){let e=ms(t);return{back:g.backBottom-e*(g.backBottom-g.backTop)*.96,front:g.frontBottom-e*(g.frontBottom-g.frontTop)*.96}}function ma(t,e){let r=t.waterC===null?0:Math.max(0,Math.min(1,(t.waterC-30)/60))*.35;return e==="dark"?{edge:"#d7e0e6",water:[$e("#6f8c99","#8f8070",r),$e("#3f5a66","#5a4d40",r)],waterAlpha:[.3,.5],sheen:"#c9d6dc"}:{edge:"#7f8b93",water:[$e("#e6f1f5","#f6eee4",r),$e("#b7d2dd","#e2d3c2",r)],waterAlpha:[.18,.42],sheen:"#ffffff"}}function gs(t,e,r,o){let n=ma(e,r),{back:a,front:i}=Mt(e);return p`
    ${de(`${t}-white`,ds[o])}
    ${de(`${t}-cap`,o==="BSV600"?fs:us)}
    ${_(`${t}-cap-edge`,[[0,"#000000",.55],[.12,"#000000",.08],[.22,"#ffffff",.18],[.4,"#ffffff",0],[.78,"#000000",0],[.92,"#000000",.18],[1,"#000000",.5]],[0,0],[0,1])}
    ${_(`${t}-chrome`,[[0,"#5d6064"],[.12,"#c9ced2"],[.25,"#fbfcfc"],[.42,"#dfe3e4"],[.6,"#8f9497"],[.75,"#e9ecec"],[.9,"#9aa0a3"],[1,"#5a5e62"]])}
    ${_(`${t}-neck`,[[0,"#151617"],[.4,"#35383b"],[.6,"#2a2c2f"],[1,"#0f1011"]])}
    ${_(`${t}-water`,[[0,n.water[0],n.waterAlpha[0]],[1,n.water[1],n.waterAlpha[1]]],[0,i],[0,g.frontBottom],"userSpaceOnUse")}
    ${_(`${t}-sheet`,[[0,n.sheen,r==="dark"?.32:.85],[.45,n.sheen,r==="dark"?.12:.45],[1,n.water[1],r==="dark"?.3:.35]],[0,a],[0,i],"userSpaceOnUse")}
    ${_(`${t}-wall`,[[0,n.edge,.4],[.012,"#ffffff",.75],[.03,n.edge,.18],[.06,"#ffffff",.22],[.2,"#ffffff",.04],[.5,"#ffffff",0],[.86,"#ffffff",.04],[.95,"#ffffff",.2],[.975,n.edge,.2],[.99,"#ffffff",.7],[1,n.edge,.4]])}
    ${_(`${t}-lip`,[[0,"#ffffff",.95],[.25,"#f2f7f9",.55],[.6,n.edge,.12],[.85,n.edge,.35],[1,n.edge,.6]],[0,0],[0,1])}
    ${_(`${t}-bag`,[[0,"#ffffff",.5],[.3,"#ffffff",.16],[.7,"#ffffff",.1],[1,"#ffffff",.32]],[0,0],[0,1])}
    ${le(`${t}-steak`,[[0,"#cc3f37"],[.5,"#ad2b26"],[.85,"#7c1a19"],[1,"#541010"]],[.45,.38],.72)}
    <pattern id=${`${t}-seal`} width="1.6" height="1.6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <path d="M0,0 V1.6" stroke="#ffffff" stroke-opacity="0.7" stroke-width="0.35"></path>
    </pattern>
    ${le(`${t}-led`,[[0,"#e6ffd6"],[.35,"#7ad83a"],[1,"#55c21f",0]])}
    ${_(`${t}-steam`,[[0,r==="dark"?"#ffffff":"#cdd6db",0],[.25,r==="dark"?"#ffffff":"#cdd6db",r==="dark"?.5:.55],[1,r==="dark"?"#ffffff":"#cdd6db",0]],[0,a],[0,a-130],"userSpaceOnUse")}
    <filter id=${`${t}-wisp`} x="-60%" y="-20%" width="220%" height="140%">
      <feTurbulence type="fractalNoise" baseFrequency="0.035 0.06" numOctaves="2" seed="5" result="noise"></feTurbulence>
      <feDisplacementMap in="SourceGraphic" in2="noise" scale="16" xChannelSelector="R" yChannelSelector="G" result="moved"></feDisplacementMap>
      <feGaussianBlur in="moved" stdDeviation="3.4"></feGaussianBlur>
    </filter>
    <filter id=${`${t}-meat`} x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="sRGB">
      <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="13" result="noise"></feTurbulence>
      <feDiffuseLighting in="noise" surfaceScale="0.45" diffuseConstant="1" lighting-color="#ffffff" result="light">
        <feDistantLight azimuth="235" elevation="60"></feDistantLight>
      </feDiffuseLighting>
      <feComposite in="light" in2="SourceGraphic" operator="arithmetic" k1="1.12" k2="0" k3="0" k4="0" result="lit"></feComposite>
      <feComposite in="lit" in2="SourceAlpha" operator="in"></feComposite>
    </filter>
    ${ht(`${t}-glow`,1.2)}
    ${ht(`${t}-soft`,.8)}
    <clipPath id=${`${t}-above`}><rect x="0" y="0" width=${uo} height=${a}></rect></clipPath>
    <clipPath id=${`${t}-below`}><rect x="0" y=${a} width=${uo} height=${fa}></rect></clipPath>
  `}function bs(t,e,r){let n=Ae-(r==="BSV600"?312:279),a=14.5,i=N-ot,s=ot*2,l=n+a,c=Ae-13,d=Ae-62,m=e.available&&e.running,b=r==="BSV600"?p`<g class="marks" fill="#a3a9ae" font-family="inherit" font-size="4.2" font-weight="600">
          ${[[Ae-210,"MAX"],[Ae-52,"MIN"]].map(([$,v])=>p`<line x1=${i+5} x2=${i+12} y1=${$} y2=${$} stroke="#a3a9ae" stroke-width="0.8"></line>
              <text x=${i+14} y=${Number($)+1.5}>${v}</text>`)}
        </g>`:f;return p`
    <!-- The clip on its back: a white moulding with a steel spring, hooked over the back rim. -->
    <g class="clip">
      <path d=${w(N+ot-6,g.backTop-32,12,54,4)} fill="#e9eaec"></path>
      <path d=${w(N+ot-6,g.backTop-32,12,54,4)} fill="none" stroke="#a7acb1" stroke-width="0.6"></path>
      <path d=${`M${N+ot+4},${g.backTop-22} q 10,-7 14,4 v 36`} fill="none" stroke="#9aa0a5" stroke-width="1.8" stroke-linecap="round"></path>
      <path d=${`M${N+ot+4},${g.backTop-22} q 10,-7 14,4 v 36`} fill="none" stroke="#f4f5f6" stroke-width="0.6" stroke-linecap="round"></path>
    </g>
    <!-- The body: glossy white, lit from the left, with a crisp highlight down it. -->
    <rect x=${i} y=${l} width=${s} height=${c-l} fill=${`url(#${t}-white)`}></rect>
    <rect x=${i+s*.13} y=${l+1} width=${s*.05} height=${c-l-2} fill="#ffffff" opacity="0.7"></rect>
    <rect x=${i+s*.86} y=${l+1} width=${s*.025} height=${c-l-2} fill="#ffffff" opacity="0.35"></rect>
    ${b}
    <!-- The outlet: a black slot, its rim catching the light. -->
    <path d=${w(N-4,d-12,8,24,3.6)} fill="#0c0d0e"></path>
    <path d=${w(N-4,d-12,8,24,3.6)} fill="none" stroke="#ffffff" stroke-opacity="0.85" stroke-width="0.6"></path>
    <path d=${w(N-2.6,d-10,2,20,1)} fill="#3b3f44"></path>
    <!-- The cap: polished, the light set in its front. -->
    <path d=${w(i-.4,n,s+.8,a,2.2)} fill=${`url(#${t}-cap)`}></path>
    <path d=${w(i-.4,n,s+.8,a,2.2)} fill=${`url(#${t}-cap-edge)`}></path>
    <line x1=${i+1} x2=${i+s-1} y1=${n+.6} y2=${n+.6} stroke="#ffffff" stroke-opacity="0.55" stroke-width="0.6"></line>
    <line x1=${i} x2=${i+s} y1=${l} y2=${l} stroke="#6f7478" stroke-width="0.6"></line>
    ${m?p`<circle cx=${N} cy=${n+a*.42} r="4.2" fill=${`url(#${t}-led)`} filter=${`url(#${t}-glow)`}></circle>
          <circle cx=${N} cy=${n+a*.42} r="1.2" fill="#eaffdc"></circle>`:p`<circle cx=${N} cy=${n+a*.42} r="1.2" fill="#55595e"></circle>`}
    <!-- The foot: a chrome band, a dark neck, and the magnetic disc with its rubber edge. -->
    <rect x=${i} y=${c} width=${s} height="2.4" fill=${`url(#${t}-chrome)`}></rect>
    <rect x=${N-15} y=${c+2.4} width="30" height="4.4" fill=${`url(#${t}-neck)`}></rect>
    <path d=${w(i+1,c+6.8,s-2,4.6,1.6)} fill=${`url(#${t}-chrome)`}></path>
    <rect x=${i+2} y=${Ae-1.6} width=${s-4} height="1.6" rx="0.8" fill="#9a5f4b"></rect>
  `}function $s(t){let[e,r]=Sr(g.backBottom,!0);return p`
    <path d=${`M${g.topLeft+8},${g.backTop} H${g.topRight-8} L${r},${g.backBottom} H${e} Z`}
      fill="#ffffff" fill-opacity="0.06" stroke=${t.edge} stroke-opacity="0.3" stroke-width="0.7"></path>
    <path d=${`M${e},${g.backBottom} L${g.bottomLeft+2},${g.frontBottom-4} M${r},${g.backBottom} L${g.bottomRight-2},${g.frontBottom-4}`}
      stroke=${t.edge} stroke-opacity="0.3" stroke-width="0.7"></path>
    <path d=${`M${g.topLeft+8},${g.backTop+1.2} H${g.topRight-8}`} stroke=${t.edge} stroke-opacity="0.35" stroke-width="1.4"></path>
  `}var zr=(t,e)=>{let r=Math.sin(t*12.9898+e*78.233)*43758.5453;return r-Math.floor(r)};function vs(t,e){let r=Ae-62,o=Array.from({length:110},(n,a)=>{let i=zr(a,1)**.8,s=(zr(a,2)-.5)*(5+i*30),l=N-5-i*96+(zr(a,3)-.5)*6,c=r+s-i*5,d=.25+zr(a,4)**2*1.1;return p`<circle cx=${u(l)} cy=${u(c)} r=${u(d)} opacity=${u(.95-i*.75)}></circle>`});return p`<g class=${e?`${t}-stream`:""} fill="#ffffff" stroke="#7f939c" stroke-width="0.22">${o}</g>`}function ys(t,e,r,o){let{back:n,front:a}=Mt(e),[i,s]=Sr(n,!0),[l,c]=Sr(a,!1),d=`M${l},${a} H${c} L${g.bottomRight},${g.frontBottom-8} Q${g.bottomRight},${g.frontBottom} ${g.bottomRight-8},${g.frontBottom}
    H${g.bottomLeft+8} Q${g.bottomLeft},${g.frontBottom} ${g.bottomLeft},${g.frontBottom-8} Z`,m=`M${i},${n} H${s} L${c},${a} H${l} Z`,b=e.running&&e.available,$=[.22,.42,.62,.8].map((v,z)=>{let T=n+(a-n)*v,[G,X]=[i+(l-i)*v+6,s+(c-s)*v-6],R=b?1.2:.4,U=(X-G)/8,V=`M${u(G)},${u(T)}`;for(let ye=0;ye<8;ye++)V+=` q${u(U/2)},${u((ye+z)%2?R:-R)} ${u(U)},0`;return p`<path d=${V} fill="none" stroke=${r.edge} stroke-opacity=${b?.22:.12} stroke-width="0.6"></path>`});return p`
    <path d=${d} fill=${`url(#${t}-water)`}></path>
    ${b?vs(t,o):f}
    <path d=${m} fill=${`url(#${t}-sheet)`}></path>
    ${$}
    <path d=${`M${i},${n} H${s}`} stroke="#ffffff" stroke-opacity="0.9" stroke-width="0.8"></path>
    <path d=${`M${i},${n} L${l},${a} M${s},${n} L${c},${a}`} stroke=${r.edge} stroke-opacity="0.35" stroke-width="0.7"></path>
    <path d=${`M${l+1},${a} H${c-1}`} stroke=${r.edge} stroke-opacity="0.75" stroke-width="0.9"></path>
    <path d=${`M${l+2},${a+1.4} H${c-2}`} stroke="#ffffff" stroke-opacity="0.85" stroke-width="1.1"></path>
    <path d=${`M${l+2},${a+3.6} H${c-2}`} stroke=${r.edge} stroke-opacity="0.12" stroke-width="3"></path>
    ${b?p`<g fill="none" stroke="#ffffff" stroke-width="0.8">
          ${[0,1,2].map(v=>p`<ellipse class=${o?`${t}-ripple`:""} style=${`animation-delay:${v*1.1}s`}
              cx=${N} cy=${n+3} rx=${ot+10+v*18} ry=${3+v*2.2} stroke-opacity=${.6-v*.15}></ellipse>`)}
        </g>`:f}
  `}function _s(t,e,r){let{front:o}=Mt(e),n=112,a=Math.max(o+58,300),i=`M${n-46},${a-10} C${n-40},${a-24} ${n+4},${a-27} ${n+38},${a-18}
    C${n+52},${a-12} ${n+52},${a+8} ${n+38},${a+16}
    C${n+12},${a+25} ${n-30},${a+23} ${n-44},${a+12}
    C${n-52},${a+4} ${n-52},${a-4} ${n-46},${a-10} Z`;return p`<g transform=${`rotate(-6 ${n} ${a})`}>
    <path d=${w(n-62,a-37,124,72,8)} fill="#ffffff" fill-opacity="0.18"></path>
    <path d=${i} fill=${`url(#${t}-steak)`} filter=${`url(#${t}-meat)`}></path>
    <path d=${`M${n-43},${a-11} C${n-31},${a-23} ${n+8},${a-25} ${n+37},${a-16}`}
      fill="none" stroke="#f3ddd2" stroke-width="3.4" stroke-linecap="round" opacity="0.9"></path>
    ${[[-32,-3,24,.7],[-8,6,30,.6],[16,-7,20,.55],[-38,9,14,.5],[10,13,18,.6],[-18,-13,13,.45],[26,4,14,.5],[-2,-4,10,.4]].map(([s,l,c,d])=>p`<path d=${`M${n+s},${a+l} q ${c/4},-3 ${c/2},-0.5 t ${c/2},1.5`} fill="none"
        stroke="#f1d3c8" stroke-opacity="0.6" stroke-width=${d} stroke-linecap="round"></path>`)}
    <path d=${w(n-62,a-37,124,72,8)} fill=${`url(#${t}-bag)`}></path>
    <path d=${w(n-62,a-37,124,72,8)} fill="none" stroke=${r.edge} stroke-opacity="0.55" stroke-width="1.2"></path>
    <path d=${w(n-60.5,a-35.5,121,69,7)} fill="none" stroke="#ffffff" stroke-opacity="0.85" stroke-width="0.7"></path>
    <path d=${w(n-62,a-37,124,10,4)} fill="#ffffff" fill-opacity="0.4"></path>
    <path d=${w(n-60,a-35.5,120,7,3)} fill=${`url(#${t}-seal)`}></path>
    <line x1=${n-60} x2=${n+60} y1=${a-27.5} y2=${a-27.5} stroke=${r.edge} stroke-opacity="0.35" stroke-width="0.5"></line>
    <g fill="none" stroke="#ffffff" stroke-linecap="round" filter=${`url(#${t}-soft)`}>
      <path d=${`M${n-45},${a-15} C${n-30},${a-27} ${n+10},${a-29} ${n+40},${a-21}`} stroke-opacity="0.9" stroke-width="1.8"></path>
      <path d=${`M${n+47},${a-8} C${n+54},${a-2} ${n+52},${a+10} ${n+42},${a+17}`} stroke-opacity="0.6" stroke-width="1.2"></path>
      <path d=${`M${n-53},${a-2} q -3,9 2,16`} stroke-opacity="0.6" stroke-width="1"></path>
      <path d=${`M${n-24},${a+25} q 16,4 34,-1`} stroke-opacity="0.5" stroke-width="1"></path>
    </g>
  </g>`}function ks(t,e){let r=`M${g.topLeft},${g.frontTop} H${g.topRight} L${g.bottomRight},${g.frontBottom-8}
    Q${g.bottomRight},${g.frontBottom} ${g.bottomRight-8},${g.frontBottom} H${g.bottomLeft+8}
    Q${g.bottomLeft},${g.frontBottom} ${g.bottomLeft},${g.frontBottom-8} Z`,o=[2,4,6,8,10,12].map(n=>{let a=g.frontBottom-12-n/12*(g.frontBottom-g.frontTop-34),[i]=Sr(a,!1),s=i+16;return p`
      <line x1=${s} x2=${s+(n%4?6:10)} y1=${u(a+.5)} y2=${u(a+.5)} stroke=${e.edge} stroke-opacity="0.35" stroke-width="0.6"></line>
      <line x1=${s} x2=${s+(n%4?6:10)} y1=${u(a)} y2=${u(a)} stroke="#ffffff" stroke-opacity="0.8" stroke-width="0.6"></line>
      ${n%4?f:p`<text x=${s+12} y=${u(a+1.6)} font-size="4.4" font-weight="600" fill=${e.edge} fill-opacity="0.45">${n}</text>`}
    `});return p`
    <path d=${r} fill=${`url(#${t}-wall)`}></path>
    <path d=${r} fill="none" stroke=${e.edge} stroke-opacity="0.5" stroke-width="0.9"></path>
    <path d=${`M${g.bottomLeft+10},${g.frontBottom-2.2} H${g.bottomRight-10}`} stroke=${e.edge} stroke-opacity="0.35" stroke-width="2.2"></path>
    <path d=${`M${g.bottomLeft+10},${g.frontBottom-4} H${g.bottomRight-10}`} stroke="#ffffff" stroke-opacity="0.55" stroke-width="0.8"></path>
    <g font-family="inherit">${o}</g>
    <!-- The rim: the back edge, the sides of the opening, and the thick front lip. -->
    <path d=${`M${g.topLeft+6},${g.backTop} H${g.topRight-6} M${g.topLeft+6},${g.backTop} L${g.topLeft-3},${g.frontTop-2} M${g.topRight-6},${g.backTop} L${g.topRight+3},${g.frontTop-2}`}
      stroke=${e.edge} stroke-opacity="0.55" stroke-width="2.4" stroke-linecap="round"></path>
    <path d=${`M${g.topLeft+6},${g.backTop-.8} H${g.topRight-6}`} stroke="#ffffff" stroke-opacity="0.8" stroke-width="0.7"></path>
    <path d=${w(g.topLeft-5,g.frontTop-6,g.topRight-g.topLeft+10,11,5)} fill=${`url(#${t}-lip)`}></path>
    <path d=${w(g.topLeft-5,g.frontTop-6,g.topRight-g.topLeft+10,11,5)} fill="none" stroke=${e.edge}
      stroke-opacity="0.55" stroke-width="0.7"></path>
    <path d=${`M${g.topLeft},${g.frontTop-4.2} H${g.topRight}`} stroke="#ffffff" stroke-opacity="0.95" stroke-width="1.1" stroke-linecap="round"></path>
    <path d=${`M${g.topLeft+10},${g.frontTop+12} L${g.bottomLeft+7},${g.frontBottom-16}`}
      stroke="#ffffff" stroke-opacity="0.5" stroke-width="3" stroke-linecap="round" filter=${`url(#${t}-soft)`}></path>
    <path d=${`M${g.topRight-13},${g.frontTop+16} L${g.bottomRight-11},${g.frontBottom-40}`}
      stroke="#ffffff" stroke-opacity="0.3" stroke-width="1.8" stroke-linecap="round" filter=${`url(#${t}-soft)`}></path>
  `}function ws(t,e,r){let o=hs(e);if(o<=0)return f;let{back:n}=Mt(e),a=3+Math.round(o*5),i=Array.from({length:a},(s,l)=>{let c=62+l*53%236,d=55+o*55,m=l%2?10:-10;return p`<path class=${r?`${t}-wisp`:""} style=${`animation-delay:${l*.9%4}s`}
      d=${`M${c},${n-2} c ${m},-${d*.3} ${-m},-${d*.6} ${m*.5},-${d}`}
      fill="none" stroke=${`url(#${t}-steam)`} stroke-width=${10+o*8} stroke-linecap="round"
      opacity=${u(.25+o*.35)}></path>`});return p`<g filter=${`url(#${t}-wisp)`}>${i}</g>`}function xs(t,e,r,o){if(!e.readout||!e.available)return f;let n=Cn(r,o,12.5),a=e.targetReadout?`${e.readout} \u2192 ${e.targetReadout}`:e.readout,i=n*(.62*[...a].length+1.6),s=n*1.75,l=100-i/2,c=g.frontTop+(Mt(e).front-g.frontTop)/2-s/2+4;return p`<g class=${`${t}-readout`}>
    <path d=${w(l,c,i,s,s/2)} fill="#101418" fill-opacity="0.62"></path>
    <text x=${l+i/2} y=${c+s*.68} text-anchor="middle" fill="#ffffff" font-size=${n}
      font-weight="600" font-family="inherit" style="font-variant-numeric: tabular-nums">${a}</text>
  </g>`}function zs(t){if(!t.error)return f;let e=t.error==="low_water"?"#e69500":"#d93025";return p`<g transform="translate(318 118)">
    <circle r="13" fill=${e}></circle>
    <rect x="-1.8" y="-7.5" width="3.6" height="9.5" rx="1.6" fill="#ffffff"></rect>
    <circle cy="6" r="2.1" fill="#ffffff"></circle>
  </g>`}function Ss(t){return yr(`<style>
    .${t}-ripple { transform-box: fill-box; transform-origin: center; animation: ${t}-ripple 3.3s ease-out infinite; }
    @keyframes ${t}-ripple { from { transform: scale(0.6); opacity: 0.9; } to { transform: scale(1.25); opacity: 0; } }
    .${t}-stream { animation: ${t}-stream 1.4s linear infinite; }
    @keyframes ${t}-stream { from { transform: translateX(6px); opacity: 0.6; } 50% { opacity: 1; } to { transform: translateX(-10px); opacity: 0.6; } }
    .${t}-wisp { animation: ${t}-wisp 4.5s ease-in-out infinite; }
    @keyframes ${t}-wisp { 0% { transform: translateY(6px); opacity: 0; } 30% { opacity: 1; } 100% { transform: translateY(-18px); opacity: 0; } }
  </style>`)}function ha(t){let e=t.state,{uid:r,theme:o}=t,n=t.model==="BSV600"?"BSV600":"CSJ100",a=!t.reducedMotion&&e.available,i=ma(e,o),s=e.error==="tipped",l=bs(r,e,n),c=s?p`<g transform=${`translate(80 -12) rotate(-90 ${N} ${Ae})`}>${l}</g>`:l,m=Math.min(Ae-(n==="BSV600"?312:279)-6,40),b=fa-m;return h`<svg
    viewBox=${`0 ${m} ${uo} ${b}`}
    class=${e.available?"":"offline"}
    style=${e.available?"":"filter: grayscale(0.9) opacity(0.62)"}
    aria-hidden="true"
    focusable="false"
  >
    <defs>${gs(r,e,o,n)}</defs>
    ${a?Ss(r):f}
    ${_r(r,180,g.frontBottom+3,172,7,o)}
    ${$s(i)}
    ${s?c:p`<g clip-path=${`url(#${r}-above)`}>${c}</g>
          <g clip-path=${`url(#${r}-below)`}><g transform=${`translate(${N} 0) scale(1.07 1) translate(${-N} 0)`}>${c}</g></g>`}
    ${e.food?_s(r,e,i):f}
    ${ys(r,e,i,a)}
    ${ks(r,i)}
    ${ws(r,e,a)}
    ${xs(r,e,b,t.pixelHeight)}
    ${zs(e)}
  </svg>`}function ga(t){return t.state.kind==="oven"?ua(t):ha(t)}var fo=new Set,As=200;function J(t,e,r){try{return e()}catch(o){let n=`${t}: ${String(o)}`;return!fo.has(n)&&fo.size<As&&(fo.add(n),console.error(`Breville+ panel: ${t} failed`,o)),r}}function mo(t){return t.kind==="oven"?{kind:"oven",available:t.available,mode:"bake",rack:6,accessory:"roasting_pan",food:null,frozen:!1,elements:null,fan:"off",door_open:!1,light:!1,lcd:null,start_prompt:!1,error:!1}:{kind:"sous_vide",available:t.available,running:!1,heating:!1,food:!1,waterC:null,readout:null,targetReadout:null,error:null}}function ba(t,e,r,o,n){let a=ct(t),i=pt(t,e,r,o,n),s=d=>`${t.kind} ${d} for ${t.device_id}`,l=J(s("drawing state"),()=>a.drawingState(i),mo(t)),c=J(s("description"),()=>a.describe(i),t.product);return t.available?{status:J(s("status"),()=>a.status(i),{text:"",tone:"neutral"}),rows:J(s("info rows"),()=>a.infoRows(i),[]),display:J(s("display"),()=>a.display(i),null),state:l,description:c}:{status:{text:r("status.offline"),tone:"gray"},rows:J(s("info rows"),()=>a.infoRows(i),[]),display:null,state:{...l,available:!1},description:c}}function Ts(){try{return typeof matchMedia=="function"&&matchMedia("(prefers-reduced-motion: reduce)").matches}catch{return!1}}function Ar(t,e,r,o,n){return{uid:o,model:t.model,finish:t.finish,state:t.available?e:{...e,available:!1},theme:r?.themes?.darkMode?"dark":"light",reducedMotion:Ts(),...n?{pixelHeight:n}:{}}}function Tr(t){return J(`${t.state.kind} drawing`,()=>ga(t),f)}var $a=P`
  :host {
    display: block;
    color: var(--bc-text, var(--primary-text-color, #1f2328));
    font-size: 14px;
    line-height: 1.35;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px 16px;
    min-height: 40px;
  }
  /* One column that never wraps: a wrapping column sizes its height from its content's narrowest
     layout, which for the mode tiles is one tile per row. */
  .row.stacked {
    flex-direction: column;
    flex-wrap: nowrap;
    align-items: stretch;
  }
  /* In a column the flex basis would be a height, so stacked parts take their own. */
  .row.stacked .text,
  .row.stacked .widget {
    flex: none;
  }
  .text {
    display: flex;
    flex: 1 1 9em;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .title {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
  }
  .label {
    font-weight: 500;
  }
  /* Still read out: the label of a quiet control, and a reason the section shows once. */
  :host([quiet]) .row.stacked .label,
  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }
  .aside {
    color: var(--bc-muted, #6b7178);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .hint {
    color: var(--bc-muted, #6b7178);
    font-size: 12.5px;
    white-space: pre-line;
  }
  .widget {
    display: flex;
    flex: 0 1 auto;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    max-width: 100%;
  }
  .reason,
  .error {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    margin-top: 6px;
    font-size: 12.5px;
  }
  .reason {
    color: var(--bc-muted, #6b7178);
  }
  .reason svg {
    flex: none;
    width: 14px;
    height: 14px;
    margin-top: 1px;
    fill: currentColor;
  }
  .error {
    color: var(--bc-error-text, #b3261e);
  }
  .ask {
    margin-top: 8px;
  }
  .link {
    display: inline-block;
    margin-top: 4px;
    font-size: 12.5px;
    font-weight: 500;
    color: var(--bc-accent, #03a9f4);
  }

  /* A small ring while a call is in flight. */
  .spinner {
    flex: none;
    width: 16px;
    height: 16px;
    box-sizing: border-box;
    border: 2px solid var(--bc-control-bg, rgba(127, 127, 127, 0.25));
    border-top-color: var(--bc-accent, #03a9f4);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  /* Choices as separate chips, the chosen one filled: the same whether they fit beside the label
     or wrap under it, and the same as the timer presets. */
  .segmented {
    display: inline-flex;
    flex-wrap: wrap;
    gap: 6px;
    max-width: 100%;
  }
  .segmented button {
    flex: 0 0 auto;
    min-height: 40px;
    padding: 6px 14px;
    border: none;
    border-radius: 999px;
    background: var(--bc-control-bg, rgba(127, 127, 127, 0.14));
    color: inherit;
    font: inherit;
    font-size: 13.5px;
    font-weight: 600;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
    transition: background-color 0.15s, color 0.15s;
  }
  .segmented button:hover:not([aria-disabled="true"]):not([aria-pressed="true"]) {
    background: var(--bc-control-hover, rgba(127, 127, 127, 0.2));
  }
  .segmented button[aria-pressed="true"] {
    background: var(--bc-accent-fill, var(--bc-accent, #03a9f4));
    color: var(--bc-on-accent, #ffffff);
  }
  .segmented button:disabled,
  .segmented button[aria-disabled="true"] {
    cursor: default;
  }
  .segmented.disabled {
    opacity: 0.55;
  }

  /* The oven's modes: a grid of tiles, the chosen one filled. */
  /* A block, not a flex row, around the grid: a flex row sizes its height from the grid's
     narrowest layout (one tile per row), then centres the real grid in all that height. */
  .widget:has(> .tiles) {
    display: block;
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(118px, 1fr));
    gap: 6px;
    width: 100%;
  }
  .tile {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 44px;
    padding: 6px 10px;
    box-sizing: border-box;
    border-radius: 12px;
    background: var(--bc-control-bg, rgba(127, 127, 127, 0.14));
    font-size: 13.5px;
    font-weight: 600;
    line-height: 1.2;
    text-align: center;
    cursor: pointer;
    user-select: none;
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
    transition: background-color 0.15s, color 0.15s;
  }
  .tile:hover:not([aria-selected="true"]) {
    background: var(--bc-control-hover, rgba(127, 127, 127, 0.2));
  }
  .tile[aria-selected="true"] {
    background: var(--bc-accent-fill, var(--bc-accent, #03a9f4));
    color: var(--bc-on-accent, #ffffff);
  }
  .tile:focus-visible {
    outline: 2px solid var(--bc-accent, #03a9f4);
    outline-offset: 2px;
  }
  .tiles.disabled .tile {
    opacity: 0.55;
    cursor: default;
  }
  .tiles.disabled .tile:hover:not([aria-selected="true"]) {
    background: var(--bc-control-bg, rgba(127, 127, 127, 0.14));
  }
  .custom label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: var(--bc-muted, #6b7178);
  }
  .custom input[type="number"] {
    width: 4.5em;
  }

  /* The dropdown for more than five choices. */
  .dropdown {
    position: relative;
    display: inline-flex;
    max-width: 100%;
  }
  .dropdown select {
    max-width: 100%;
    min-height: 40px;
    padding: 7px 36px 7px 14px;
    border: none;
    border-radius: 999px;
    background: var(--bc-control-bg, rgba(127, 127, 127, 0.14));
    color: inherit;
    font: inherit;
    font-size: 14px;
    font-weight: 600;
    text-overflow: ellipsis;
    cursor: pointer;
    -webkit-appearance: none;
    appearance: none;
  }
  /* Locked but focusable: it doesn't open, by pointer or key (see BcSelect). */
  .dropdown select[aria-disabled="true"] {
    opacity: 0.55;
    cursor: default;
    pointer-events: none;
  }
  .dropdown svg {
    position: absolute;
    top: 50%;
    right: 12px;
    width: 18px;
    height: 18px;
    margin-top: -9px;
    fill: currentColor;
    pointer-events: none;
  }

  /* An on/off switch, in the same blue as a chosen chip. */
  .switch {
    position: relative;
    flex: none;
    width: 48px;
    height: 28px;
    padding: 0;
    border: none;
    border-radius: 999px;
    background: var(--bc-switch-off, rgba(127, 127, 127, 0.5));
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
    transition: background-color 0.2s;
  }
  /* A 56 × 44 target for fingers around the smaller switch. */
  .switch::before {
    content: "";
    position: absolute;
    inset: -8px -4px;
  }
  .switch::after {
    content: "";
    position: absolute;
    top: 3px;
    left: 3px;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: #ffffff;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
    transition: transform 0.2s;
  }
  .switch[aria-checked="true"] {
    background: var(--bc-accent-fill, var(--bc-accent, #03a9f4));
  }
  .switch[aria-checked="true"]::after {
    transform: translateX(20px);
  }
  /* A switch whose entity has no state yet: neither on nor off. */
  .switch.unknown::after {
    transform: translateX(10px);
  }
  .switch:disabled,
  .switch[aria-disabled="true"] {
    opacity: 0.5;
    cursor: default;
  }

  /* Minus, the value, plus. */
  .stepper {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    padding: 3px;
    border-radius: 999px;
    background: var(--bc-control-bg, rgba(127, 127, 127, 0.14));
  }
  .stepper button {
    display: grid;
    place-items: center;
    width: 40px;
    height: 40px;
    padding: 0;
    border: none;
    border-radius: 50%;
    background: transparent;
    color: inherit;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
  }
  .stepper button:hover:not(:disabled):not([aria-disabled="true"]) {
    background: var(--bc-control-hover, rgba(127, 127, 127, 0.2));
  }
  .stepper button:disabled,
  .stepper button[aria-disabled="true"] {
    opacity: 0.35;
    cursor: default;
  }
  .stepper svg {
    width: 20px;
    height: 20px;
    fill: currentColor;
  }
  .stepper output {
    min-width: 4.2em;
    font-size: 17px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    text-align: center;
  }
  /* On the stepper's grey, the muted color falls short of 4.5:1; the text color, softened, doesn't. */
  .stepper output .unit {
    margin-inline-start: 1px;
    font-size: 13px;
    font-weight: 500;
    color: color-mix(in srgb, var(--bc-text, #1f2328) 72%, transparent);
  }
  /* No setpoint, like a blank display. */
  .stepper output.empty {
    color: var(--bc-muted, #6b7178);
    font-weight: 500;
    letter-spacing: 0.06em;
  }
  .stepper.draft output {
    color: var(--bc-accent, #03a9f4);
  }

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .chips .bc-button {
    min-height: 40px;
    padding: 6px 14px;
    font-size: 13.5px;
  }
  .chips .bc-button[aria-pressed="true"] {
    background: var(--bc-accent-fill, var(--bc-accent, #03a9f4));
    color: var(--bc-on-accent, #ffffff);
  }

  .reading {
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    text-align: end;
  }
  /* Text tokens, not the raw tones: amber and red text need more ink to reach 4.5:1. */
  .reading[data-tone="warning"] {
    color: var(--bc-warning-text, #8a5a00);
  }
  .reading[data-tone="alert"] {
    color: var(--bc-error-text, #b3261e);
  }

  input[type="number"],
  input[type="time"] {
    min-height: 40px;
    box-sizing: border-box;
    padding: 6px 12px;
    border: 1px solid var(--bc-divider, rgba(127, 127, 127, 0.35));
    border-radius: 10px;
    background: transparent;
    color: inherit;
    font: inherit;
    font-variant-numeric: tabular-nums;
  }
  input[type="number"] {
    width: 6em;
  }

  .slider {
    display: grid;
    grid-template-columns: minmax(6em, auto) 1fr 4.2em;
    align-items: center;
    gap: 12px;
  }
  .slider span {
    color: var(--bc-muted, #6b7178);
    font-size: 13px;
  }
  .slider output {
    font-variant-numeric: tabular-nums;
    text-align: end;
  }
  /* Both sliders share a track and a thumb: brightness fills its track with the accent up to the
     value, white temperature shows its warm-to-cool range. */
  input[type="range"] {
    width: 100%;
    min-width: 0;
    height: 8px;
    margin: 0;
    border-radius: 999px;
    background: linear-gradient(
      90deg,
      var(--bc-accent-fill, var(--bc-accent, #03a9f4)) var(--filled, 0%),
      var(--bc-control-bg, rgba(127, 127, 127, 0.14)) var(--filled, 0%)
    );
    cursor: pointer;
    -webkit-appearance: none;
    appearance: none;
  }
  input[type="range"].kelvin {
    background: linear-gradient(90deg, #ffb46b, #fff4e6 55%, #d6e6ff);
    box-shadow: inset 0 0 0 1px var(--bc-inset-edge, rgba(0, 0, 0, 0.08));
  }
  input[type="range"]::-moz-range-track {
    background: transparent;
  }
  input[type="range"]::-webkit-slider-thumb {
    width: 20px;
    height: 20px;
    border: 2px solid #ffffff;
    border-radius: 50%;
    background: var(--bc-accent-fill, var(--bc-accent, #03a9f4));
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
    -webkit-appearance: none;
    appearance: none;
  }
  input[type="range"]::-moz-range-thumb {
    width: 16px;
    height: 16px;
    border: 2px solid #ffffff;
    border-radius: 50%;
    background: var(--bc-accent-fill, var(--bc-accent, #03a9f4));
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
  }
  input[type="range"]:disabled {
    opacity: 0.5;
    cursor: default;
  }

  button:focus-visible,
  select:focus-visible,
  input:focus-visible {
    outline: 2px solid var(--bc-accent, #03a9f4);
    outline-offset: 2px;
  }

  /* Bigger targets wherever there's a finger: touch laptops report a mouse as their main pointer. */
  @media (any-pointer: coarse) {
    .segmented button,
    .tile,
    .chips .bc-button,
    .dropdown select,
    input[type="number"],
    input[type="time"] {
      min-height: 44px;
    }
    .stepper button {
      width: 44px;
      height: 44px;
    }
    input[type="range"]::-webkit-slider-thumb {
      width: 24px;
      height: 24px;
    }
    input[type="range"]::-moz-range-thumb {
      width: 20px;
      height: 20px;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .spinner {
      animation-duration: 2.4s;
    }
    .switch,
    .switch::after,
    .segmented button {
      transition: none;
    }
  }
`;var va="bc-value",Cs=2500,Ms=qt("en"),Ue={minus:p`<path d="M5 11h14v2H5z" />`,plus:p`<path d="M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6z" />`,chevron:p`<path d="M7.4 8.6 12 13.2l4.6-4.6L18 10l-6 6-6-6z" />`,lock:p`<path d="M12 2a5 5 0 0 0-5 5v3H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-1V7a5 5 0 0 0-5-5Zm-3 8V7a3 3 0 0 1 6 0v3H9Z" />`};function Ke(t){return h`<svg viewBox="0 0 24 24" aria-hidden="true">${t}</svg>`}var H=class extends E{constructor(){super(),this.t=Ms,this.pending=!1,this.error=null,this.sharedReason=!1,this.optimistic=void 0}disconnectedCallback(){super.disconnectedCallback(),clearTimeout(this.settleTimer)}current(){return this.control&&"value"in this.control?this.control.value:void 0}willUpdate(e){this.optimistic!==void 0&&(e.has("control")&&Ps(this.current(),this.optimistic)||e.has("error")&&this.error)&&this.clearOptimistic()}updated(e){e.has("pending")&&e.get("pending")===!0&&!this.pending&&this.optimistic!==void 0&&(clearTimeout(this.settleTimer),this.settleTimer=setTimeout(()=>this.clearOptimistic(),Cs))}clearOptimistic(){clearTimeout(this.settleTimer),this.settleTimer=void 0,this.optimistic=void 0}send(e){clearTimeout(this.settleTimer),this.optimistic=e,this.emit(e)}emit(e){this.dispatchEvent(new CustomEvent(va,{detail:{value:e},bubbles:!0,composed:!0}))}get disabled(){return!!this.control?.disabled}get locked(){return this.disabled?"true":f}describedBy(e=this.control?.hint??null){let r=[e?"hint":null,this.reason()?"reason":null].filter(Boolean);return r.length?r.join(" "):f}reason(){return this.control?.disabled&&this.control.reason||null}frame(e,r={}){return h`${this.head(e,r)}${this.errorLine()}`}head(e,r={}){let o=this.control;if(!o)return h``;let n=r.hint===void 0?o.hint:r.hint,a=this.reason();return h`
      <div class="row ${r.stacked?"stacked":""}">
        <div class="text">
          <div class="title">
            <span class="label" id="label">${o.label}</span>
            ${r.aside?h`<span class="aside">${r.aside}</span>`:f}
          </div>
          ${n?h`<span class="hint" id="hint">${n}</span>`:f}
        </div>
        <div class="widget">
          ${this.pending?h`<span class="spinner" role="progressbar" aria-label=${this.t("ctl.saving")}></span>`:f}
          ${e}
        </div>
      </div>
      ${a?h`<div class="reason ${this.sharedReason?"visually-hidden":""}" id="reason">
            ${Ke(Ue.lock)}<span>${a}</span>
          </div>`:f}
      ${o.disabled&&o.link?h`<a class="link" href=${o.link.href} @click=${Xt}>${o.link.text}</a>`:f}
    `}errorLine(){return this.error?h`<div class="error" role="alert">${this.error}</div>`:f}};H.properties={control:{attribute:!1},t:{attribute:!1},pending:{type:Boolean,reflect:!0},error:{attribute:!1},sharedReason:{attribute:!1},optimistic:{state:!0}},H.styles=[ie,$a];function Ps(t,e){return t===e?!0:typeof t=="object"&&typeof e=="object"&&t!==null&&e!==null&&JSON.stringify(t)===JSON.stringify(e)}function Y(t,e){customElements.get(t)||customElements.define(t,e)}var Pt=class extends H{constructor(){super();this.onKey=r=>{r.key==="Escape"&&this.asking&&(r.stopPropagation(),this.answer(!1))};this.asking=!1}async press(){if(!(this.disabled||this.pending)){if(!this.control?.confirm){this.emit(void 0);return}this.asking=!0,await this.updateComplete,this.renderRoot.querySelector(".confirm .bc-button")?.focus()}}answer(r){this.asking=!1,r&&!this.disabled&&this.emit(void 0),this.updateComplete.then(()=>this.renderRoot.querySelector(".row .bc-button")?.focus())}render(){let r=this.control;if(!r)return f;let o=r.tone==="danger"?"danger":r.tone==="primary"?"primary":"";return h`<div @keydown=${this.onKey}>
      ${this.head(h`<button
        type="button"
        class="bc-button ${this.asking?"":o}"
        aria-expanded=${r.confirm?this.asking?"true":"false":f}
        aria-disabled=${(this.disabled||this.pending)&&!this.asking?"true":f}
        aria-describedby=${this.describedBy()}
        ?disabled=${this.asking}
        @click=${()=>this.press()}
      >
        ${r.button}
      </button>`)}
      ${this.asking&&r.confirm?h`<div class="ask">
            ${Tt({text:r.confirm,confirm:r.button,cancel:this.t("ctl.not_now"),tone:r.tone==="danger"?"danger":"primary",busy:this.pending,onConfirm:()=>this.answer(!0),onCancel:()=>this.answer(!1)})}
          </div>`:f}
      ${this.errorLine()}
    </div>`}};Pt.properties={asking:{state:!0}},Pt.styles=[...H.styles,je];Y("bc-action",Pt);var ho=P`
  .row {
    min-height: 0;
  }
`,Cr=class extends H{render(){let e=this.control;return e?this.frame(h`<span class="reading" data-tone=${e.tone??"normal"}>${e.value}</span>`):f}};Cr.styles=[...H.styles,ho];Y("bc-reading",Cr);var Mr=class extends H{constructor(){super(...arguments);this.tick=()=>{this.requestUpdate(),this.timer=setTimeout(this.tick,1e3-Date.now()%1e3+5)}}connectedCallback(){super.connectedCallback(),this.tick()}disconnectedCallback(){super.disconnectedCallback(),clearTimeout(this.timer),this.timer=void 0}render(){let r=this.control;if(!r)return f;let o=r.end!==null?r.end-Date.now():r.seconds!==null?r.seconds*1e3:null;return this.frame(h`<span class="reading" role="timer" aria-live="off">${o===null?"\u2014":Ye(o)}</span>`)}};Mr.styles=[...H.styles,ho];Y("bc-countdown",Mr);var Pr=class extends H{constructor(){super();this.onSubmit=r=>{r.preventDefault();let o=r.currentTarget,n=o.querySelector("input[name=hours]"),a=o.querySelector("input[name=minutes]");if(!n||!a||!n.checkValidity()||!a.checkValidity()){(n?.checkValidity()===!1?n:a)?.reportValidity();return}let i=Number(n.value||0)*60+Number(a.value||0),s=this.control;if(s&&(i<s.min||i>s.max)){a.setCustomValidity(this.t("ctl.out_of_range",{min:this.minutes(s.min),max:this.minutes(s.max)})),a.reportValidity(),a.setCustomValidity("");return}this.choose(i)};this.custom=!1}value(){return typeof this.optimistic=="number"?this.optimistic:this.control?.value??null}choose(r){let o=this.control;if(!o||this.disabled||!Number.isFinite(r))return;let n=Math.min(o.max,Math.max(o.min,Math.round(r)));this.custom=!1,n!==this.value()&&this.send(n)}minutes(r){return r===0?this.control?.zero??this.t("ctl.off"):ge(this.t,r*60)}render(){let r=this.control;if(!r)return f;let o=this.value(),n=[...new Set(r.presets)].filter(d=>d>=r.min&&d<=r.max),a=o!==null&&!n.includes(o),i=this.disabled,s=this.describedBy(),l=o===null?"":String(Math.floor(o/60)),c=o===null?"":String(o%60);return this.frame(h`<div class="chips" role="group" aria-labelledby="label">
          ${n.map(d=>h`<button
              type="button"
              class="bc-button"
              aria-pressed=${d===o?"true":"false"}
              aria-disabled=${this.locked}
              aria-describedby=${s}
              @click=${()=>this.choose(d)}
            >
              ${this.minutes(d)}
            </button>`)}
          <button
            type="button"
            class="bc-button"
            aria-pressed=${a?"true":"false"}
            aria-expanded=${this.custom&&!i?"true":"false"}
            aria-disabled=${this.locked}
            aria-describedby=${s}
            @click=${()=>{this.disabled||(this.custom=!this.custom)}}
          >
            ${this.t("ctl.custom")}
          </button>
        </div>
        ${this.custom&&!i?h`<form class="chips custom" @submit=${this.onSubmit}>
              <label
                ><input
                  name="hours"
                  type="number"
                  inputmode="numeric"
                  min="0"
                  max=${Math.floor(r.max/60)}
                  step="1"
                  .value=${l}
                  aria-label=${this.t("ctl.hours")}
                /><span aria-hidden="true">${this.t("ctl.h")}</span></label
              >
              <label
                ><input
                  name="minutes"
                  type="number"
                  inputmode="numeric"
                  min="0"
                  max="59"
                  step="1"
                  .value=${c}
                  aria-label=${this.t("ctl.minutes")}
                /><span aria-hidden="true">${this.t("ctl.min")}</span></label
              >
              <button type="submit" class="bc-button primary">${this.t("ctl.set")}</button>
            </form>`:f}`,{stacked:!0,aside:o===null?null:this.minutes(o)})}};Pr.properties={custom:{state:!0}};Y("bc-duration",Pr);var Rs=5,Es=new Set(["ArrowUp","ArrowDown","ArrowLeft","ArrowRight","Home","End","PageUp","PageDown"]);function ya(t){return t.altKey||t.ctrlKey||t.metaKey?!1:Es.has(t.key)||t.key!==" "&&[...t.key].length===1}function Ls(t){return t.altKey&&(t.key==="ArrowDown"||t.key==="ArrowUp")||t.key===" "||t.key==="Enter"||t.key==="F4"}var go=class extends H{constructor(){super(...arguments);this.onKey=r=>{let o=r.currentTarget;if(this.disabled){(ya(r)||Ls(r))&&r.preventDefault();return}if(ya(r)){r.preventDefault();try{o.showPicker?.()}catch{}}};this.onTileKey=r=>{let o=[...this.renderRoot.querySelectorAll(".tiles [role=option]")],n=o.indexOf(r.target);if(n<0)return;let a=-1;if(r.key==="ArrowRight"||r.key==="ArrowDown")a=Math.min(o.length-1,n+1);else if(r.key==="ArrowLeft"||r.key==="ArrowUp")a=Math.max(0,n-1);else if(r.key==="Home")a=0;else if(r.key==="End")a=o.length-1;else if(r.key==="Enter"||r.key===" "){r.preventDefault();let i=this.control?.options[n];i&&this.pick(i.value);return}if(!(a<0)){r.preventDefault();for(let[i,s]of o.entries())s.tabIndex=i===a?0:-1;o[a].focus()}}}value(){return typeof this.optimistic=="string"?this.optimistic:this.control?.value??null}pick(r){this.disabled||r===this.value()||this.send(r)}renderTiles(r,o){let n=r.options.findIndex(a=>a.value===o);return this.frame(h`<div
        class="tiles ${this.disabled?"disabled":""}"
        role="listbox"
        aria-labelledby="label"
        aria-describedby=${this.describedBy()}
        aria-disabled=${this.locked}
        @keydown=${this.onTileKey}
      >
        ${r.options.map((a,i)=>h`<div
            role="option"
            class="tile"
            aria-selected=${a.value===o?"true":"false"}
            tabindex=${i===(n<0?0:n)?"0":"-1"}
            @click=${()=>this.pick(a.value)}
          >
            ${a.label}
          </div>`)}
      </div>`,{stacked:!0})}render(){let r=this.control;if(!r)return f;let o=this.value();if(r.tiles)return this.renderTiles(r,o);let n=r.options.some(a=>a.value===o);if(r.options.length<=Rs){let a=r.options.length>3||r.options.some(l=>l.label.length>12),i=n||o===null?null:this.t("value.now",{value:o}),s=[r.hint,i].filter(Boolean).join(`
`)||null;return this.frame(h`<div class="segmented ${this.disabled?"disabled":""}" role="group" aria-labelledby="label">
          ${r.options.map(l=>h`<button
              type="button"
              aria-pressed=${l.value===o?"true":"false"}
              aria-disabled=${this.locked}
              aria-describedby=${this.describedBy(s)}
              @click=${()=>this.pick(l.value)}
            >
              ${l.label}
            </button>`)}
        </div>`,{stacked:a,hint:s})}return this.frame(h`<span class="dropdown">
        <select
          aria-labelledby="label"
          aria-disabled=${this.locked}
          aria-describedby=${this.describedBy()}
          @keydown=${this.onKey}
          @change=${a=>this.pick(a.target.value)}
        >
          ${n?f:h`<option value="" disabled selected>${o===null?"\u2014":o}</option>`}
          ${r.options.map(a=>h`<option value=${a.value} ?selected=${a.value===o}>${a.label}</option>`)}
        </select>
        ${Ke(Ue.chevron)}
      </span>`)}updated(r){super.updated(r);let o=this.renderRoot.querySelector("select"),n=this.value();o&&n!==null&&o.value!==n&&this.control?.options.some(a=>a.value===n)&&(o.value=n)}};Y("bc-select",go);var Hs=600,Ds=(t,e)=>t.toFixed(e);function _a(t){let e=String(t);return e.includes(".")?e.length-e.indexOf(".")-1:0}function bo(t,e){return Number(t.toFixed(_a(e)))}var Rr=class extends H{constructor(){super(...arguments);this.onKey=r=>{let o=r.key==="ArrowUp"||r.key==="ArrowRight"?1:r.key==="ArrowDown"||r.key==="ArrowLeft"?-1:r.key==="PageUp"?10:r.key==="PageDown"?-10:0;o&&(r.preventDefault(),this.bump(o))}}disconnectedCallback(){this.commitTimer!==void 0&&this.commit(),super.disconnectedCallback()}shown(){return typeof this.optimistic=="number"?this.optimistic:this.control?.value??null}bump(r){let o=this.control;if(!o||this.disabled)return;let n=this.shown(),a=o.step,i=c=>bo(Math.round(c/a)*a,a),s;n===null?s=o.min+Math.round((o.max-o.min)/2/a)*a:i(n)===bo(n,a)?s=n+r*a:s=(r>0?Math.ceil(n/a)*a:Math.floor(n/a)*a)+(r-Math.sign(r))*a;let l=Math.min(o.max,Math.max(o.min,bo(s,a)));l!==n&&(this.optimistic=l,clearTimeout(this.commitTimer),this.commitTimer=setTimeout(()=>this.commit(),Hs))}commit(){clearTimeout(this.commitTimer),this.commitTimer=void 0;let r=this.optimistic;if(typeof r=="number"){if(r===this.control?.value){this.clearOptimistic();return}this.send(r)}}render(){let r=this.control;if(!r)return f;let o=this.shown(),n=this.disabled,a=o!==null&&o<=r.min,i=o!==null&&o>=r.max,s=this.describedBy();return this.frame(h`
      <div class="stepper ${this.commitTimer!==void 0?"draft":""}" role="group" aria-labelledby="label" @keydown=${this.onKey}>
        <button
          type="button"
          aria-label=${this.t("ctl.decrease")}
          aria-disabled=${a||n?"true":f}
          aria-describedby=${s}
          @click=${()=>this.bump(-1)}
        >
          ${Ke(Ue.minus)}
        </button>
        <!-- No setpoint (an oven that's off) reads as a blank display, not as a number. -->
        <output aria-live="polite" class=${o===null?"empty":f}>
          ${o===null?"--":(this.formatNumber??Ds)(o,_a(r.step))}<span class="unit">${r.unit}</span>
        </output>
        <button
          type="button"
          aria-label=${this.t("ctl.increase")}
          aria-disabled=${i||n?"true":f}
          aria-describedby=${s}
          @click=${()=>this.bump(1)}
        >
          ${Ke(Ue.plus)}
        </button>
      </div>
    `)}};Rr.properties={formatNumber:{attribute:!1}};Y("bc-setpoint",Rr);var $o=class extends H{value(){return typeof this.optimistic=="boolean"?this.optimistic:this.control?.value??null}flip(){this.disabled||this.send(!this.value())}render(){if(!this.control)return f;let e=this.value();return e===null&&this.disabled?this.frame(h`<span class="reading">—</span>`):this.frame(h`<button
      type="button"
      class="switch ${e===null?"unknown":""}"
      role="switch"
      aria-checked=${e===!0?"true":"false"}
      aria-labelledby="label"
      aria-disabled=${this.locked}
      aria-describedby=${this.describedBy()}
      @click=${()=>this.flip()}
    ></button>`)}};Y("bc-toggle",$o);function ka(t,e){let{t:r,pending:o,error:n,onValue:a}=e,i=e.quiet===!0,s=e.sharedReason===!0;switch(t.kind){case"setpoint":return h`<bc-setpoint
        .control=${t}
        .t=${r}
        .pending=${o}
        .error=${n}
        .sharedReason=${s}
        .formatNumber=${e.formatNumber}
        ?quiet=${i}
        @bc-value=${a}
      ></bc-setpoint>`;case"select":return h`<bc-select .control=${t} .t=${r} .pending=${o} .error=${n} .sharedReason=${s} ?quiet=${i} @bc-value=${a}></bc-select>`;case"toggle":return h`<bc-toggle .control=${t} .t=${r} .pending=${o} .error=${n} .sharedReason=${s} ?quiet=${i} @bc-value=${a}></bc-toggle>`;case"action":return h`<bc-action .control=${t} .t=${r} .pending=${o} .error=${n} .sharedReason=${s} ?quiet=${i} @bc-value=${a}></bc-action>`;case"duration":return h`<bc-duration .control=${t} .t=${r} .pending=${o} .error=${n} .sharedReason=${s} ?quiet=${i} @bc-value=${a}></bc-duration>`;case"reading":return h`<bc-reading .control=${t} .t=${r} ?quiet=${i}></bc-reading>`;case"countdown":return h`<bc-countdown .control=${t} .t=${r} ?quiet=${i}></bc-countdown>`}}var Aa=new Set(["unavailable","unknown"]);function vo(t){if(!Array.isArray(t))return[];let e=[];for(let r of t){if(!r||typeof r!="object")continue;let o=r.s??r.state,n=yo(r.lc??r.lu??r.last_changed??r.last_updated);typeof o=="string"&&n!==null&&e.push({state:o,at:n})}return e}function yo(t){if(typeof t=="number"&&Number.isFinite(t))return t<1e11?t*1e3:t;if(typeof t=="string"){let e=Date.parse(t);return Number.isNaN(e)?null:e}return null}function Os(t,e){let r=null,o;for(let n of t)Aa.has(n.state)||(n.state==="on"&&o!=="on"?r={start:n.at,end:null}:n.state!=="on"&&o==="on"&&r&&(r={start:r.start,end:n.at}),o=n.state);return r&&r.end===null&&r.start>e?null:r}function wa(t){let e=[];for(let r of t){let o=Number.parseFloat(r.state);Number.isFinite(o)&&!Aa.has(r.state)&&e.push({at:r.at,value:o})}return e}function xa(t,e=1500){if(t.length<=e)return[...t];let r=(t.length-1)/(e-1);return Array.from({length:e},(o,n)=>t[Math.round(n*r)])}function za(t){return t.entities.cook?.switch}var Er=class{constructor(e=()=>{},r=Date.now){this.onChange=e;this.now=r;this.entries=new Map}chart(e,r){let o=this.now(),n=za(r),a={status:"none",window:null,from:o,to:o,current:[],target:[]};if(!e||!n||!e.states[n])return a;let i=`${r.device_id}|${e.states[n].last_changed}`,s=this.entries.get(r.device_id);(!s||s.key!==i||s.retryAt!==null&&o>=s.retryAt)&&(s={key:i,status:"loading",window:s?.key===i?s.window:null,current:[],target:[],retryAt:null,seen:{}},this.entries.set(r.device_id,s),this.fetch(e,r,s)),s.status==="ready"&&this.extend(e,r,s);let l=s.window;if(!l)return{...a,status:s.status==="ready"?"none":s.status};let c=l.end??o,d=Math.max(l.start,c-864e5);return{status:s.status,window:l,from:d,to:c,current:xa(s.current),target:xa(s.target)}}extend(e,r,o){if(!(!o.window||o.window.end!==null))for(let[n,a]of[["current_temperature",o.current],["target_temperature",o.target]]){let i=n==="current_temperature"?r.entities[n]?.sensor:r.entities[n]?.number,s=i?e.states[i]:void 0;if(!i||!s||o.seen[i]===s)continue;o.seen[i]=s;let l=Number.parseFloat(s.state),c=yo(s.last_updated);if(!Number.isFinite(l)||c===null)continue;let d=a[a.length-1];d&&c<=d.at||(d&&d.value===l&&a.length>1&&a[a.length-2].value===l?a[a.length-1]={at:c,value:l}:a.push({at:c,value:l}))}}async fetch(e,r,o){let n=za(r),a=this.now();try{let i=await Sa(e,[n],a-36e7,a,!0),s=Os(vo(i[n]),a),l=e.states[n];if(l?.state==="on"&&(!s||s.end!==null)&&(s={start:yo(l.last_changed)??a,end:null}),this.entries.get(r.device_id)!==o)return;if(o.window=s,s){let c=s.end??a,d=Math.max(s.start,c-864e5),m=r.entities.current_temperature?.sensor,b=r.entities.target_temperature?.number,$=[m,b].filter(z=>!!z),v=$.length?await Sa(e,$,d,s.end??void 0,!0):{};if(this.entries.get(r.device_id)!==o)return;o.current=m?wa(vo(v[m])):[],o.target=b?wa(vo(v[b])):[]}o.status="ready"}catch{if(this.entries.get(r.device_id)!==o)return;o.status="failed",o.retryAt=this.now()+6e4}this.onChange()}};async function Sa(t,e,r,o,n){return await t.callWS({type:"history/history_during_period",start_time:new Date(r).toISOString(),...o===void 0?{}:{end_time:new Date(o).toISOString()},include_start_time_state:n,significant_changes_only:!1,entity_ids:e,minimal_response:!0,no_attributes:!0})??{}}var _o=class{constructor(e=Date.now){this.listeners=new Set;this.history=new Er(()=>this.notify(),e)}onChange(e){return this.listeners.add(e),()=>{this.listeners.delete(e)}}notify(){for(let e of[...this.listeners])e()}},ko=new _o;var Bs=600,re={left:46,right:14,top:12,bottom:26},js=24,Gs=[5,10,15,30,60,120,180,360,720];function Lr(t,e){let r=null;for(let o of t){if(o.at>e)break;r=o.value}return r}function Ns(t,e,r){let o=null;for(let n=t.length-1;n>=0;n--){let a=t[n],i=Lr(e,a.at);if(i===null||Math.abs(a.value-i)>r)break;o=a.at}return o}function Vs(t,e,r=4){let n=Math.max(e-t,1e-6)/r,a=10**Math.floor(Math.log10(n)),i=[1,2,2.5,5,10].map(c=>c*a).find(c=>c>=n)??n,s=[],l=Math.ceil(e/i-1e-9)*i;for(let c=Math.floor(t/i+1e-9)*i;c<=l+i*1e-6;c+=i)s.push(Number(c.toFixed(6)));return s}var Rt=class extends E{constructor(){super(),this.now=Date.now(),this.table=!1,this.width=Bs}connectedCallback(){super.connectedCallback(),this.stop=ko.onChange(()=>this.requestUpdate()),typeof ResizeObserver=="function"&&(this.observer??=new ResizeObserver(e=>{let r=Math.round(e[e.length-1]?.contentRect.width??0);r>0&&r!==this.width&&(this.width=r)}),this.observer.observe(this))}disconnectedCallback(){super.disconnectedCallback(),this.stop?.(),this.stop=void 0,this.observer?.disconnect()}willUpdate(e){se(this,this.hass)}render(){let{hass:e,appliance:r}=this;if(!e||!r)return f;let o=K(e),n=ko.history.chart(e,r);if(n.status==="loading"&&!n.current.length)return h`<p class="note">${o("chart.loading")}</p>`;if(n.status==="failed")return h`<p class="note">${o("chart.failed")}</p>`;if(n.status==="none"||!n.window)return h`<p class="note">${o("chart.none")}</p>`;let a=xe(e),i=r.sensor_target_c===null?null:St(e,r.sensor_target_c);return h`
      <p class="summary">${this.summary(o,n,a,i)}</p>
      <figure>
        ${this.renderSvg(n,a,i)}
        <figcaption class="legend" aria-hidden="true">
          <span><i class="key current"></i>${o("chart.temperature")}</span>
          <span><i class="key target"></i>${o("chart.target")}</span>
          ${i!==null?h`<span><i class="key sensor"></i>${o("chart.sensor_target")}</span>`:f}
        </figcaption>
      </figure>
      ${i!==null?h`<p class="note">${o("chart.sensor_caption")}</p>`:f}
      <button type="button" class="bc-button" aria-expanded=${this.table?"true":"false"} @click=${()=>this.table=!this.table}>
        ${o(this.table?"chart.hide_table":"chart.show_table")}
      </button>
      ${this.table?this.renderTable(o,n,a):f}
    `}summary(e,r,o,n){let a=this.hass,i=this.appliance?.kind==="sous_vide"?1:0,s=r.current[r.current.length-1],l=Lr(r.target,r.to),c=[];if(r.window?.end!=null&&c.push(e("chart.last_cook",{start:or(a,r.window.start,this.now),end:he(a,r.window.end)})),s){let d=D(a,s.value,o,i);c.push(l===null?e(r.window?.end!=null?"chart.summary_last":"chart.summary_now",{now:d}):e(r.window?.end!=null?"chart.summary_last_target":"chart.summary_now_target",{now:d,target:D(a,l,o,i)}))}if(this.appliance?.kind==="sous_vide"&&r.window?.end==null){let d=Ns(r.current,r.target,me(a)?.5:1);d!==null&&c.push(e("chart.at_temperature_since",{time:or(a,d,this.now)}))}return n!==null&&c.push(e("chart.sensor_summary",{temp:D(a,n,o)})),r.window&&r.from>r.window.start&&c.push(e("chart.last_day")),c.join(" ")}renderSvg(e,r,o){let n=this.hass,a=Math.max(260,this.width),i=Math.round(Math.min(240,Math.max(170,a*.36))),s=[...e.current,...e.target].map(C=>C.value);o!==null&&s.push(o);let l=this.appliance?.kind==="oven"?10:1,c=s.length?Math.min(...s)-l:0,d=s.length?Math.max(...s)+l:100;d-c<4&&(c-=2,d+=2);let m=Vs(c,d,4);c=Math.min(c,m[0]),d=Math.max(d,m[m.length-1]);let b=e.from,$=Math.max(e.to,b+6e4),v=C=>re.left+(C-b)/($-b)*(a-re.left-re.right),z=C=>i-re.bottom-(C-c)/(d-c)*(i-re.top-re.bottom),T=C=>C.filter(Te=>Te.at>=b-1&&Te.at<=$+1),G=C=>T(C).map((Te,Pa)=>`${Pa?"L":"M"}${v(Te.at).toFixed(1)},${z(Te.value).toFixed(1)}`).join(""),X=Lr(e.target,b),R=X===null?[]:[{at:b,value:X}];for(let C of T(e.target)){let Te=R[R.length-1];Te&&R.push({at:C.at,value:Te.value}),R.push(C)}R.length&&R.push({at:$,value:R[R.length-1].value});let U=($-b)/6e4,V=Math.max(2,Math.floor((a-re.left-re.right)/90)),ye=Gs.find(C=>U/C<=V)??1440,Hr=Math.ceil(b/(ye*6e4))*ye*6e4,vt=[];for(let C=Hr;C<=$;C+=ye*6e4)vt.push(C);return h`<svg class="chart" viewBox="0 0 ${a} ${i}" width=${a} height=${i} aria-hidden="true">
      ${m.map(C=>p`<line class="grid" x1=${re.left} x2=${a-re.right} y1=${z(C)} y2=${z(C)}></line>
          <text class="axis" x=${re.left-6} y=${z(C)+4} text-anchor="end">${Pe(n,C,1)}°</text>`)}
      ${vt.map(C=>p`<text class="axis" x=${v(C)} y=${i-8} text-anchor="middle">${he(n,C)}</text>`)}
      ${o!==null?p`<line class="sensor" x1=${re.left} x2=${a-re.right} y1=${z(o)} y2=${z(o)}></line>`:f}
      ${R.length?p`<path class="target" d=${G(R)}></path>`:f}
      <path class="current" d=${G(e.current)}></path>
      <text class="unit" x="4" y="14">${r}</text>
    </svg>`}renderTable(e,r,o){let n=this.hass,a=this.appliance?.kind==="sous_vide"?1:0,i=r.current,s=Math.max(1,Math.ceil(i.length/js)),l=i.filter((c,d)=>d%s===0||d===i.length-1);return h`<table>
      <caption class="visually-hidden">${e("chart.table_caption")}</caption>
      <thead>
        <tr>
          <th scope="col">${e("chart.time")}</th>
          <th scope="col">${e("chart.temperature")}</th>
          <th scope="col">${e("chart.target")}</th>
        </tr>
      </thead>
      <tbody>
        ${l.map(c=>{let d=Lr(r.target,c.at);return h`<tr>
            <th scope="row">${or(n,c.at,this.now)}</th>
            <td>${D(n,c.value,o,a)}</td>
            <td>${d===null?"\u2014":D(n,d,o,a)}</td>
          </tr>`})}
      </tbody>
    </table>`}};Rt.properties={hass:{attribute:!1},appliance:{attribute:!1},now:{attribute:!1},table:{state:!0},width:{state:!0}},Rt.styles=[ae,ie,P`
      :host {
        display: block;
        color: var(--bc-text);
        font-size: 14px;
        --bc-chart-current: var(--bc-tone-warm);
        --bc-chart-target: color-mix(in srgb, var(--bc-text) 55%, transparent);
      }
      .summary {
        margin: 0 0 8px;
        line-height: 1.45;
      }
      .note {
        margin: 6px 0 10px;
        color: var(--bc-muted);
        font-size: 13px;
        line-height: 1.45;
      }
      figure {
        margin: 0;
      }
      .chart {
        display: block;
        max-width: 100%;
        height: auto;
        overflow: visible;
      }
      .grid {
        stroke: var(--bc-divider);
        stroke-width: 1;
        vector-effect: non-scaling-stroke;
      }
      .axis,
      .unit {
        fill: var(--bc-muted);
        font-size: 11px;
        font-variant-numeric: tabular-nums;
      }
      .current,
      .target,
      .sensor {
        fill: none;
        vector-effect: non-scaling-stroke;
        stroke-linejoin: round;
        stroke-linecap: round;
      }
      .current {
        stroke: var(--bc-chart-current);
        stroke-width: 2.25;
      }
      .target {
        stroke: var(--bc-chart-target);
        stroke-width: 1.5;
      }
      .sensor {
        stroke: var(--bc-chart-target);
        stroke-width: 1.5;
        stroke-dasharray: 5 4;
      }
      .legend {
        display: flex;
        flex-wrap: wrap;
        gap: 4px 16px;
        margin-top: 6px;
        color: var(--bc-muted);
        font-size: 12.5px;
      }
      .legend span {
        display: inline-flex;
        align-items: center;
        gap: 6px;
      }
      .key {
        display: inline-block;
        width: 18px;
        height: 0;
        border-top: 2.5px solid var(--bc-chart-current);
      }
      .key.target {
        border-top: 1.5px solid var(--bc-chart-target);
      }
      .key.sensor {
        border-top: 1.5px dashed var(--bc-chart-target);
      }
      .bc-button {
        margin-top: 10px;
      }
      table {
        width: 100%;
        margin-top: 10px;
        border-collapse: collapse;
        font-variant-numeric: tabular-nums;
      }
      th,
      td {
        padding: 5px 8px;
        border-top: 1px solid var(--bc-divider);
        text-align: start;
        font-weight: 400;
      }
      thead th {
        border-top: none;
        color: var(--bc-muted);
        font-weight: 500;
      }
      .visually-hidden {
        position: absolute;
        width: 1px;
        height: 1px;
        margin: -1px;
        overflow: hidden;
        clip: rect(0 0 0 0);
        white-space: nowrap;
      }
    `];customElements.get("bc-temp-chart")||customElements.define("bc-temp-chart",Rt);function Et(t,e){if(!e.builtin&&e.name)return e.name;let r=`preset.${e.id}`,o=t(r);return o===r?e.name??e.id:o}function Is(t,e){let{temperature_c:r,temperature_f:o}=e.settings;return!me(t)&&typeof o=="number"?o:typeof r!="number"?null:me(t)?r:Math.round((r*9/5+32)*10)/10}function Ta(t,e,r,o){let n=r.settings,a=Is(t,r),i=a===null?null:D(t,a,xe(t),1),s=n.duration_s?ge(e,n.duration_s):e("value.until_stopped");if(r.kind==="sous_vide")return[i,s].join(" \xB7 ");let l=n.mode?Le(e,"mode",n.mode):null,c=n.mode?o.get(n.mode)?.type:null,d=n.level?Le(e,"level",n.level):null;return[l,c==="temp"?i:d,s,n.frozen?e("presets.frozen"):null].filter(b=>!!b).join(" \xB7 ")}function Ca(t,e,r){if(t.kind!==e.kind)return!1;let o=t.settings;if(t.kind==="sous_vide"){let a=o.temperature_c;if(typeof a!="number")return!1;let{min_temp_c:i,max_temp_c:s,max_cook_s:l}=e.limits;return a>=i&&a<=s&&(o.duration_s??0)<=l}let n=o.mode?r.get(o.mode):void 0;if(!n?.remote)return!1;if(n.type==="temp"){let a=n.temperature_c,i=o.temperature_c;return!a||typeof i!="number"?!1:Math.round(i)>=a.min&&Math.round(i)<=a.max}return!!(o.level&&n.levels?.includes(o.level))}var wo="bc-preset-applied",Fs=p`<path d="M14.06 9.02l.92.92L5.92 19H5v-.92l9.06-9.06M17.66 3c-.25 0-.51.1-.7.29l-1.83 1.83 3.75 3.75 1.83-1.83a.996.996 0 0 0 0-1.41l-2.34-2.34c-.2-.2-.45-.29-.71-.29zm-3.6 3.19L3 17.25V21h3.75L17.81 9.94l-3.75-3.75z" />`,Us=p`<path d="M17.7 6.3A8 8 0 1 0 19.7 14h-2.1A6 6 0 1 1 12 6c1.7 0 3.1.7 4.2 1.8L13 11h7V4l-2.3 2.3Z" />`,Ks=p`<path d="M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6v12M8 9h8v10H8V9m7.5-5-1-1h-5l-1 1H5v2h14V4h-3.5z" />`,Lt=class extends E{constructor(){super(),this.presets=[],this.modes=new Map,this.cooking=!1,this.busy=!1,this.editing=null,this.message=null,this.error=null}willUpdate(e){se(this,this.hass);let r=e.get("appliance");e.has("appliance")&&r&&r.device_id!==this.appliance?.device_id&&(this.editing=null,this.message=null,this.error=null)}t(){return K(this.hass)}async failure(e){let r=this.t(),n=`presets.error.${e&&typeof e=="object"&&"code"in e?String(e.code):""}`,a=r(n);return a===n?await Zt(this.hass,e)||r("full.failed"):a}async call(e,r){let o=this.hass;if(!o||this.busy)return!1;this.busy=!0,this.error=null,this.message=null;try{let n=await o.callWS(e);return this.message=r(n),!0}catch(n){return this.error=await this.failure(n),!1}finally{this.busy=!1}}async apply(e){let r=this.t(),o=Et(r,e);await this.call({type:"bruh_cooking/panel/apply_preset",device_id:this.appliance?.device_id,preset_id:e.id},()=>r("presets.applied",{name:o}))&&this.dispatchEvent(new CustomEvent(wo,{bubbles:!0,composed:!0}))}async save(e,r){e.preventDefault();let o=e.currentTarget.querySelector("input[name=name]"),n=o?.value.trim()??"";if(!n){o?.reportValidity();return}let a=this.t();await this.call(r?{type:"bruh_cooking/panel/save_preset",preset_id:r,name:n}:{type:"bruh_cooking/panel/save_preset",device_id:this.appliance?.device_id,name:n},()=>a(r?"presets.renamed":"presets.saved",{name:n}))&&(this.editing=null)}async replaceSettings(e){let r=this.t();await this.call({type:"bruh_cooking/panel/save_preset",preset_id:e.id,device_id:this.appliance?.device_id},()=>r("presets.updated",{name:Et(r,e)}))&&(this.editing=null)}async deletePreset(e){let r=this.t();await this.call({type:"bruh_cooking/panel/delete_preset",preset_id:e.id},()=>r("presets.deleted",{name:Et(r,e)}))&&(this.editing=null)}render(){let{hass:e,appliance:r}=this;if(!e||!r)return f;let o=this.t(),n=e.user?.is_admin===!0,a=this.presets.filter(c=>Ca(c,r,this.modes)),i=a.filter(c=>c.builtin),s=a.filter(c=>!c.builtin),l=r.available?this.cooking?o("presets.disabled_cooking"):null:o("reason.offline");return h`
      ${l?h`<p class="note">${l}</p>`:f}
      <h3 id="builtin">${o("presets.builtin")}</h3>
      <ul class="list" aria-labelledby="builtin">
        ${Be(i,c=>c.id,c=>this.renderRow(o,c,l,!1))}
      </ul>
      <h3 id="custom">${o("presets.custom")}</h3>
      ${s.length?h`<ul class="list" aria-labelledby="custom">
            ${Be(s,c=>c.id,c=>this.renderRow(o,c,l,n))}
          </ul>`:h`<p class="note">${o(n?"presets.none_admin":"presets.none")}</p>`}
      ${n?this.renderNew(o):f}
      <p class="status" role="status">${this.message??""}</p>
      ${this.error?h`<p class="error" role="alert">${this.error}</p>`:f}
      <p class="disclaimer">${o("presets.disclaimer")}</p>
    `}renderRow(e,r,o,n){let a=this.hass,i=Et(e,r),s=Ta(a,e,r,this.modes),l=this.editing&&"id"in this.editing&&this.editing.id===r.id?this.editing:null;if(l?.kind==="rename")return h`<li class="row">
        <form class="rename" @submit=${d=>{this.save(d,r.id)}}>
          <input name="name" maxlength="40" required .value=${i} aria-label=${e("presets.name")} />
          <button type="submit" class="bc-button primary" ?disabled=${this.busy}>${e("presets.save")}</button>
          <button type="button" class="bc-button" @click=${()=>this.editing=null}>${e("presets.cancel")}</button>
        </form>
      </li>`;let c=`p-${r.id}`;return h`<li class="row">
      <button
        type="button"
        class="apply"
        aria-describedby=${`${c}-summary${r.note?` ${c}-note`:""}${o?` ${c}-blocked`:""}`}
        aria-disabled=${o||this.busy?"true":f}
        @click=${()=>{!o&&!this.busy&&this.apply(r)}}
      >
        <span class="name">${i}</span>
        <span class="summary" id=${`${c}-summary`}>${s}</span>
        ${r.note?h`<span class="warning" id=${`${c}-note`}>${e(`presets.note.${r.note}`)}</span>`:f}
        ${o?h`<span class="visually-hidden" id=${`${c}-blocked`}>${o}</span>`:f}
      </button>
      ${n?h`<span class="tools">
            ${this.tool(Fs,e("presets.rename_named",{name:i}),()=>this.editing={kind:"rename",id:r.id})}
            ${this.tool(Us,e("presets.update_named",{name:i}),()=>this.editing={kind:"update",id:r.id},!!o)}
            ${this.tool(Ks,e("presets.delete_named",{name:i}),()=>this.editing={kind:"delete",id:r.id})}
          </span>`:f}
      ${l?.kind==="delete"?h`<div class="ask">
            ${Tt({text:e("presets.delete_confirm",{name:i}),confirm:e("presets.delete"),cancel:e("presets.cancel"),tone:"danger",busy:this.busy,onConfirm:()=>{this.deletePreset(r)},onCancel:()=>this.editing=null})}
          </div>`:f}
      ${l?.kind==="update"?h`<div class="ask">
            ${Tt({text:e("presets.update_confirm",{name:i}),confirm:e("presets.update"),cancel:e("presets.cancel"),busy:this.busy,onConfirm:()=>{this.replaceSettings(r)},onCancel:()=>this.editing=null})}
          </div>`:f}
    </li>`}tool(e,r,o,n=!1){return h`<button
      type="button"
      class="tool"
      aria-label=${r}
      title=${r}
      aria-disabled=${n?"true":f}
      @click=${()=>{n||(o(),this.updateComplete.then(()=>this.renderRoot.querySelector(".ask .bc-button, .rename input")?.focus()))}}
    >
      <svg viewBox="0 0 24 24" aria-hidden="true">${e}</svg>
    </button>`}renderNew(e){return this.editing?.kind!=="new"?h`<button
        type="button"
        class="bc-button save"
        ?disabled=${!this.appliance?.available}
        @click=${()=>{this.editing={kind:"new"},this.updateComplete.then(()=>this.renderRoot.querySelector("form.new input")?.focus())}}
      >
        ${e("presets.save_current")}
      </button>`:h`<form class="new" @submit=${r=>{this.save(r)}}>
      <label for="new-name">${e("presets.name")}</label>
      <div class="fields">
        <input id="new-name" name="name" maxlength="40" required autocomplete="off" />
        <button type="submit" class="bc-button primary" ?disabled=${this.busy}>${e("presets.save")}</button>
        <button type="button" class="bc-button" @click=${()=>this.editing=null}>${e("presets.cancel")}</button>
      </div>
      <p class="hint">${e("presets.save_hint")}</p>
    </form>`}};Lt.properties={hass:{attribute:!1},appliance:{attribute:!1},presets:{attribute:!1},modes:{attribute:!1},cooking:{type:Boolean},busy:{state:!0},editing:{state:!0},message:{state:!0},error:{state:!0}},Lt.styles=[ae,ie,je,P`
      :host {
        display: block;
        color: var(--bc-text);
        font-size: 14px;
      }
      h3 {
        margin: 4px 0 6px;
        font-size: 13px;
        font-weight: 600;
        color: var(--bc-muted);
        text-transform: none;
      }
      h3:not(:first-of-type) {
        margin-top: 14px;
      }
      .list {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(min(100%, 230px), 1fr));
        gap: 6px;
        margin: 0;
        padding: 0;
        list-style: none;
      }
      .row {
        position: relative;
        display: flex;
        flex-wrap: wrap;
        align-items: stretch;
        gap: 4px;
        min-width: 0;
      }
      .apply {
        display: flex;
        flex: 1 1 auto;
        flex-direction: column;
        align-items: flex-start;
        gap: 2px;
        min-width: 0;
        min-height: 52px;
        padding: 8px 12px;
        box-sizing: border-box;
        border: none;
        border-radius: 12px;
        background: var(--bc-control-bg);
        color: inherit;
        font: inherit;
        text-align: start;
        cursor: pointer;
        -webkit-tap-highlight-color: transparent;
        transition: background-color 0.15s;
      }
      .apply:hover:not([aria-disabled="true"]) {
        background: var(--bc-control-hover);
      }
      .apply[aria-disabled="true"] {
        opacity: 0.55;
        cursor: default;
      }
      .apply:focus-visible,
      .tool:focus-visible,
      input:focus-visible {
        outline: 2px solid var(--bc-accent);
        outline-offset: 2px;
      }
      .name {
        font-weight: 600;
      }
      .summary {
        color: var(--bc-muted-inset);
        font-size: 12.5px;
        font-variant-numeric: tabular-nums;
      }
      .warning {
        color: var(--bc-warning-text);
        font-size: 12px;
      }
      .tools {
        display: flex;
        align-items: center;
        gap: 2px;
      }
      .tool {
        display: grid;
        place-items: center;
        width: 32px;
        height: 32px;
        padding: 0;
        border: none;
        border-radius: 50%;
        background: none;
        color: var(--bc-muted);
        cursor: pointer;
      }
      .tool:hover:not([aria-disabled="true"]) {
        background: var(--bc-control-bg);
        color: var(--bc-text);
      }
      .tool[aria-disabled="true"] {
        opacity: 0.4;
        cursor: default;
      }
      .tool svg {
        width: 18px;
        height: 18px;
        fill: currentColor;
      }
      .ask {
        flex-basis: 100%;
      }
      .save {
        margin-top: 12px;
      }
      form.new {
        margin-top: 12px;
      }
      form.new label {
        display: block;
        margin-bottom: 4px;
        font-weight: 500;
      }
      .fields,
      .rename {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 8px;
        width: 100%;
      }
      input {
        flex: 1 1 12em;
        min-height: 40px;
        box-sizing: border-box;
        padding: 6px 12px;
        border: 1px solid var(--bc-divider);
        border-radius: 10px;
        background: transparent;
        color: inherit;
        font: inherit;
      }
      .hint,
      .note,
      .disclaimer {
        margin: 6px 0 0;
        color: var(--bc-muted);
        font-size: 12.5px;
        line-height: 1.45;
      }
      .note {
        margin: 0 0 8px;
        font-size: 13px;
      }
      .status:empty {
        display: none;
      }
      .status {
        margin: 10px 0 0;
        color: var(--bc-text);
        font-size: 13px;
      }
      .error {
        margin: 8px 0 0;
        color: var(--bc-error-text);
        font-size: 13px;
      }
      .disclaimer {
        margin-top: 12px;
      }
      .visually-hidden {
        position: absolute;
        width: 1px;
        height: 1px;
        margin: -1px;
        overflow: hidden;
        clip: rect(0 0 0 0);
        white-space: nowrap;
      }
      @media (any-pointer: coarse) {
        .tool {
          width: 44px;
          height: 44px;
        }
        input {
          min-height: 44px;
        }
      }
      @media (prefers-reduced-motion: reduce) {
        .apply {
          transition: none;
        }
      }
    `];customElements.get("bc-presets")||customElements.define("bc-presets",Lt);var Ws=p`<path d="M7.4 8.6 12 13.2l4.6-4.6L18 10l-6 6-6-6z" />`,qs=0;function Ma(t,e){let r={...t};return delete r[e],r}function Zs(t,e){return t.trim().toLocaleLowerCase()===e.trim().toLocaleLowerCase()}var Ht=class extends E{constructor(){super();this.uid=`bcv${++qs}`;this.size=new mt(this,".stage .drawing > svg");this.clock=Date.now();this.tick=()=>{this.clock=Date.now(),this.now===void 0&&this.requestUpdate(),this.timer=setTimeout(this.tick,1e3-this.clock%1e3+5)};this.narrow=!1,this.shared=tt,this.pending={},this.errors={},this.addEventListener(wo,()=>{this.focusStart()})}async focusStart(){await this.updateComplete;let r=this.renderRoot.querySelector('.control[data-control="start"] bc-action');await r?.updateComplete,r?.shadowRoot?.querySelector("button")?.focus()}connectedCallback(){super.connectedCallback(),this.tick()}disconnectedCallback(){super.disconnectedCallback(),clearTimeout(this.timer),this.timer=void 0}shouldUpdate(r){return r.size===1&&r.has("hass")&&this.hass&&this.appliance?Qt(r.get("hass"),this.hass,this.appliance):!0}willUpdate(r){se(this,this.hass);let o=r.get("appliance");r.has("appliance")&&o?.device_id!==this.appliance?.device_id&&(this.pending={},this.errors={})}async apply(r,o,n){let a=this.hass;if(!(!a||!("action"in o))){this.pending={...this.pending,[r]:!0},this.errors=Ma(this.errors,r);try{await kn(a,o.action,n)}catch(i){let s=await Zt(a,i);this.errors={...this.errors,[r]:s||K(a)("full.failed")}}finally{this.pending=Ma(this.pending,r)}}}render(){let{hass:r,appliance:o}=this;if(!r||!o)return f;let n=K(r),a=this.now??this.clock,i=ct(o),s=pt(o,r,n,a,this.shared),l=V=>`${o.kind} ${V} for ${o.device_id}`,c=J(l("drawing state"),()=>i.drawingState(s),mo(o)),d=J(l("status"),()=>i.status(s),{text:"",tone:"neutral"}),m=o.available?J(l("display"),()=>i.display(s),null):null,b=J(l("sections"),()=>i.sections(s),[]),$=J(l("description"),()=>i.describe(s),o.product),v=J(l("phase"),()=>i.phase(s),"idle"),z=v==="preheating"?Q(s,"preheat","sensor"):null,T=v!=="idle"&&v!=="offline"&&v!=="error"&&v!=="updating",[G,...X]=b,R=X.find(V=>V.id==="details"),U=X.filter(V=>V!==R);return h`<div class="layout">
      <section class="hero" aria-label=${n("full.appliance")}>
        <div class="hero-head">
          <!-- Not a live region: preheat and timer pills change every second; the panel
               announces what matters. -->
          <div class="status">${$r(d)} ${z!==null?this.renderRing(n,z):f}</div>
          ${vr(m,m?.dim)}
        </div>
        <div class="stage">
          <div class="drawing" role="img" aria-label=${$}>
            ${Tr(Ar(o,c,r,this.uid,this.size.height))}
          </div>
        </div>
      </section>
      <div class="sections">
        ${G?this.renderSection(G,n):f}
        ${Be(U,V=>V.id,V=>this.renderSection(V,n))}
        ${this.card("presets",n("section.presets"),h`<bc-presets
            .hass=${this.hass}
            .appliance=${o}
            .presets=${this.shared.presets}
            .modes=${this.shared.modes}
            .cooking=${T}
          ></bc-presets>`,!0)}
        ${this.card("chart",n("section.chart"),h`<bc-temp-chart .hass=${this.hass} .appliance=${o} .now=${a}></bc-temp-chart>`,!0)}
        ${R?this.renderSection(R,n):f}
      </div>
    </div>`}renderRing(r,o){let n=Math.max(0,Math.min(100,Math.round(o))),a=15.5,i=2*Math.PI*a;return h`<span
      class="ring"
      role="progressbar"
      aria-label=${r("full.preheat")}
      aria-valuemin="0"
      aria-valuemax="100"
      aria-valuenow=${n}
      aria-valuetext=${r("full.preheat_value",{n})}
    >
      <svg viewBox="0 0 36 36" aria-hidden="true">
        <circle class="track" cx="18" cy="18" r=${a}></circle>
        <circle
          class="bar"
          cx="18"
          cy="18"
          r=${a}
          stroke-dasharray=${`${i*n/100} ${i}`}
          transform="rotate(-90 18 18)"
        ></circle>
      </svg>
      <span class="ring-value">${Pe(this.hass,n)}%</span>
    </span>`}card(r,o,n,a){return h`<details class="card" data-section=${r} ?open=${a}>
      <summary>
        <h2>${o}</h2>
        <svg class="chevron" viewBox="0 0 24 24" aria-hidden="true">${Ws}</svg>
      </summary>
      <div class="body">${n}</div>
    </details>`}renderSection(r,o){let n=this.hass,a=new Map;for(let d of r.controls)d.disabled&&d.reason&&a.set(d.reason,(a.get(d.reason)??0)+1);let i=new Set([...a].filter(([,d])=>d>1).map(([d])=>d));r.note&&i.add(r.note);let s=(d,m)=>h`<p class="note shared" aria-hidden=${m?"true":f}>${Ke(Ue.lock)}<span>${d}</span></p>`,l=r.controls.length===1&&Zs(r.controls[0].label,r.title),c=(d,m)=>Pe(n,d,m,m);return this.card(r.id,r.title,h`${[...i].map(d=>s(d,d!==r.note))}
      ${Be(r.controls,d=>d.id,d=>{let m=`${r.id}/${d.id}`;return h`<div class="control" data-control=${d.id}>
            ${ka(d,{t:o,pending:!!this.pending[m],error:this.errors[m]??null,onValue:b=>{this.apply(m,d,b.detail.value)},quiet:l,sharedReason:!!(d.disabled&&d.reason&&i.has(d.reason)),formatNumber:c})}
          </div>`})}`,!r.collapsed)}};Ht.properties={hass:{attribute:!1},appliance:{attribute:!1},shared:{attribute:!1},narrow:{type:Boolean,reflect:!0},now:{attribute:!1},pending:{state:!0},errors:{state:!0}},Ht.styles=[ae,hr,ie,je,P`
      :host {
        display: block;
        color: var(--bc-text);
        container-type: inline-size;
      }
      :host([dark]) {
        color-scheme: dark;
      }
      .layout {
        display: grid;
        grid-template-columns: minmax(300px, 5fr) minmax(0, 7fr);
        align-items: start;
        gap: 20px;
        max-width: 1240px;
        margin: 0 auto;
      }
      .hero,
      .card {
        box-sizing: border-box;
        border: var(--bc-border-width) solid var(--bc-border);
        border-radius: var(--bc-radius);
        background: var(--bc-card-bg);
        box-shadow: var(--ha-card-box-shadow, none);
      }
      /* The page scrolls under the panel's sticky toolbar; the drawing stays in view below it. */
      .hero {
        position: sticky;
        top: calc(var(--bc-toolbar-height, 0px) + 16px);
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 14px 16px 18px;
      }
      .hero-head {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        min-height: 36px;
      }
      .status {
        display: flex;
        align-items: center;
        gap: 10px;
      }
      .hero-head .pill {
        max-width: none;
        padding: 4px 12px;
        font-size: 13px;
      }
      .ring {
        position: relative;
        display: inline-grid;
        place-items: center;
        width: 40px;
        height: 40px;
      }
      .ring svg {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
      }
      .ring circle {
        fill: none;
        stroke-width: 3.5;
      }
      .ring .track {
        stroke: var(--bc-control-bg);
      }
      .ring .bar {
        stroke: var(--bc-tone-warm);
        stroke-linecap: round;
        transition: stroke-dasharray 0.6s ease;
      }
      .ring-value {
        font-size: 10.5px;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
      }
      /* The drawing takes its own proportions, up to a height that keeps it in view. */
      .stage,
      .stage .drawing {
        height: auto;
      }
      .stage .drawing > svg {
        max-height: min(62vh, 560px);
      }
      .sections {
        display: flex;
        flex-direction: column;
        gap: 12px;
        min-width: 0;
      }
      summary {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        min-height: 52px;
        padding: 0 16px;
        box-sizing: border-box;
        border-radius: var(--bc-radius);
        cursor: pointer;
        list-style: none;
        -webkit-tap-highlight-color: transparent;
      }
      summary::-webkit-details-marker {
        display: none;
      }
      summary:focus-visible {
        outline: 2px solid var(--bc-accent);
        outline-offset: -2px;
      }
      summary h2 {
        margin: 0;
        font-size: 16px;
        font-weight: 600;
      }
      .chevron {
        flex: none;
        width: 22px;
        height: 22px;
        fill: var(--bc-muted);
        transition: transform 0.2s;
      }
      details[open] > summary .chevron {
        transform: rotate(180deg);
      }
      .body {
        padding: 0 16px 12px;
      }
      .control {
        padding: 10px 0;
        border-top: 1px solid var(--bc-divider);
      }
      /* Values to read sit closer than controls to use, like Home Assistant's device info. */
      .control:has(> bc-reading, > bc-countdown) {
        padding: 7px 0;
      }
      .control:first-child,
      .note + .control {
        padding-top: 0;
        border-top: none;
      }
      .note {
        margin: 0 0 6px;
        color: var(--bc-muted);
      }
      .note.shared {
        display: flex;
        align-items: flex-start;
        gap: 6px;
        margin-bottom: 10px;
        font-size: 13px;
      }
      .note.shared svg {
        flex: none;
        width: 14px;
        height: 14px;
        margin-top: 2px;
        fill: currentColor;
      }
      @media (prefers-reduced-motion: reduce) {
        .chevron,
        .ring .bar {
          transition: none;
        }
      }
      /* Narrow: the drawing on top, short enough that the first controls show under it. */
      @container (max-width: 760px) {
        .layout {
          grid-template-columns: minmax(0, 1fr);
          gap: 12px;
        }
        .hero {
          position: static;
        }
        .stage .drawing > svg {
          max-height: min(40vh, 340px);
        }
      }
      :host([narrow]) .layout {
        grid-template-columns: minmax(0, 1fr);
        gap: 12px;
      }
      :host([narrow]) .hero {
        position: static;
      }
      :host([narrow]) .stage .drawing > svg {
        max-height: min(40vh, 340px);
      }
    `];customElements.get("bc-appliance-view")||customElements.define("bc-appliance-view",Ht);var Qs="bc-open-appliance",Js=0,$t=class extends E{constructor(){super();this.uid=`bcc${++Js}`;this.size=new mt(this,".drawing > svg");this.name="";this.now=Date.now(),this.shared=tt}shouldUpdate(r){return!this.hass||!this.appliance?!1:r.size===1&&r.has("hass")?Qt(r.get("hass"),this.hass,this.appliance):!0}willUpdate(){let{hass:r,appliance:o}=this;!r||!o||(se(this,r),this.toggleAttribute("offline",!o.available),this.name=at(o,r),this.view=ba(o,r,K(r),this.now,this.shared))}render(){let{hass:r,appliance:o,view:n}=this;if(!r||!o||!n)return f;let a=K(r);return h`
      <div class="head">
        <h3 class="name">
          <button type="button" class="open" aria-describedby="status hint" @click=${()=>this.open()}>
            ${this.name}
          </button>
        </h3>
        <span id="status">${$r(n.status)}</span>
        <span id="hint" class="visually-hidden">${a("card.open_hint")}</span>
      </div>
      <div class="stage ${n.display?"has-display":""}">
        ${vr(n.display,n.display?.dim)}
        <div class="drawing" role="img" aria-label=${n.description}>
          ${Tr(Ar(o,n.state,r,this.uid,this.size.height))}
        </div>
      </div>
      ${wn(n.rows.slice(0,3))}
    `}open(){this.appliance&&this.dispatchEvent(new CustomEvent(Qs,{detail:{deviceId:this.appliance.device_id},bubbles:!0,composed:!0}))}};$t.shadowRootOptions={...E.shadowRootOptions,delegatesFocus:!0},$t.properties={hass:{attribute:!1},appliance:{attribute:!1},shared:{attribute:!1},now:{attribute:!1}},$t.styles=[ae,hr,je,P`
      :host {
        position: relative;
        display: flex;
        flex-direction: column;
        box-sizing: border-box;
        min-width: 0;
        padding: 12px 14px 14px;
        border: var(--bc-border-width) solid var(--bc-border);
        border-radius: var(--bc-radius);
        background: var(--bc-card-bg);
        box-shadow: var(--ha-card-box-shadow, none);
        color: var(--bc-text);
        cursor: pointer;
        container-type: inline-size;
        -webkit-tap-highlight-color: transparent;
        transition:
          box-shadow 0.2s ease,
          border-color 0.2s ease,
          transform 0.2s ease;
      }
      /* Only where there's a pointer to hover with: on touch, the lift would stay after a tap. */
      @media (hover: hover) {
        :host(:hover) {
          border-color: color-mix(in srgb, var(--bc-text) 20%, transparent);
          box-shadow: var(--bc-lift);
        }
      }
      :host(:active) {
        transform: scale(0.98);
      }
      :host(:focus-within) {
        outline: 2px solid var(--bc-accent);
        outline-offset: 2px;
      }
      @media (prefers-reduced-motion: reduce) {
        :host {
          transition: none;
        }
        :host(:active) {
          transform: none;
        }
      }
      .head {
        display: flex;
        align-items: center;
        gap: 10px;
        min-height: 28px;
        margin-bottom: 8px;
      }
      .name {
        flex: 1;
        min-width: 0;
        margin: 0;
        overflow: hidden;
        font-size: 17px;
        font-weight: 600;
        line-height: 1.3;
        white-space: nowrap;
        text-overflow: ellipsis;
      }
      /* The name opens the full view, and its hit area covers the whole card. */
      .open {
        max-width: 100%;
        padding: 0;
        border: none;
        background: none;
        color: inherit;
        font: inherit;
        text-align: start;
        overflow: hidden;
        white-space: nowrap;
        text-overflow: ellipsis;
        cursor: pointer;
        outline: none;
      }
      .open::after {
        content: "";
        position: absolute;
        inset: 0;
        z-index: 1;
        border-radius: var(--bc-radius);
      }
      :host([offline]) .name {
        color: var(--bc-muted);
      }
      .visually-hidden {
        position: absolute;
        width: 1px;
        height: 1px;
        margin: -1px;
        overflow: hidden;
        clip: rect(0 0 0 0);
        white-space: nowrap;
      }
      /* Every card's stage is the same height and sits right under the title, so the appliances
         in a grid row stand on one floor line; the info panel takes up any slack below. A display
         sits above the drawing, and the drawing in that card starts below it. */
      .stage {
        --drawing-height: clamp(220px, 74cqw, 320px);
        height: var(--drawing-height);
        margin: 0 0 12px;
        padding-bottom: 2px;
      }
      @media (max-width: 600px) {
        .stage {
          --drawing-height: clamp(200px, 62cqw, 280px);
        }
      }
      .stage.has-display .drawing {
        box-sizing: border-box;
        padding-top: 52px;
      }
      .stage .lcd {
        position: absolute;
        top: 0;
        left: 50%;
        z-index: 1;
        height: 50px;
        transform: translateX(-50%);
      }
      /* Three rows' height whatever it holds, the rows centered, as on the GE card. */
      .info {
        min-height: 75px;
        box-sizing: border-box;
        align-content: center;
        margin: auto 4% 0;
      }
    `];customElements.get("bc-appliance-card")||customElements.define("bc-appliance-card",$t);var Ys="/config/integrations/integration/bruh_cooking",Xs="M19,19A2,2 0 0,1 17,21H7A2,2 0 0,1 5,19V13H3V11H21V13H19V19M7,13V19H17V13H7M13,5.5C13,6.2 12.6,6.7 12.1,7.1C11.6,7.6 11,8.1 11,9H9.5C9.5,7.8 10.3,7.1 10.9,6.6C11.4,6.2 11.5,5.9 11.5,5.5C11.5,5.1 11.3,4.7 10.8,4.3L11.8,3.2C12.6,3.9 13,4.6 13,5.5M16.5,5.5C16.5,6.2 16.1,6.7 15.6,7.1C15.1,7.6 14.5,8.1 14.5,9H13C13,7.8 13.8,7.1 14.4,6.6C14.9,6.2 15,5.9 15,5.5C15,5.1 14.8,4.7 14.3,4.3L15.3,3.2C16.1,3.9 16.5,4.6 16.5,5.5Z",Dt=class extends E{constructor(){super(),this.appliances=[],this.shared=tt,this.now=Date.now()}willUpdate(){se(this,this.hass)}render(){let e=K(this.hass);if(!this.appliances.length)return this.renderEmpty(e);let r=this.groups(),o=r.length>1||r[0]?.areaId!==null;return r.map(n=>h`
        <section class="area" aria-label=${n.name??e("overview.no_area")}>
          ${o?h`<h2>${n.name??e("overview.no_area")}</h2>`:f}
          <div class="grid">
            ${Be(n.appliances,a=>a.appliance.device_id,a=>h`<bc-appliance-card
                .hass=${this.hass}
                .appliance=${a.appliance}
                .shared=${this.shared}
                .now=${this.now}
              ></bc-appliance-card>`)}
          </div>
        </section>
      `)}groups(){let e=this.hass,r=[this.appliances,e?.devices,e?.areas,e?.language,e?.locale];return(!this.grouped||r.some((o,n)=>o!==this.grouped.key[n]))&&(this.grouped={key:r,groups:nn(this.appliances,e)}),this.grouped.groups}renderEmpty(e){let r=this.hass?.user?.is_admin===!0;return h`<div class="empty">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d=${Xs}></path></svg>
      <h2>${e("overview.empty_title")}</h2>
      <p>${e(r?"overview.empty_text":"overview.empty_text_user")}</p>
      ${r?h`<a class="bc-button primary" href=${Ys} @click=${Xt}>
            ${e("overview.empty_link")}
          </a>`:f}
    </div>`}};Dt.properties={hass:{attribute:!1},appliances:{attribute:!1},shared:{attribute:!1},now:{attribute:!1}},Dt.styles=[ae,ie,P`
      :host {
        display: block;
        color: var(--bc-text);
      }
      .area + .area {
        margin-top: 28px;
      }
      /* A section title over the cards, not a caption: as strong as the card names under it. */
      h2 {
        margin: 0 4px 10px;
        font-size: 18px;
        font-weight: 500;
        line-height: 1.4;
        color: var(--bc-text);
      }
      .grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr));
        gap: 16px;
        align-items: stretch;
      }
      .empty {
        display: flex;
        flex-direction: column;
        align-items: center;
        max-width: 420px;
        margin: 10vh auto 0;
        padding: 0 16px;
        text-align: center;
      }
      .empty svg {
        width: 56px;
        height: 56px;
        fill: var(--bc-muted);
        opacity: 0.6;
      }
      .empty h2 {
        margin: 16px 0 4px;
        font-size: 20px;
        color: var(--bc-text);
      }
      .empty p {
        margin: 0 0 20px;
        color: var(--bc-muted);
        line-height: 1.5;
      }
    `];customElements.get("bc-overview")||customElements.define("bc-overview",Dt);var el="M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z",tl="M20,11V13H8L13.5,18.5L12.08,19.92L4.16,12L12.08,4.08L13.5,5.5L8,11H20Z",rl="M11,15H13V17H11V15M11,7H13V13H11V7M12,2C6.47,2 2,6.5 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M12,20A8,8 0 0,1 4,12A8,8 0 0,1 12,4A8,8 0 0,1 20,12A8,8 0 0,1 12,20Z",Ot=class extends E{constructor(){super();this.subscription=new er(r=>{this.message={appliances:Array.isArray(r?.appliances)?r.appliances:[],oven_modes:Array.isArray(r?.oven_modes)?r.oven_modes:[],presets:Array.isArray(r?.presets)?r.presets:[]},this.error=null},r=>{this.error=Wr(r)});this.announcer=new Wt;this.shared={from:null,value:oo([],[])};this.openedFromOverview=!1;this.tick=()=>{this.now=Date.now(),this.timer=setTimeout(this.tick,1e3-this.now%1e3+5)};this.onOpen=r=>{this.openedFromOverview=!0,Yt(qr(this.route?.prefix,{view:"appliance",deviceId:r.detail.deviceId}))};this.narrow=!1,this.message=null,this.error=null,this.now=Date.now(),this.announcement=""}connectedCallback(){super.connectedCallback(),this.toggleAttribute("framed",!!this.parentElement?.style.paddingTop),this.tick(),this.subscription.connect(this.hass?.connection)}disconnectedCallback(){super.disconnectedCallback(),clearTimeout(this.timer),this.timer=void 0,this.subscription.disconnect()}get appliances(){return this.message?.appliances??null}sharedData(){return this.shared.from!==this.message&&(this.shared={from:this.message,value:oo(this.message?.oven_modes,this.message?.presets)}),this.shared.value}willUpdate(r){se(this,this.hass),r.has("hass")&&this.isConnected&&this.subscription.connect(this.hass?.connection),(r.has("hass")||r.has("message"))&&this.hass&&this.appliances&&this.announce(this.hass,this.appliances)}announce(r,o){let n=K(r),a=this.sharedData(),i=o.map(l=>{let c=pt(l,r,n,this.now,a),d="idle";try{d=ct(l).phase(c)}catch{}return{id:l.device_id,name:at(l,r),phase:d,error:d==="error"?ze(c):null}}),s=this.announcer.observe(i,n);s&&(this.announcement=s===this.announcement.replace(/​$/,"")?`${s}\u200B`:s)}updated(r){if(!r.has("route"))return;let o=r.get("route"),n=Jt(o?.path),a=Jt(this.route?.path);a.view==="overview"&&(this.openedFromOverview=!1),!(!o||n.view===a.view)&&this.restoreFocus(n)}async restoreFocus(r){let o=document.activeElement;if(o&&o!==document.body&&!this.shadowRoot?.activeElement)return;let n;if(r.view==="overview")n=this.renderRoot.querySelector(".toolbar .icon-button");else{let a=this.renderRoot.querySelector("bc-overview");await a?.updateComplete,n=[...a?.shadowRoot?.querySelectorAll("bc-appliance-card")??[]].find(i=>i.appliance?.device_id===r.deviceId)}n?.focus({preventScroll:!0})}shown(){let r=Jt(this.route?.path),o=this.appliances??[],n=o.length===1;return r.view==="overview"?n?{route:{view:"appliance",deviceId:o[0].device_id},appliance:o[0],single:n}:{route:r,appliance:void 0,single:n}:{route:r,appliance:o.find(a=>a.device_id===r.deviceId),single:n}}render(){let r=K(this.hass),o=this.shown();return h`
      ${this.renderToolbar(r,o)}
      <main class="content">${this.renderContent(r,o)}</main>
      <div class="visually-hidden" role="status" aria-live="polite" aria-atomic="true">${this.announcement}</div>
    `}panelTitle(r){return this.panel?.title||r("panel.title")}renderToolbar(r,o){let n=o.route.view==="appliance"&&!o.single,a=f;n?a=this.iconButton(tl,r("panel.back"),()=>this.showOverview()):(this.narrow||this.hass?.dockedSidebar==="always_hidden")&&(a=this.iconButton(el,r("panel.menu"),()=>this.toggleMenu()));let i=o.appliance&&o.route.view==="appliance"?at(o.appliance,this.hass):this.panelTitle(r);return h`<header class="toolbar ${a===f?"":"with-button"}">
      ${a}
      <h1 class="title">${i}</h1>
    </header>`}iconButton(r,o,n){return h`<button type="button" class="icon-button" aria-label=${o} title=${o} @click=${n}>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d=${r}></path></svg>
    </button>`}renderContent(r,o){if(!this.appliances)return this.error?h`<div class="state" role="alert">
          <svg class="state-icon" viewBox="0 0 24 24" aria-hidden="true"><path d=${rl}></path></svg>
          <h2>${r("overview.error_title")}</h2>
          <p>${this.error}</p>
          <button type="button" class="bc-button primary" @click=${()=>this.retry()}>${r("overview.retry")}</button>
        </div>`:h`<div class="state">
        <div class="spinner" role="progressbar" aria-label=${r("overview.loading")}></div>
        <p>${r("overview.loading")}</p>
      </div>`;let n=this.sharedData();return o.route.view==="overview"?h`<bc-overview
        .hass=${this.hass}
        .appliances=${this.appliances}
        .shared=${n}
        .now=${this.now}
        @bc-open-appliance=${this.onOpen}
      ></bc-overview>`:o.appliance?h`<bc-appliance-view
      .hass=${this.hass}
      .appliance=${o.appliance}
      .shared=${n}
      .narrow=${this.narrow}
      .now=${this.now}
    ></bc-appliance-view>`:h`<div class="state">
        <h2>${r("overview.not_found_title")}</h2>
        <p>${r("overview.not_found_text")}</p>
        <button type="button" class="bc-button primary" @click=${()=>this.showOverview()}>${r("overview.back")}</button>
      </div>`}showOverview(){if(this.openedFromOverview){this.openedFromOverview=!1,history.back();return}Yt(qr(this.route?.prefix,{view:"overview"}),{replace:!0})}toggleMenu(){this.dispatchEvent(new CustomEvent("hass-toggle-menu",{bubbles:!0,composed:!0}))}retry(){this.error=null,this.subscription.retry()}};Ot.properties={hass:{attribute:!1},narrow:{type:Boolean,reflect:!0},route:{attribute:!1},panel:{attribute:!1},message:{state:!0},error:{state:!0},now:{state:!0},announcement:{state:!0}},Ot.styles=[ae,ie,P`
      /* The page scrolls, not the panel: Home Assistant gives a custom panel no fixed height.
         The toolbar sticks to the top instead, and the full view's drawing below it. */
      :host {
        --bc-inset-top: var(--safe-area-inset-top, 0px);
        --bc-inset-bottom: var(--safe-area-inset-bottom, 0px);
        --bc-inset-left: var(--safe-area-content-inset-left, var(--safe-area-inset-left, 0px));
        --bc-inset-right: var(--safe-area-content-inset-right, var(--safe-area-inset-right, 0px));
        --bc-toolbar-height: calc(var(--header-height, 56px) + var(--bc-inset-top));
        display: flex;
        flex-direction: column;
        min-height: 100%;
        background: var(--bc-page-bg);
        color: var(--bc-text);
        -webkit-font-smoothing: antialiased;
      }
      :host([framed]) {
        margin: calc(-1 * var(--bc-inset-top)) calc(-1 * var(--bc-inset-right)) calc(-1 * var(--bc-inset-bottom))
          calc(-1 * var(--bc-inset-left));
      }
      .toolbar {
        position: sticky;
        top: 0;
        z-index: 2;
        display: flex;
        flex: none;
        align-items: center;
        box-sizing: border-box;
        height: var(--bc-toolbar-height);
        padding: var(--bc-inset-top) calc(12px + var(--bc-inset-right)) 0 calc(12px + var(--bc-inset-left));
        background: var(--app-header-background-color, var(--bc-page-bg));
        color: var(--app-header-text-color, var(--bc-text));
        border-bottom: var(--app-header-border-bottom, none);
      }
      .title {
        flex: 1;
        min-width: 0;
        margin: 0 0 0 12px;
        overflow: hidden;
        font-size: 20px;
        font-weight: 400;
        line-height: 1.4;
        white-space: nowrap;
        text-overflow: ellipsis;
      }
      .with-button .title {
        margin-inline-start: 24px;
      }
      .icon-button {
        display: grid;
        flex: none;
        place-items: center;
        width: 48px;
        height: 48px;
        padding: 0;
        border: none;
        border-radius: 50%;
        background: none;
        color: inherit;
        cursor: pointer;
        -webkit-tap-highlight-color: transparent;
      }
      .icon-button:hover {
        background: var(--bc-control-bg);
      }
      .icon-button:focus-visible {
        outline: 2px solid var(--bc-accent);
        outline-offset: -2px;
      }
      .icon-button svg {
        width: 24px;
        height: 24px;
        fill: currentColor;
      }
      .content {
        flex: 1;
        box-sizing: border-box;
        padding: 16px calc(16px + var(--bc-inset-right)) calc(16px + var(--bc-inset-bottom)) calc(16px + var(--bc-inset-left));
      }
      :host([narrow]) .content {
        padding: 12px calc(12px + var(--bc-inset-right)) calc(12px + var(--bc-inset-bottom)) calc(12px + var(--bc-inset-left));
      }
      .state {
        display: flex;
        flex-direction: column;
        align-items: center;
        max-width: 420px;
        margin: 12vh auto 0;
        text-align: center;
        color: var(--bc-muted);
      }
      .state-icon {
        width: 56px;
        height: 56px;
        margin-bottom: 16px;
        fill: var(--bc-muted);
        opacity: 0.6;
      }
      .state h2 {
        margin: 0 0 4px;
        font-size: 20px;
        font-weight: 500;
        color: var(--bc-text);
      }
      .state p {
        margin: 8px 0 20px;
        line-height: 1.5;
      }
      .spinner {
        width: 36px;
        height: 36px;
        box-sizing: border-box;
        border: 3px solid var(--bc-control-bg);
        border-top-color: var(--bc-accent);
        border-radius: 50%;
        animation: spin 0.9s linear infinite;
      }
      @keyframes spin {
        to {
          transform: rotate(360deg);
        }
      }
      @media (prefers-reduced-motion: reduce) {
        .spinner {
          animation: none;
        }
      }
      .visually-hidden {
        position: absolute;
        width: 1px;
        height: 1px;
        margin: -1px;
        overflow: hidden;
        clip: rect(0 0 0 0);
        white-space: nowrap;
      }
    `];customElements.get("bruh-cooking-panel")||customElements.define("bruh-cooking-panel",Ot);
