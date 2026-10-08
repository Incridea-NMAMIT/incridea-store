export default function health(_req,res){
 if(!['VPS','VERCEL'].includes(process.env.PROD_ENV??'VERCEL'))return res.status(503).json({status:'unavailable'});
 res.setHeader('Cache-Control','no-store');
 return res.status(200).json({status:'ready',releaseSha:process.env.RELEASE_SHA??process.env.VERCEL_GIT_COMMIT_SHA??'development'});
}
