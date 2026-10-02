// 중량 탭 자체 검증: node wt/test_wt.js  (명세 §7 예시 BOM)
const { chromium } = require('playwright'); const assert=require('assert');
(async()=>{const b=await chromium.launch();const p=await b.newPage({viewport:{width:1600,height:960}});
const errs=[];p.on('pageerror',e=>errs.push(e.message));p.on('console',m=>{if(m.type()==='error')errs.push(m.text())});p.on('dialog',d=>d.accept());
await p.goto('file://'+__dirname+'/harness_gauge_v8.html');await p.waitForTimeout(400);
for(const i of [0,1,2,3,4,5,6]){await p.evaluate(i=>ST(i),i);await p.waitForTimeout(150);}
await p.evaluate(()=>ST(7));
const bom=['NO\t품명\t수량\t단위\t규격/품번\t메이커\t비고',
 '1\t전선\t59.5\tm\tFLRY-B 2.0\t\t',
 '2\t전선\t3.7\tM\tAVSS 1.25\t\t',
 '3\t전선\t27.8\tm\tFLRY-B 0.5\t\t',
 '4\t코르게이트 튜브 Ø10\t10\tm\t\t\t',
 '5\t열수축튜브\t0.5\tm\tHST\t\t',
 '6\tCONN HOUSING 12P\t2\tEA\tMG610335\tKET\t',
 '7\tTERMINAL 025\t20\tEA\tXX-025\tKET\t',
 '8\tBOOT\t1\tEA\t\t\t',
 '9\tRETAINER\t2\t\t\t\t'].join('\n');
await p.click('text=📋 BOM 붙여넣기');await p.fill('#wtta',bom);await p.click('#wtpaste >> text=적용');await p.waitForTimeout(200);
const r=await p.evaluate(()=>{const R=wtCalc();return{n:R.rows.length,cats:R.rows.map(x=>x.it.cat),wire:R.byCat.wire,tube:R.byCat.tube,miss:R.miss,refG:R.refG,raw:R.raw,tsub:R.tsub,hsMiss:R.rows[4].u.miss}});
console.log(r);
assert.equal(r.n,9);
assert.deepEqual(r.cats,['wire','wire','wire','tube','tube','conn','term','seal','seal']);
assert(Math.abs(r.wire-1468.1)<1,'wire≈1469g');               // 59.5×21 + 3.7×14 + 27.8×6
assert(Math.abs(r.tsub-r.wire*0.05)<1e-6,'tape 5%');
assert.equal(r.hsMiss,'내경 선택 필요');                         // 내경 없는 열수축튜브는 사용자 선택
// 내경 선택 → 계산 반영, 단위중량 직접 수정 → 확인값
await p.evaluate(()=>{wtSet(4,'dia','6');wtSet(0,'uw','20');});
const r2=await p.evaluate(()=>{const R=wtCalc();return{miss:R.miss,u0:R.rows[0].u,hs:R.rows[4].sub}});
assert.equal(r2.miss,0);assert.equal(r2.u0.ref,'');assert.equal(r2.u0.v,20);assert(Math.abs(r2.hs-1)<1e-9);
// 실측 보정
await p.evaluate(()=>{wtH().meas='2000';wtKeepK(2000/wtCalc().raw);});
const r3=await p.evaluate(()=>{const R=wtCalc();return{pred:R.pred,k:R.k}});assert(Math.abs(r3.pred-2000)<0.01);
// CAD 텍스트(공백 2칸) + 머리행 없음
const cad=await p.evaluate(()=>wtParse('1   전선   12.5   m   AVSS 0.85   SUMI\n2   커넥터   1   EA   ABC-123'));
assert.equal(cad.length,2);assert.equal(cad[0].qty,12.5);assert.equal(cad[0].unit,'m');assert.equal(cad[1].cat,'conn');
// 보간 (AVSS 0.75 는 표에 없음)
const ip=await p.evaluate(()=>wtUnitW({cat:'wire',name:'AVSS 0.75',unit:'m'}));assert(ip.v>6.2&&ip.v<9.6&&/보간/.test(ip.ref));
// 품번 라이브러리 중량 열 + 기존 PLIB(wt 없음) 호환
await p.evaluate(()=>ST(5));await p.waitForTimeout(200);
assert(await p.$('text=중량 (g)'));
await p.evaluate(()=>ST(7));await p.screenshot({path:'/tmp/wt_tab.png'});
await p.evaluate(()=>{toggleTheme()});await p.waitForTimeout(600);await p.screenshot({path:'/tmp/wt_tab_light.png'});
assert.deepEqual(errs,[]);console.log('ALL OK');await b.close();})().catch(e=>{console.error(e);process.exit(1)});
