/* Local DCF discussion: safe text rendering, explicit selection and application. */
let discussionId=null,advisorBusy=false;
const scenarioDefaults={bull_growth_shift:5,bull_margin_shift:2,bull_capex_shift:0,bull_nwc_shift:-1,bear_growth_shift:-5,bear_margin_shift:-3,bear_capex_shift:.5,bear_nwc_shift:2};
const scenarioBox=$('scenarioFields');
for(const [key,value] of Object.entries(scenarioDefaults)){
  const label=document.createElement('label');label.htmlFor=key;label.textContent=key.replaceAll('_',' ')+' (percentage points)';
  const input=document.createElement('input');input.id=key;input.type='number';input.step='.1';input.value=value;scenarioBox.append(label,input);percent.push(key);
}
const basePayload=payload;
payload=()=>({...basePayload(),discussion_id:discussionId});
const showAdvisor=()=>$('discussionBody').hidden=$('assumptionMethod').value==='manual';
$('assumptionMethod').onchange=showAdvisor;
function clearAdvisor(){discussionId=null;$('discussionHistory').replaceChildren();$('suggestionList').replaceChildren();$('researchSources').replaceChildren();txt('advisorStatus','Load a company, then enter your view or question.');txt('advisorImpact','');$('applySuggestions').disabled=true;}
for(const [id,event] of [['market','onchange'],['symbol','oninput'],['sector','onchange']]){const old=$(id)[event];$(id)[event]=(...args)=>{clearAdvisor();if(old)old(...args);};}
const previewHandler=$('preview').onclick;$('preview').onclick=async()=>{clearAdvisor();await previewHandler();};
function entry(role,text){const p=document.createElement('p');p.style.whiteSpace='pre-wrap';const b=document.createElement('b');b.textContent=role+': ';p.append(b,document.createTextNode(text));$('discussionHistory').append(p);}
function human(key,value){return key==='reserve'?value.toLocaleString(undefined,{maximumFractionDigits:2})+' million':(value*100).toFixed(2)+(key.includes('_shift')?' pp':'%');}
$('discussAssumptions').onclick=async()=>{
  if(!snapshotId){txt('advisorStatus','Load company data first.');return;}
  if($('sector').value!=='non_financial'){txt('advisorStatus','Corporate DCF discussion is available for non-financial companies only.');return;}
  const message=$('userThesis').value.trim();if(!message){txt('advisorStatus','Enter your view or a question.');return;}
  const boundSnapshot=snapshotId;advisorBusy=true;$('discussAssumptions').disabled=true;$('newDiscussion').disabled=true;$('generate').disabled=true;$('applySuggestions').disabled=true;
  txt('advisorStatus','Researching public sources and discussing with DeepSeek…');
  try{
    const d=await api('/api/assumption-discuss',{snapshot_id:snapshotId,discussion_id:discussionId,sector:$('sector').value,overrides:payload().overrides,message,links:$('researchLinks').value.split('\n').map(s=>s.trim()).filter(Boolean),refresh:$('refreshResearch').checked});
    let j;do{await new Promise(r=>setTimeout(r,2000));j=await (await fetch('/api/job/'+d.id)).json();if(boundSnapshot!==snapshotId)throw Error('Company changed. Discarded the previous discussion result.');txt('advisorStatus',j.message);}while(j.status==='running');
    if(j.status!=='complete')throw Error(j.message||'Discussion failed');discussionId=j.discussion_id;const a=j.answer;entry('Your view',message);entry('DeepSeek',a.reply);$('userThesis').value='';$('researchLinks').value='';$('refreshResearch').checked=false;
    $('suggestionList').replaceChildren();a.suggestions.forEach((s,i)=>{
      const box=document.createElement('div');box.className='suggestion';const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.dataset.suggestionIndex=i;check.style.width='auto';check.style.marginRight='8px';label.append(check,document.createTextNode(s.parameter.replaceAll('_',' ')+' — '+human(s.parameter,a.current_parameters[s.parameter])+' → '+human(s.parameter,s.value)));box.append(label);
      for(const text of ['Range: '+human(s.parameter,s.low)+' to '+human(s.parameter,s.high),'Basis: '+s.basis+'; sources: '+(s.source_ids.join(', ')||'no retrieved evidence'),s.rationale,'Counterargument: '+s.counterargument]){const p=document.createElement('p');p.className='note';p.textContent=text;box.append(p);} $('suggestionList').append(box);
    });
    txt('advisorImpact','All proposed changes, not yet applied — '+['bull','base','bear'].map(s=>s+': '+a.currency+' '+a.before[s].toFixed(2)+' → '+a.after[s].toFixed(2)).join(' · '));
    $('researchSources').replaceChildren();for(const s of a.sources){const p=document.createElement('p'),link=document.createElement('a');try{const url=new URL(s.url);if(url.protocol==='https:'){link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';}}catch{}link.textContent=s.id+' · '+s.title;p.append(link,document.createTextNode(' — '+s.status+'; published: '+(s.published_at||'unknown')+'; retrieved: '+s.retrieved_utc.slice(0,10)));$('researchSources').append(p);}
    if(!a.sources.length){const p=document.createElement('p');p.textContent='No usable sources were retrieved. Suggestions are hypotheses pending evidence.';$('researchSources').append(p);}
    for(const warning of a.research_warnings){const p=document.createElement('p');p.className='note';p.textContent=warning;$('researchSources').append(p);}
    $('applySuggestions').disabled=!a.suggestions.length;txt('advisorStatus','Turn '+a.turn_count+' of 8. Select suggestions to apply, or continue discussing. Manual values are unchanged.');
  }catch(e){txt('advisorStatus',e.message);}finally{advisorBusy=false;$('discussAssumptions').disabled=false;$('newDiscussion').disabled=false;$('generate').disabled=false;}
};
$('applySuggestions').onclick=async()=>{
  const selected=[...$('suggestionList').querySelectorAll('input:checked')].map(x=>Number(x.dataset.suggestionIndex));
  if(!selected.length){txt('advisorStatus','Select at least one suggestion.');return;}
  try{const r=await api('/api/assumption-apply',{discussion_id:discussionId,snapshot_id:snapshotId,selected,overrides:payload().overrides,sector:$('sector').value});for(const [k,v] of Object.entries(r.overrides))$(k).value=Number((v*(percent.includes(k)?100:1)).toFixed(8));txt('advisorImpact','Selected changes applied — '+['bull','base','bear'].map(s=>s+': '+r.currency+' '+r.before[s].toFixed(2)+' → '+r.after[s].toFixed(2)).join(' · '));txt('advisorStatus','Selected suggestions applied. You can edit any value manually before generating the report.');}catch(e){txt('advisorStatus',e.message);}
};
$('newDiscussion').onclick=()=>{clearAdvisor();};
showAdvisor();
