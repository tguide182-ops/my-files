const {chromium}=require('playwright');const http=require('http');const fs=require('fs');const path=require('path');const {spawn}=require('child_process');
const root=__dirname;const out=process.argv[2];const FPS=+process.argv[3]||30;const DUR=15;
const srv=http.createServer((q,s)=>{const f=path.join(root,decodeURIComponent(q.url.split('?')[0]));fs.readFile(f,(e,d)=>{if(e){s.writeHead(404);s.end();return}s.writeHead(200,{'content-type':f.endsWith('.html')?'text/html':'text/javascript'});s.end(d)})}).listen(8123);
(async()=>{const b=await chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader','--no-sandbox']});
const p=await b.newPage({viewport:{width:1280,height:720}});p.on('console',m=>console.log('c:',m.text()));p.on('pageerror',e=>console.log('err',e.message));
await p.goto('http://localhost:8123/index.html');await p.waitForFunction('window.ready',null,{timeout:60000});
const ff=spawn('ffmpeg',['-y','-f','image2pipe','-framerate',String(FPS),'-c:v','mjpeg','-i','-','-c:v','libx264','-pix_fmt','yuv420p','-crf','18','-preset','medium',out],{stdio:['pipe','inherit','inherit']});
const n=process.argv[4]?+process.argv[4]:FPS*DUR;const t0=Date.now();
for(let i=0;i<n;i++){await p.evaluate(t=>window.renderAt(t),i/FPS);const buf=await p.screenshot({type:'jpeg',quality:93});if(!ff.stdin.write(buf))await new Promise(r=>ff.stdin.once('drain',r));if(i%30==0)console.log(i,((Date.now()-t0)/1000).toFixed(1)+'s')}
ff.stdin.end();await new Promise(r=>ff.on('close',r));await b.close();srv.close()})();
