// Node-only logic tests; no browser automation or backend calls.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');

function element() {
  return {textContent:'',innerHTML:'',style:{},classList:{add(){},remove(){},toggle(){}},addEventListener(){},duration:20,pause(){},load(){},removeAttribute(){}};
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
      fetch:async()=>({ok:true,json:async()=>({source:'Test catalog',rules:Object.values(rules).map(r=>({...r,point:r.paragraph,text:r.description}))})}),
      setTimeout(fn){fn();}, console, URL:class extends URL {static createObjectURL(){return 'blob:test';} static revokeObjectURL(){}},
    });
    vm.runInContext(fs.readFileSync(root+'app.js','utf8'),ctx);
    await vm.runInContext('loadRules()',ctx);
    vm.runInContext('renderResult({verdict:"no_violation", violations:[]})',ctx);
    assert.equal(elements.verdictTitle.textContent,'Нарушение не обнаружено');
    assert(elements.verdictText.textContent.includes('не подтверждение соблюдения всех правил'));
    vm.runInContext('renderResult({verdict:"no_violation",coverage_status:"partial",violations:[],rule_checks:[{title:"<check>",status:"not_implemented",reason:"Нужны данные"}]})',ctx);
    assert.equal(elements.verdictTitle.textContent,'Нарушение не обнаружено');
    assert(elements.ruleChecks.innerHTML.includes('&lt;check&gt;'));
    assert(elements.ruleChecks.innerHTML.includes('детектор не реализован'));
    vm.runInContext('renderResult({verdict:"violation",violations:[{type:"cash_unattended",timecode_sec:10,description:"<unsafe>",evidence_frames:[]}]})',ctx);
    assert(elements.violations.innerHTML.includes('Возможное оставление банкнот'));
    assert(!elements.violations.innerHTML.includes('unsafe'));
    assert(elements.violations.innerHTML.includes('Предполагаемое нарушение. Требует перепроверки.'));
    assert.equal(elements.verdictTitle.textContent,'Обнаружены признаки возможных нарушений');
    const sourceHtml = vm.runInContext('ruleHtml({type:"Телефон",source:"https://adilet.zan.kz/rus/docs/V1900019680",paragraph:"п. 12",source_verified:false})',ctx);
    assert(sourceHtml.includes('href="https://adilet.zan.kz/rus/docs/V1900019680"'));
    assert(sourceHtml.includes('п. 12') && sourceHtml.includes('не проверена'));
    assert(vm.runInContext('ruleHtml({type:"Еда",source:null})',ctx).includes('источник не установлен'));
    assert(!vm.runInContext('ruleHtml({source:"javascript:alert(1)"})',ctx).includes('href='));
    ctx.legalSample={...rules.bag_left_by_visitor,rule_title:rules.bag_left_by_visitor.title};
    const detailed=vm.runInContext('ruleHtml(legalSample)',ctx);
    for(const label of ['Правило:','Основание проверки:','Источник:']) assert(detailed.includes(label));
    for(const label of ['Условия применения','Ограничения детектора','Сверка источника','Требование / что необходимо установить','Статус:','Adilet.pdf']) assert(!detailed.includes(label));
    ctx.legalSample={...rules.pc_not_shutdown};
    const internal=vm.runInContext('ruleHtml(legalSample)',ctx);
    assert(!internal.includes('href=') && internal.includes('Требуется внутренний регламент банка'));
    ctx.legalSample={rule_title:'<script>evil</script>',source:'https://adilet.zan.kz.evil.test/x',requirement:'<img src=x>',limits:'<b>x</b>',legal_status:'<svg>'};
    const unsafe=vm.runInContext('ruleHtml(legalSample)',ctx);
    assert(!unsafe.includes('href=') && !unsafe.includes('<script>'));
    assert(unsafe.includes('&lt;script&gt;'));
    for(const fragment of ['&lt;img','&lt;b&gt;','&lt;svg&gt;']) assert(!unsafe.includes(fragment));
    assert(!vm.runInContext('ruleHtml({source:"https://user:pass@adilet.zan.kz/x"})',ctx).includes('href='));
    if(variant==='forte_с_правилами') {
      assert(elements.catalogList.innerHTML.includes('Основание проверки:'));
      assert(!elements.catalogList.innerHTML.includes('Условия применения'));
    }
    for(const rule of Object.values(rules).filter(r=>r.mode==='automatic_candidate')) {
      ctx.eventSample={...rule,rule_id:rule.id,timecode_sec:15,evidence_frames:[],description:'TECHNICAL_DESCRIPTION_SENTINEL',limits:'TECHNICAL_LIMITS_SENTINEL'};
      const card=vm.runInContext('violationHtml(eventSample,0)',ctx);
      assert(card.includes('Предполагаемое нарушение. Требует перепроверки.'));
      assert(!card.includes('TECHNICAL_') && !card.includes('Условия применения'));
      for(const label of ['Правило:','Основание проверки:','Источник:']) assert(card.includes(label));
    }
    vm.runInContext('renderResult({verdict:"no_violation",violations:[],rule_checks:[{title:"Проверка",status:"insufficient_evidence",reason:"TECHNICAL_REASON_SENTINEL"}]})',ctx);
    assert(!elements.ruleChecks.innerHTML.includes('TECHNICAL_REASON_SENTINEL'));
    assert(elements.ruleChecks.innerHTML.includes('Недостаточно данных'));
    ctx.fetch=async()=>({ok:true,json:async()=>({status:'done',verdict:'no_violation',violations:[]})});
    assert.equal((await vm.runInContext('waitForResult("test")',ctx)).verdict,'no_violation');
    ctx.fetch=async()=>({ok:true,json:async()=>({status:'done',result:{verdict:'violation',violations:[]}})});
    assert.equal((await vm.runInContext('waitForResult("test")',ctx)).verdict,'violation');
    ctx.fetch=async()=>({ok:true,json:async()=>({status:'done',result:null})});
    await assert.rejects(vm.runInContext('waitForResult("test")',ctx),/Некорректный ответ/);
    vm.runInContext('selectFile({name:"jury.mp4",size:1024})',ctx);
    assert.equal(vm.runInContext('state.file.name',ctx),'jury.mp4');
    vm.runInContext('state.isBusy=true; selectFile({name:"other.mov",size:1024})',ctx);
    assert.equal(vm.runInContext('state.file.name',ctx),'jury.mp4');
    vm.runInContext('state.isBusy=false; resetAll()',ctx);
    assert.equal(vm.runInContext('state.file',ctx),null);
    for(const [file,hash] of Object.entries({
      'style.css':'6A1E5EB4C381FBB535E1E9F4212029D1D129F1A0097A3D83F68201A27687E3DE',
      'images/logo.png':'90F56E9BBB34206AE614CC983FAD0183CA215805EE9B0261F67171752641B984',
      'images/icon.png':'296B08525DAC9F7957715F940BC7B4F453A614CE54531FBEB12360F100260308',
    })) assert.equal(crypto.createHash('sha256').update(fs.readFileSync(root+file)).digest('hex').toUpperCase(),hash);
    console.log(variant+': text, result parsing, escaping, catalog and original assets OK');
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
