const {chromium}=require('playwright');const {spawn}=require('child_process');
(async()=>{const b=await chromium.launch({args:['--no-sandbox']});const p=await b.newPage({viewport:{width:1280,height:720}});p.on('pageerror',e=>console.log('err',e.message));
await p.goto('file://'+__dirname+'/index.html');
const out=process.argv[2];
if(out.endsWith('.png')){for(const t of process.argv.slice(3)){await p.evaluate(t=>renderAt(t),+t);await p.locator('#c').screenshot({path:`s_${t}.png`})}await b.close();return}
const FPS=30;const ff=spawn('ffmpeg',['-y','-loglevel','error','-f','image2pipe','-framerate','30','-c:v','mjpeg','-i','-','-c:v','libx264','-pix_fmt','yuv420p','-crf','17',out],{stdio:['pipe','inherit','inherit']});
for(let i=0;i<300;i++){await p.evaluate(t=>renderAt(t),i/FPS);const d=await p.evaluate(()=>document.getElementById('c').toDataURL('image/jpeg',0.95));ff.stdin.write(Buffer.from(d.split(',')[1],'base64'))}
ff.stdin.end();await new Promise(r=>ff.on('close',r));await b.close()})();
