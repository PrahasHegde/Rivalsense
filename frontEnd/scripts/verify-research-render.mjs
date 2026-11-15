// React form integration check using a genuine saved provider response, replayed over CDP. No user session or live authenticated API claim.
import { spawn } from "node:child_process";
import { mkdtemp, readFile, writeFile, access } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
const executable = process.env.RIVALSENSE_CHROME || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const appUrl = process.argv[2];
if (appUrl && !["http://127.0.0.1:5173/", "http://localhost:5173/"].includes(appUrl)) throw new Error("Only the local demo origin is allowed");
await access(executable);
const profile = await mkdtemp(join(tmpdir(), "rivalsense-layout-"));
const browser = spawn(executable, ["--headless=new","--disable-gpu","--disable-background-networking",
  "--no-first-run","--no-default-browser-check","--remote-debugging-port=0","--user-data-dir="+profile],
  { windowsHide:true, stdio:"ignore" });
const deadline = Date.now()+15000;
let socket;
try {
  let port;
  while (!port && Date.now()<deadline) {
    try { port=(await readFile(join(profile,"DevToolsActivePort"),"utf8")).split("\n")[0]; }
    catch { await new Promise(resolve=>setTimeout(resolve,100)); }
  }
  if (!port) throw new Error("Headless browser did not start");
  const pages=await (await fetch("http://127.0.0.1:"+port+"/json/list")).json();
  const target=pages.find(page=>page.type==="page");
  if (!target) throw new Error("No isolated test page");
  socket=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.addEventListener("open",resolve,{once:true});socket.addEventListener("error",reject,{once:true});});
  let id=0; const pending=new Map(); let runtimeErrors=0;
  socket.addEventListener("message",event=>{if(JSON.parse(event.data).method==="Runtime.exceptionThrown")runtimeErrors++;});
  socket.addEventListener("message",event=>{const value=JSON.parse(event.data);const operation=pending.get(value.id);if(operation){pending.delete(value.id);if(value.error)operation.reject(new Error(value.error.message));else operation.resolve(value.result);}});
  function call(method,params={}) {
    return new Promise((resolve,reject)=>{const requestId=++id;const timer=setTimeout(()=>{pending.delete(requestId);reject(new Error("Browser command timed out"));},10000);pending.set(requestId,{resolve:value=>{clearTimeout(timer);resolve(value);},reject:error=>{clearTimeout(timer);reject(error);}});socket.send(JSON.stringify({id:requestId,method,params}));});
  }
  await call("Page.enable");
  await call("Runtime.enable");
  await call('Emulation.setDeviceMetricsOverride',{width:process.argv.includes('--mobile')?390:1440,height:900,deviceScaleFactor:1,mobile:process.argv.includes('--mobile')});
  await call('Page.navigate',{url:'http://127.0.0.1:5173/'});
  await new Promise(r=>setTimeout(r,1500));
  const live=JSON.parse(await readFile(new URL('../../Backend/research-live.local',import.meta.url),'utf8'));
  let submitted=false;
  socket.addEventListener('message',event=>{
    const msg=JSON.parse(event.data);
    if(msg.method!=='Fetch.requestPaused')return;
    const {requestId,request}=msg.params;
    const path=new URL(request.url).pathname;
    let body=[];
    if(path==='/api/ai/ask'){
      submitted=JSON.parse(request.postData).question===live.question && Object.entries(request.headers).some(([k,v])=>k.toLowerCase()==='authorization'&&v==='Bearer isolated-render-test-token');
      body=live;
    } else if(path==='/api/ai/history')body={items:[],status:'not_configured'};
    call('Fetch.fulfillRequest',{requestId,responseCode:200,responseHeaders:[{name:'Content-Type',value:'application/json'}],body:Buffer.from(JSON.stringify(body)).toString('base64')}).catch(()=>{});
  });
  await call('Fetch.enable',{patterns:[{urlPattern:'http://127.0.0.1:5173/api/*',requestStage:'Request'}]});
  const setupFunction=async function(live){
    const {supabase}=await import('/src/supabase.js');
    supabase.auth.getSession=async()=>({data:{session:{access_token:'isolated-render-test-token'}}});
    const React=(await import('/node_modules/.vite/deps/react.js')).default;
    const {createRoot}=(await import('/node_modules/.vite/deps/react-dom_client.js')).default;
    const Dashboard=(await import('/src/DashBoard.jsx')).default;
    document.getElementById('onboarding').style.display='none';
    const host=document.createElement('div');document.body.append(host);
    createRoot(host).render(React.createElement(Dashboard,{session:{user:{id:'isolated-render-test',user_metadata:{full_name:'Test'}}},signOut:()=>{}}));
  };
  const setup=await call('Runtime.evaluate',{expression:'('+setupFunction.toString()+')('+JSON.stringify(live)+')',awaitPromise:true,returnByValue:true});
  if(setup.exceptionDetails)throw Error('Test setup failed: '+setup.exceptionDetails.text);
  await new Promise(r=>setTimeout(r,400));
  await call('Runtime.evaluate',{expression:"(()=>{const field=document.querySelector('#question');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(field,'Who founded Microsoft and in what year?');field.dispatchEvent(new Event('input',{bubbles:true}));})()"});
  await new Promise(r=>setTimeout(r,100));
  await call('Runtime.evaluate',{expression:"document.querySelector('.research-composer form').requestSubmit()"});
  await new Promise(r=>setTimeout(r,900));
  const check=await call('Runtime.evaluate',{expression:"(()=>{const panel=document.querySelector('.answer-panel');return {mode:'REAL_PROVIDER_RESPONSE_REPLAY_WITH_TEST_AUTH',submitted:window.testSubmitted,answerRendered:!!panel?.querySelector('.answer-text')?.innerText.includes('1975'),clickableSources:panel?.querySelectorAll('a.source-card[href^=https]').length||0,panelTop:panel?.getBoundingClientRect().top,viewportHeight:innerHeight,error:document.querySelector('[role=alert]')?.innerText||null};})()",returnByValue:true});
  check.result.value.submitted=submitted; console.log(JSON.stringify(check.result.value));
  if(runtimeErrors||!check.result.value.answerRendered||!check.result.value.clickableSources||!check.result.value.submitted||check.result.value.panelTop<0||check.result.value.panelTop>300)throw Error('Research action/render failed');
} finally {socket?.close();browser.kill();}
