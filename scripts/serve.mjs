import {createServer} from 'node:http';
import {readFile, stat} from 'node:fs/promises';
import {resolve, extname} from 'node:path';
if (!['VPS','VERCEL'].includes(process.env.PROD_ENV ?? 'VERCEL')) throw Error('PROD_ENV must be VPS or VERCEL');
const root=resolve(process.env.STORE_PUBLIC_DIR ?? '/app/public');
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.png':'image/png','.webp':'image/webp','.jpg':'image/jpeg','.woff2':'font/woff2'};
const server=createServer(async(req,res)=>{
  res.setHeader('X-Content-Type-Options','nosniff');
  res.setHeader('Referrer-Policy','no-referrer');
  res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src https://raw.githubusercontent.com; frame-ancestors 'none'; base-uri 'self'");
  try {
    const path=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
    if(path==='/health'||path==='/health/ready'){res.setHeader('Cache-Control','no-store');res.setHeader('Content-Type','application/json');res.end(JSON.stringify({status:'ready',releaseSha:process.env.RELEASE_SHA ?? 'development'}));return;}
    if(!['GET','HEAD'].includes(req.method)){res.writeHead(405);res.end();return;}
    let file=resolve(root,'.'+path);
    if(!file.startsWith(root+'/')&&file!==root){res.writeHead(403);res.end();return;}
    if(path==='/'||/^\/apps\/[a-z-]+\/?$/.test(path))file=resolve(root,'index.html');
    if(!(await stat(file)).isFile()){res.writeHead(404);res.end();return;}
    res.setHeader('Content-Type',types[extname(file)]??'application/octet-stream');
    res.setHeader('Cache-Control',path.startsWith('/assets/')?'public,max-age=31536000,immutable':'no-cache');
    res.end(req.method==='HEAD'?undefined:await readFile(file));
  } catch {res.writeHead(404);res.end();}
});
server.listen(Number(process.env.PORT ?? 8080),'0.0.0.0');
for(const signal of ['SIGINT','SIGTERM'])process.once(signal,()=>server.close());
