// Headless visual regression for a STATIC empty layout. No user browser/session.
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
  for (const width of [1440,390]) {
    await call("Emulation.setDeviceMetricsOverride",{width,height:1100,deviceScaleFactor:1,mobile:width<720});
    await call("Page.navigate",{url:appUrl || pathToFileURL(join(tmpdir(),"RivalSense-layout-review.html")).href});
    let complete=false;
    for(let i=0;i<60&&!complete;i++){const state=await call("Runtime.evaluate",{expression:"document.readyState==='complete' && !!document.querySelector('.brand')?.textContent.includes('RivalSense')",returnByValue:true});complete=state.result.value===true;if(!complete)await new Promise(resolve=>setTimeout(resolve,100));}
    if(!complete || runtimeErrors)throw new Error("Page failed to render or raised a client runtime exception");
    const metrics=await call("Runtime.evaluate",{expression:"({width:innerWidth,scrollWidth:document.documentElement.scrollWidth})",returnByValue:true});
    console.log(JSON.stringify({kind:appUrl ? "LOCAL_APP_SIGNED_OUT" : "STATIC_LAYOUT_NOT_LIVE",...metrics.result.value}));
    const image=await call("Page.captureScreenshot",{format:"png",captureBeyondViewport:false});
    await writeFile(join(tmpdir(),"RivalSense-"+(appUrl ? "welcome" : "layout")+"-"+width+".png"),Buffer.from(image.data,"base64"));
    if(metrics.result.value.scrollWidth>width) throw new Error("Layout overflows at width "+width);
  }
} finally {socket?.close();browser.kill();}
