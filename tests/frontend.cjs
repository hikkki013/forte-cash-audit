// Node-only logic tests; no browser automation or backend calls.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');

function element() {
  return {textContent:'',innerHTML:'',style:{},classList:{add(){},remove(){},toggle(){}},addEventListener(){},duration:20};
}

(async () => {
  for (const variant of ['forte_с_правилами','forte_без_правил']) {
    const root='frontend/'+variant+'/';
    const elements={};
    const rules=JSON.parse(fs.readFileSync(root+'rules.json','utf8'));
    const ctx=vm.createContext({
      document:{getElementById(id){
        if(variant==='forte_без_правил' && id.startsWith('catalog')) return null;
        return elements[id] ??= element();
      },querySelectorAll(){return [];},addEventListener(){}},
      fetch:async()=>({ok:true,json:async()=>rules}),
      setTimeout(fn){fn();}, console,
    });
    vm.runInContext(fs.readFileSync(root+'app.js','utf8'),ctx);
    await vm.runInContext('loadRules()',ctx);
    vm.runInContext('renderResult({verdict:"no_violation", violations:[]})',ctx);
    assert.equal(elements.verdictTitle.textContent,'По включённому правилу событий нет');
    assert.equal(elements.verdictText.textContent,'Это не подтверждает отсутствие других нарушений.');
    vm.runInContext('renderResult({verdict:"violation",violations:[{type:"cash_unattended",timecode_sec:10,description:"<unsafe>",evidence_frames:[]}]})',ctx);
    assert(elements.violations.innerHTML.includes('Возможное оставление банкнот'));
    assert(elements.violations.innerHTML.includes('&lt;unsafe&gt;'));
    ctx.fetch=async()=>({ok:true,json:async()=>({status:'done',result:{verdict:'violation',violations:[]}})});
    assert.equal((await vm.runInContext('waitForResult("test")',ctx)).verdict,'violation');
    ctx.fetch=async()=>({ok:true,json:async()=>({status:'done',result:null})});
    await assert.rejects(vm.runInContext('waitForResult("test")',ctx),/Некорректный ответ/);
    for(const [file,hash] of Object.entries({
      'style.css':'6A1E5EB4C381FBB535E1E9F4212029D1D129F1A0097A3D83F68201A27687E3DE',
      'images/logo.png':'90F56E9BBB34206AE614CC983FAD0183CA215805EE9B0261F67171752641B984',
      'images/icon.png':'296B08525DAC9F7957715F940BC7B4F453A614CE54531FBEB12360F100260308',
    })) assert.equal(crypto.createHash('sha256').update(fs.readFileSync(root+file)).digest('hex').toUpperCase(),hash);
    console.log(variant+': text, result parsing, escaping, catalog and original assets OK');
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
